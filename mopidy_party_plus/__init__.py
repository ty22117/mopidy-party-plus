import os
import json
import random
import re
import time
import logging
import datetime
import threading
import urllib.parse
import urllib.request
from collections import deque

import pykka
import tornado.web
import tornado.websocket
import tornado.ioloop

from mopidy import config, core, ext

__version__ = "1.14.0-NETJAMMER"

# NETJammer's own logger; INFO+ from here (and WARNING+ from anything, incl.
# Mopidy/yt-dlp) is captured into a diagnostics ring buffer, merged with client
# logs, and exposed at /logs so intermittent problems can be pulled after the fact.
logger = logging.getLogger("netjammer")

_log_lock = threading.Lock()
_log_buffer = deque(maxlen=4000)  # [{"ts": float, "level": str, "logger": str, "msg": str, "source": "server"|"client"}]


def _record_log(ts, level, logger_name, msg, source):
    with _log_lock:
        _log_buffer.append(
            {
                "ts": float(ts),
                "level": str(level),
                "logger": str(logger_name),
                "msg": str(msg),
                "source": source,
            }
        )


def _fmt_ts(ts):
    try:
        return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


class DiagnosticsLogHandler(logging.Handler):
    """Captures log records into the diagnostics ring buffer: everything from the
    'netjammer' logger, plus WARNING and above from any logger (Mopidy, yt-dlp...)."""

    def emit(self, record):
        try:
            name = record.name or ""
            if not (name.startswith("netjammer") or record.levelno >= logging.WARNING):
                return
            _record_log(
                record.created, record.levelname, name, record.getMessage(), "server"
            )
        except Exception:
            pass

# Shared, server-side play history so the "back" button works across page
# refreshes and for everyone who joins (it lives as long as Mopidy runs).
_history_lock = threading.Lock()
_history = []               # [{"uri":..., "name":...}] oldest-first, most recent last
_history_suppress_uri = None  # a track whose next "ended" should NOT be recorded (set during a back-jump)

# Radio mode: party-wide, shared between the HTTP toggle and the frontend actor.
# When on, the queue is auto-refilled with songs similar to what's playing.
_radio = {"on": False}
_radio_lock = threading.Lock()
_radio_busy = False  # a refill is currently in flight (guards against overlapping refills)

# Radio Blocklist: songs the user never wants radio to seed from. Keyed by exact
# track URI. Blocking a song also drops the not-yet-played tracks radio spawned
# from it, using _radio_provenance (added-track URI -> set of seed URIs). Both
# live in memory for the life of the Mopidy process and share one lock.
_radio_blocklist = {}   # uri -> name (for display)
_radio_provenance = {}  # added_track_uri -> set(seed_uri), bounded
_radio_pick_artist = {}  # added_track_uri -> artist name radio believed it was (bounded)
# Station steering (all in-memory, guarded by _radio_meta_lock):
_radio_pins = []        # [{kind: track|artist|genre, value, label, artist?, title?}]
_radio_liked = {}       # uri -> {name, artist, title}: thumbed-up picks, used as seeds
_radio_artist_ban = {}  # normalised artist -> display name: thumbed-down artists (session)
_radio_meta_lock = threading.Lock()


class NetjammerFrontend(pykka.ThreadingActor, core.CoreListener):
    """A Mopidy frontend that records every track that finishes/skips into the
    shared history, so the web UI's back button has a real, shared source."""

    def __init__(self, config, core):
        super().__init__()
        self.config = config
        self.core = core
        self._at_end = False  # True when the track that just ended was the last in the queue
        self._ended_at = 0.0  # when that last track ended (to catch only the immediate auto-loop)

    def _set_playback_modes(self, where):
        # We want a plain, linear queue: consume off (keep played tracks for the
        # back button) and repeat/single/random off so the queue STOPS at the end
        # instead of looping back to the first song. Something (e.g. the YouTube
        # autoplayer) turns repeat on, so we assert this on start and on each track.
        try:
            tl = self.core.tracklist
            if tl.get_consume().get():
                tl.set_consume(False)
            if tl.get_repeat().get():
                tl.set_repeat(False)
                logger.info("%s: repeat mode was on -> disabled", where)
            if tl.get_single().get():
                tl.set_single(False)
                logger.info("%s: single mode was on -> disabled", where)
            if tl.get_random().get():
                tl.set_random(False)
                logger.info("%s: random mode was on -> disabled", where)
        except Exception as e:
            logger.warning("%s: could not set playback modes: %r", where, e)

    def on_start(self):
        self._set_playback_modes("startup")
        # Start each session at a sensible default volume instead of full blast.
        try:
            vol = int(_conf(self.config, "default_volume"))
            self.core.mixer.set_volume(vol)
            logger.info("startup: default volume set to %s%%", vol)
        except Exception as e:
            logger.warning("startup: could not set default volume: %r", e)
        # Report which radio sources are usable.
        key = (_conf(self.config, "lastfm_api_key") or "").strip()
        logger.info(
            "startup: radio sources %s; youtube music %s; last.fm key %s -> radio %s",
            ",".join(_radio_sources(self.config)) or "(none)",
            "available" if _ytm_available() else "NOT installed (pip install ytmusicapi)",
            "configured" if key else "not configured",
            "available" if _radio_available(self.config) else "DISABLED",
        )

    def track_playback_started(self, tl_track):
        track = getattr(tl_track, "track", None)
        if track:
            logger.info("playback started: %s [%s]", track.name or "?", track.uri)
        # Keep repeat/single off (in case something re-enabled them).
        self._set_playback_modes("track start")
        # End-of-queue guard: once the LAST track has ended (the queue reached its
        # end with repeat off), Mopidy won't advance on its own. So if playback
        # then jumps back to the FIRST track, something looped the queue -- an
        # external autoplayer, or (commonly) a device still running an OLD cached
        # client whose removed playback watchdog replays track #0. Stop it. We stay
        # "armed" for a window so repeated loop attempts (e.g. a stale client's
        # watchdog retrying every few seconds) are also caught, and disarm as soon
        # as a real track plays (index > 0, e.g. a freshly-added song) or the
        # window lapses. Skipped while radio is on (there we want continuation).
        try:
            armed = self._at_end
            self._at_end = False  # disarm by default; re-arm only if we suppress a loop
            if armed and (not _radio["on"]):
                tls = self.core.tracklist.get_tl_tracks().get() or []
                started_idx = next(
                    (i for i, t in enumerate(tls) if t.tlid == tl_track.tlid), None
                )
                if (
                    started_idx == 0
                    and len(tls) > 1
                    and (time.time() - self._ended_at) < 45.0
                ):
                    logger.info(
                        "end-of-queue loop suppressed (wrapped to first track); stopping"
                    )
                    self.core.playback.stop()
                    self._at_end = True  # stay armed to catch repeated loop attempts
                    return
        except Exception as e:
            logger.warning("end-of-queue guard error: %r", e)
        # Radio: if on and the queue is running low, top it up with similar songs.
        _maybe_refill_radio(self.core, self.config)

    def playback_state_changed(self, old_state, new_state):
        logger.info("playback state: %s -> %s", old_state, new_state)

    def track_playback_ended(self, tl_track, time_position):
        global _history_suppress_uri
        track = getattr(tl_track, "track", None)
        if not track or not track.uri:
            return
        logger.info(
            "playback ended: %s [%s] at %sms", track.name or "?", track.uri, time_position
        )
        # Record whether this was the last track in the queue (used by the
        # end-of-queue guard in track_playback_started).
        try:
            tls = self.core.tracklist.get_tl_tracks().get() or []
            ended_idx = next(
                (i for i, t in enumerate(tls) if t.tlid == tl_track.tlid), None
            )
            self._at_end = ended_idx is not None and ended_idx >= len(tls) - 1
            self._ended_at = time.time()
        except Exception:
            self._at_end = False
        with _history_lock:
            if _history_suppress_uri == track.uri:
                # Ended only because "back" jumped away from it; it's re-queued
                # ahead of us, so don't record it now (prevents ping-pong).
                _history_suppress_uri = None
                return
            _history.append({"uri": track.uri, "name": track.name or track.uri})
            while len(_history) > 200:
                _history.pop(0)

# Mopidy has no websocket event for "track could not be played", so we capture the
# relevant log lines and expose them to the web UI via the /errors endpoint.
_error_lock = threading.Lock()
_handler_installed = False
_VIDEO_ID_RE = re.compile(r"videoId:\s*([A-Za-z0-9_-]+)")
_HTTP_ERR_RE = re.compile(r"(HTTP Error \d+[^()\n]*)")
_GENERIC_ERR_RE = re.compile(r"ERROR:\s*(.+?)(?:\s*\(videoId.*)?$")


class PlaybackErrorLogHandler(logging.Handler):
    """Watches Mopidy's logs for playback/download failures and records them so the
    web UI can display them. Keyed off message text because there is no event for it."""

    def __init__(self, data):
        super().__init__()
        self.data = data
        self.recent_reasons = {}  # videoId (or "_last") -> human-readable reason

    def _clean_reason(self, msg):
        m = _HTTP_ERR_RE.search(msg)
        if m:
            return m.group(1).strip()
        m = _GENERIC_ERR_RE.search(msg)
        if m:
            return m.group(1).strip()
        return None

    def _push(self, uri, reason):
        with _error_lock:
            self.data["error_seq"] = self.data.get("error_seq", 0) + 1
            self.data["errors"].append(
                {
                    "id": self.data["error_seq"],
                    "uri": uri,
                    "reason": reason or "This track couldn't be played, so it was skipped.",
                }
            )

    def emit(self, record):
        try:
            msg = record.getMessage()
        except Exception:
            return
        try:
            low = msg.lower()
            # Remember a download/extraction reason, keyed by videoId when present.
            if (
                "unable to download" in low
                or "http error" in low
                or "audio_url error" in low
                or record.name.startswith("mopidy_youtube")
            ):
                reason = self._clean_reason(msg)
                if reason:
                    m = _VIDEO_ID_RE.search(msg)
                    self.recent_reasons[m.group(1) if m else "_last"] = reason
                    if len(self.recent_reasons) > 50:
                        self.recent_reasons.pop(next(iter(self.recent_reasons)))
            # The moment the listener actually notices: the track is skipped.
            if "not playable" in low:
                uri = None
                if "not playable:" in low:
                    tail = msg.split("not playable:", 1)[1].strip()
                    uri = tail.split()[0].rstrip(",") if tail else None
                reason = None
                if uri:
                    vid = uri.rsplit(":", 1)[-1]
                    reason = self.recent_reasons.get(vid) or self.recent_reasons.get(
                        "_last"
                    )
                self._push(uri, reason)
        except Exception:
            # A logging handler must never raise.
            pass


# Fallback values, matching ext.conf, so the web app never hard-crashes if a
# config value fails to resolve (which otherwise takes the whole page down).
_DEFAULTS = {
    "votes_to_skip": 3,
    "max_tracks": 0,
    "max_results": 50,
    "max_queue_length": 0,
    "max_song_duration": 0,
    "default_volume": 30,
    "hide_pause": False,
    "hide_skip": False,
    "style": "netjammer.css",
    "source_prio": "local\nspotify\ntidal\nyoutube",
    "source_blacklist": "cd",
    "lastfm_api_key": "",
    "radio_min_queue": 2,
    "radio_batch": 5,
    "radio_seed_count": 3,
    "radio_source": "ytmusic,lastfm",
    "radio_min_duration": 90,
    "radio_max_duration": 480,
}


def _section(config):
    try:
        return config["netjammer"]
    except (KeyError, TypeError):
        return {}


def _conf(config, key):
    """Read a [netjammer] config value, falling back to the built-in default."""
    try:
        value = _section(config)[key]
    except (KeyError, TypeError):
        value = None
    return _DEFAULTS.get(key) if value is None else value


# ===== Radio mode: auto-queue similar songs =====
#
# Pipeline (all network work runs in a background thread, never on Core):
#   1. Seed pool: what people actually asked for -- pinned station seeds (a song,
#      artist or genre), else recent user-requested songs + thumbs-upped picks.
#      Radio's own picks are NEVER used as seeds, so it can't drift off on its own.
#   2. Candidates per seed: YouTube Music "song radio" (studio tracks, real video
#      ids + durations), falling back to / topped up by Last.fm similarity.
#   3. Quality filter: no live sets, concerts, full albums, covers, hour loops...
#      and a duration window.
#   4. Ranking with diversity: songs similar to several seeds score higher, max
#      one track per artist per batch, recently-heard artists cool down, and a
#      weighted-random pick from the top so refills don't repeat themselves.

_BRACKETS_RE = re.compile(r"[\(\[\{].*?[\)\]\}]")  # (Official Video), [HD], {Lyrics}...
_FEAT_RE = re.compile(r"\b(feat\.?|ft\.?|featuring)\b.*", re.IGNORECASE)


def _clean_title(name):
    """Strip common YouTube-title noise so it matches Last.fm/search better."""
    if not name:
        return ""
    s = _BRACKETS_RE.sub("", name)
    s = _FEAT_RE.sub("", s)
    # Drop trailing " - Topic"/"official audio"-style tails and separators.
    s = re.sub(r"\s*[-–|]\s*(official\s*(audio|video|music video)|audio|video|lyrics?)\s*$",
               "", s, flags=re.IGNORECASE)
    return s.strip(" -–|·•").strip()


def _seed_from_track(track):
    """Return (artist, title) for a Mopidy Track. YouTube uploads often carry the
    channel as the artist and "Artist - Title" as the name; untangle that."""
    artist = ""
    try:
        if track.artists:
            artist = next(iter(track.artists)).name or ""
    except Exception:
        artist = ""
    raw = getattr(track, "name", "") or ""
    artist = re.sub(r"\s*-\s*topic$|vevo$", "", artist.strip(), flags=re.IGNORECASE).strip()
    title = _clean_title(raw)
    if " - " in title:
        left, right = title.split(" - ", 1)
        if not artist or _norm_artist(left) == _norm_artist(artist):
            artist, title = left.strip(), _clean_title(right)
    return _clean_title(artist), title


def _norm_key(artist, title):
    return re.sub(r"\s+", " ", ("%s %s" % (artist, title)).strip().lower())


def _norm_artist(name):
    """Comparable artist key: 'Rick Astley', 'RickAstleyVEVO' and
    'Rick Astley - Topic' all become 'rickastley'."""
    s = (name or "").lower()
    s = re.sub(r"\s*-\s*topic$", "", s)
    s = re.sub(r"(vevo|official)$", "", s.strip())
    return re.sub(r"[^a-z0-9]", "", s)


def _norm_title(title):
    return re.sub(r"[^a-z0-9]", "", _clean_title(title or "").lower())


# Titles that are almost never what a party radio wants. Patterns are careful not
# to catch real song names ("Live Forever", "Cover Me Up").
_BAD_TITLE_PATTERNS = [re.compile(p, re.IGNORECASE) for p in (
    r"\blive\s+(at|from|in|on|@)\b",
    r"[\(\[]\s*live\b",
    r"[-–|]\s*live\s*($|[\(\[|–-])",
    r"\blive\s+(performance|version|session|set|recording|stream|concert|show)\b",
    r"\bconcert\b",
    r"\bfull\s+(album|set|show|concert|ep|performance)\b",
    r"\b(world|reunion|farewell|arena|stadium)\s+tour\b",
    r"\bbootleg\b",
    r"\breact(s|ion|ing)?\b",
    r"\bkaraoke\b",
    r"[\(\[][^\)\]]*\bcover\b[^\)\]]*[\)\]]",
    r"\bcover\s+(by|version)\b",
    r"\b(acoustic|piano|guitar|metal|punk|rock|pop|cello|violin)\s+cover\b",
    r"\b8d\b",
    r"\bslowed\b",
    r"\bsped\s*up\b",
    r"\bnightcore\b",
    r"\b\d+\s*(hours?|hrs?)\b",
    r"\bhour\s+(loop|version)\b",
    r"\b(dj\s+mix|megamix|mixtape|continuous\s+mix|medley|compilation|mashup|playlist)\b",
    r"\b(greatest\s+hits|best\s+of)\b",
    r"\b(interview|documentary|behind\s+the\s+scenes|making\s+of|tutorial|lesson|rehearsal|soundcheck)\b",
)]


def _is_bad_title(title, allow_text=""):
    """True if `title` looks like a live set / concert / cover / loop etc. A
    pattern is ignored when it also matches `allow_text` (the seed titles), so
    seeding from a live song can still find live songs."""
    t = title or ""
    for p in _BAD_TITLE_PATTERNS:
        if p.search(t) and not (allow_text and p.search(allow_text)):
            return True
    return False


def _duration_ok(seconds, config):
    if not seconds:
        return True  # unknown -- let it through, the resolver will prefer known ones
    lo = int(_conf(config, "radio_min_duration") or 0)
    hi = int(_conf(config, "radio_max_duration") or 0)
    cap = int(_conf(config, "max_song_duration") or 0)
    if lo and seconds < lo:
        return False
    if hi and seconds > hi:
        return False
    if cap and seconds > cap:
        return False
    return True


def _parse_length(s):
    """'3:45' / '1:02:03' -> seconds (or None)."""
    if isinstance(s, (int, float)):
        return int(s)
    try:
        parts = [int(p) for p in str(s).split(":")]
    except Exception:
        return None
    total = 0
    for p in parts:
        total = total * 60 + p
    return total or None


_YT_ID_RE = re.compile(r"^(?:youtube|yt|ytmusic)[^:]*:.*?([A-Za-z0-9_-]{11})$")


def _video_id(uri):
    m = _YT_ID_RE.match(uri or "")
    return m.group(1) if m else None


def _radio_sources(config):
    raw = str(_conf(config, "radio_source") or "")
    return [s.strip().lower() for s in re.split(r"[,\s]+", raw) if s.strip()]


class Candidate(object):
    __slots__ = ("artist", "title", "video_id", "duration", "source")

    def __init__(self, artist, title, video_id=None, duration=None, source=""):
        self.artist = artist or ""
        self.title = title or ""
        self.video_id = video_id
        self.duration = duration
        self.source = source

    def key(self):
        return _norm_key(_norm_artist(self.artist), _norm_title(self.title))


class Seed(object):
    """One thing radio draws from. `key` is what provenance records (a track URI,
    or 'pin:artist:..' / 'pin:genre:..'), so blocking a seed can prune its picks."""
    __slots__ = ("kind", "key", "weight", "artist", "title", "video_id", "label")

    def __init__(self, kind, key, weight, artist="", title="", video_id=None, label=""):
        self.kind = kind
        self.key = key
        self.weight = weight
        self.artist = artist
        self.title = title
        self.video_id = video_id
        self.label = label or ("%s - %s" % (artist, title)).strip(" -")


# --- Candidate cache: pins and seeds repeat across refills; don't refetch. ---
_cand_cache = {}
_cand_cache_lock = threading.Lock()
_CAND_TTL = 30 * 60


def _cached(key, fn):
    now = time.time()
    with _cand_cache_lock:
        hit = _cand_cache.get(key)
        if hit and now - hit[0] < _CAND_TTL:
            return list(hit[1])
    val = fn() or []
    with _cand_cache_lock:
        _cand_cache[key] = (now, list(val))
        while len(_cand_cache) > 200:
            _cand_cache.pop(next(iter(_cand_cache)))
    return list(val)


# --- YouTube Music (ytmusicapi, unauthenticated) ---
_ytm = {"client": None, "tried": False}
_ytm_lock = threading.Lock()


def _ytm_available():
    try:
        import ytmusicapi  # noqa: F401
        return True
    except Exception:
        return False


def _ytm_client():
    with _ytm_lock:
        if _ytm["client"] is None and not _ytm["tried"]:
            _ytm["tried"] = True
            try:
                from ytmusicapi import YTMusic
                _ytm["client"] = YTMusic()
                logger.info("radio: YouTube Music source ready")
            except Exception as e:
                logger.warning("radio: YouTube Music unavailable (%r); using Last.fm only", e)
        return _ytm["client"]


def _ytm_track_to_cand(t, source):
    vid = t.get("videoId")
    title = t.get("title")
    if not vid or not title:
        return None
    artists = t.get("artists") or []
    artist = (artists[0].get("name") if artists and isinstance(artists[0], dict) else "") or ""
    dur = t.get("duration_seconds") or _parse_length(t.get("length") or t.get("duration"))
    return Candidate(artist, title, vid, dur, source)


def _ytm_song_radio(video_id, limit=50):
    def fetch():
        yt = _ytm_client()
        if yt is None:
            return []
        try:
            res = yt.get_watch_playlist(videoId=video_id, radio=True, limit=limit)
        except Exception as e:
            logger.warning("radio: ytmusic song radio failed for %s: %r", video_id, e)
            return []
        out = []
        for t in (res or {}).get("tracks") or []:
            c = _ytm_track_to_cand(t, "ytmusic")
            if c and c.video_id != video_id:
                out.append(c)
        return out
    return _cached(("ytm-radio", video_id), fetch)


def _ytm_find_song(artist, title):
    """Find a studio song's video id on YouTube Music (for seeding a non-YouTube
    track, e.g. a local file, into song radio)."""
    yt = _ytm_client()
    if yt is None:
        return None
    try:
        res = yt.search(("%s %s" % (artist, title)).strip(), filter="songs", limit=3)
    except Exception:
        return None
    for r in res or []:
        if r.get("videoId"):
            return r["videoId"]
    return None


def _ytm_artist_seed(name):
    def fetch():
        yt = _ytm_client()
        if yt is None:
            return []
        out = []
        try:
            hits = yt.search(name, filter="artists", limit=3) or []
            browse = next((h.get("browseId") for h in hits if h.get("browseId")), None)
            songs = []
            if browse:
                art = yt.get_artist(browse) or {}
                songs = ((art.get("songs") or {}).get("results")) or []
            for t in songs:
                c = _ytm_track_to_cand(t, "ytmusic-artist")
                if c:
                    if not c.artist:
                        c.artist = name
                    out.append(c)
            # Artist radio: their top song's radio mixes in similar artists.
            if out:
                out.extend(_ytm_song_radio(out[0].video_id))
        except Exception as e:
            logger.warning("radio: ytmusic artist seed failed for %r: %r", name, e)
        return out
    return _cached(("ytm-artist", name.lower()), fetch)


def _ytm_genre_seed(text):
    def fetch():
        yt = _ytm_client()
        if yt is None:
            return []
        out = []
        try:
            hits = yt.search(text, filter="playlists", limit=5) or []
            for h in hits[:2]:
                pid = h.get("browseId") or h.get("playlistId")
                if not pid:
                    continue
                if pid.startswith("VL"):
                    pid = pid[2:]
                pl = yt.get_playlist(pid, limit=100) or {}
                for t in pl.get("tracks") or []:
                    c = _ytm_track_to_cand(t, "ytmusic-genre")
                    if c:
                        out.append(c)
                if len(out) >= 40:
                    break
        except Exception as e:
            logger.warning("radio: ytmusic genre seed failed for %r: %r", text, e)
        # Playlist order isn't a similarity ranking; shuffle so rank is fair.
        random.shuffle(out)
        return out
    return _cached(("ytm-genre", text.lower()), fetch)


# --- Last.fm (fallback / top-up; needs lastfm_api_key) ---

def _lastfm_call(api_key, params):
    params = dict(params)
    params.update({"api_key": api_key, "format": "json", "autocorrect": 1})
    url = "https://ws.audioscrobbler.com/2.0/?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "NETJammer/1.0"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _lastfm_tracks(data, root, key="track"):
    out = []
    for t in ((data or {}).get(root, {}) or {}).get(key, []) or []:
        nm = t.get("name")
        ar = t.get("artist")
        ar = ar.get("name") if isinstance(ar, dict) else ar
        if nm and ar:
            dur = t.get("duration")
            try:
                dur = int(dur) or None
                if dur and dur > 10000:  # some endpoints report ms
                    dur //= 1000
            except Exception:
                dur = None
            out.append(Candidate(ar, nm, None, dur, "lastfm"))
    return out


def _lastfm_artist_top(api_key, artist, limit):
    try:
        return _lastfm_tracks(_lastfm_call(api_key, {
            "method": "artist.gettoptracks", "artist": artist, "limit": limit}), "toptracks")
    except Exception as e:
        logger.warning("radio: last.fm artist.getTopTracks failed: %r", e)
        return []


def _lastfm_similar(artist, title, api_key, limit):
    """track.getSimilar; if unknown, the top tracks of a few similar artists
    (never a bare artist-name search, which is what dug up random live sets)."""
    def fetch():
        out = []
        if title:
            try:
                out = _lastfm_tracks(_lastfm_call(api_key, {
                    "method": "track.getsimilar", "artist": artist, "track": title,
                    "limit": limit}), "similartracks")
            except Exception as e:
                logger.warning("radio: last.fm getSimilar failed: %r", e)
        if not out and artist:
            out = _lastfm_similar_artists_top(api_key, artist)
        return out
    return _cached(("lfm-sim", artist.lower(), title.lower(), limit), fetch)


def _lastfm_similar_artists_top(api_key, artist, n_artists=6, per_artist=3):
    try:
        data = _lastfm_call(api_key, {"method": "artist.getsimilar", "artist": artist,
                                      "limit": n_artists})
        names = [a.get("name") for a in (data.get("similarartists", {}) or {}).get("artist", []) or []
                 if a.get("name")]
    except Exception as e:
        logger.warning("radio: last.fm artist.getSimilar failed: %r", e)
        names = []
    out = []
    # Interleave so ranks alternate between artists (natural diversity).
    per = [_lastfm_artist_top(api_key, nm, per_artist) for nm in names]
    for i in range(per_artist):
        for lst in per:
            if i < len(lst):
                out.append(lst[i])
    return out


def _lastfm_artist_seed(api_key, artist):
    def fetch():
        own = _lastfm_artist_top(api_key, artist, 10)
        others = _lastfm_similar_artists_top(api_key, artist)
        out = []
        for i in range(max(len(own), len(others))):  # interleave own + similar
            if i < len(own):
                out.append(own[i])
            if i < len(others):
                out.append(others[i])
        return out
    return _cached(("lfm-artist", artist.lower()), fetch)


def _lastfm_genre_seed(api_key, tag):
    def fetch():
        try:
            out = _lastfm_tracks(_lastfm_call(api_key, {
                "method": "tag.gettoptracks", "tag": tag, "limit": 60}), "tracks")
        except Exception as e:
            logger.warning("radio: last.fm tag.getTopTracks failed: %r", e)
            out = []
        random.shuffle(out)
        return out
    return _cached(("lfm-tag", tag.lower()), fetch)


def _candidates_for_seed(seed, config, limit):
    """Gather candidates for one seed from the configured sources, in order of
    preference, topping up from the next source when the first comes up short."""
    sources = _radio_sources(config)
    api_key = (_conf(config, "lastfm_api_key") or "").strip()
    out = []
    for src in sources:
        if len(out) >= limit:
            break
        if src == "ytmusic" and _ytm_available():
            if seed.kind == "track":
                vid = seed.video_id or (_ytm_find_song(seed.artist, seed.title)
                                        if (seed.artist or seed.title) else None)
                if vid:
                    out.extend(_ytm_song_radio(vid))
            elif seed.kind == "artist":
                out.extend(_ytm_artist_seed(seed.artist))
            elif seed.kind == "genre":
                out.extend(_ytm_genre_seed(seed.title))
        elif src == "lastfm" and api_key:
            if seed.kind == "track" and (seed.artist or seed.title):
                out.extend(_lastfm_similar(seed.artist, seed.title, api_key, limit))
            elif seed.kind == "artist":
                out.extend(_lastfm_artist_seed(api_key, seed.artist))
            elif seed.kind == "genre":
                out.extend(_lastfm_genre_seed(api_key, seed.title))
    return out


def _radio_available(config):
    sources = _radio_sources(config)
    if "ytmusic" in sources and _ytm_available():
        return True
    return "lastfm" in sources and bool((_conf(config, "lastfm_api_key") or "").strip())


# --- Seed pool ---

def _weighted_shuffle(items, weight):
    """Order items randomly, heavier ones tending to come first
    (Efraimidis-Spirakis weighted sampling without replacement)."""
    keyed = []
    for it in items:
        w = max(float(weight(it)), 1e-6)
        keyed.append((random.random() ** (1.0 / w), it))
    keyed.sort(key=lambda x: -x[0])
    return [it for _, it in keyed]


def _track_seed(track, weight):
    artist, title = _seed_from_track(track)
    uri = getattr(track, "uri", None)
    if not uri or not (artist or title):
        return None
    return Seed("track", uri, weight, artist, title, _video_id(uri),
                getattr(track, "name", "") or "")


def _pin_seed(pin, weight=3.0):
    kind = pin.get("kind")
    if kind == "track":
        uri = pin.get("value")
        return Seed("track", uri, weight, pin.get("artist") or "", pin.get("title") or "",
                    _video_id(uri), pin.get("label"))
    if kind == "artist":
        return Seed("artist", "pin:artist:" + pin["value"].lower(), weight,
                    artist=pin["value"], label=pin.get("label") or pin["value"])
    if kind == "genre":
        return Seed("genre", "pin:genre:" + pin["value"].lower(), weight,
                    title=pin["value"], label=pin.get("label") or pin["value"])
    return None


def _build_seed_pool(core):
    """All seeds radio may draw from right now (newest/strongest first).

    - Pinned station seeds win outright when present.
    - Otherwise: the last few songs people REQUESTED (played, playing, or queued),
      plus radio picks someone thumbed up. Radio's own picks are excluded so it
      stays anchored to the room's taste instead of wandering.
    - Last resort: whatever is playing now."""
    with _radio_meta_lock:
        pins = [dict(p) for p in _radio_pins]
        bl = set(_radio_blocklist)
        picks = set(_radio_provenance)
        liked = dict(_radio_liked)
    if pins:
        seeds = [s for s in (_pin_seed(p) for p in pins) if s and s.key not in bl]
        if seeds:
            return seeds

    try:
        tls = core.tracklist.get_tl_tracks().get() or []
        idx = core.tracklist.index().get()
    except Exception:
        tls, idx = [], None
    if idx is None:
        idx = len(tls) - 1
    played = [t.track for t in tls[: idx + 1] if getattr(t, "track", None)]
    upcoming = [t.track for t in tls[idx + 1:] if getattr(t, "track", None)]
    played.reverse()  # newest first

    seeds, seen = [], set()
    w = 2.0
    for tr in played + upcoming:
        uri = getattr(tr, "uri", None)
        if not uri or uri in seen or uri in bl:
            continue
        if uri in picks and uri not in liked:
            continue  # radio's own pick -- never a seed
        s = _track_seed(tr, 2.0 if uri in liked else w)
        if s:
            seeds.append(s)
            seen.add(uri)
            w = max(0.5, w * 0.75)  # recency decay
        if len(seeds) >= 6:
            break
    # Thumbs-upped picks that have scrolled out of the tracklist.
    for uri, meta in liked.items():
        if uri in seen or uri in bl:
            continue
        seeds.append(Seed("track", uri, 2.0, meta.get("artist") or "",
                          _clean_title(meta.get("title") or meta.get("name") or ""),
                          _video_id(uri), meta.get("name")))
        if len(seeds) >= 8:
            break
    if seeds:
        return seeds

    try:
        cur = core.playback.get_current_track().get()
    except Exception:
        cur = None
    s = _track_seed(cur, 1.0) if cur is not None else None
    return [s] if s and s.key not in bl else []


def _current_seed_uris(core, config):
    """Track URIs currently able to influence radio (for the History highlight)."""
    return [s.key for s in _build_seed_pool(core) if s.kind == "track"]


# --- YouTube resolver (for candidates without a video id, i.e. Last.fm) ---

# yt-dlp options for resolving a radio candidate to a YouTube video id. Mirrors
# the working playlist-import opts (_extract_youtube_playlist) plus search tuning.
_RADIO_YDL_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "extract_flat": "in_playlist",  # flat entries carry `id` with no per-video fetch
    "skip_download": True,
    "noplaylist": True,
    "socket_timeout": 10,
}


def _yt_search_uri(cand, ydl, config, allow_text=""):
    """Resolve a candidate to a youtube:video:ID URI via yt-dlp (off the Core
    actor). Looks at the top 5 results instead of blindly taking the first, drops
    live/concert/loop uploads and anything outside the duration window, and
    prefers official sources (' - Topic' channels, VEVO, the artist's channel).
    Returns None if nothing suitable is found."""
    query = ("%s %s" % (cand.artist, cand.title)).strip()
    try:
        info = ydl.extract_info("ytsearch5:" + query, download=False)
    except Exception as e:
        logger.warning("radio: yt-dlp search failed for %r: %r", query, e)
        return None
    want_artist = _norm_artist(cand.artist)
    want_title = _norm_title(cand.title)
    best, best_score = None, None
    for i, e in enumerate((info or {}).get("entries") or []):
        vid = e.get("id")
        title = e.get("title") or ""
        if not vid or _is_bad_title(title, allow_text):
            continue
        dur = e.get("duration")
        if not _duration_ok(dur, config):
            continue
        chan = e.get("channel") or e.get("uploader") or ""
        score = -0.3 * i  # mild preference for YouTube's own ordering
        if re.search(r"-\s*topic$", chan, re.IGNORECASE):
            score += 3
        if "vevo" in chan.lower():
            score += 2
        if want_artist and want_artist in _norm_artist(chan):
            score += 2
        nt = _norm_title(title)
        if want_title and want_title in nt:
            score += 2
        elif want_title:
            score -= 2  # probably a different song
        if want_artist and want_artist in re.sub(r"[^a-z0-9]", "", title.lower()):
            score += 1
        if not dur:
            score -= 1
        if best_score is None or score > best_score:
            best, best_score = vid, score
    return ("youtube:video:" + best) if best else None


# --- Ranking ---

def _rank_candidates(seeds, config, limit):
    """Merge candidates from every seed. Songs similar to several seeds (the
    common thread) and to heavier seeds score higher. Returns a list of
    (Candidate, score, set(seed_keys)) best-first, quality-filtered."""
    allow_text = " ".join("%s %s" % (s.title, s.label) for s in seeds)
    seed_keys = set(_norm_key(_norm_artist(s.artist), _norm_title(s.title))
                    for s in seeds if s.kind == "track")
    seed_vids = set(s.video_id for s in seeds if s.video_id)
    merged = {}
    for s in seeds:
        cands = _candidates_for_seed(s, config, limit)
        logger.info("radio: seed [%s] %s -> %d candidates", s.kind, s.label or "?", len(cands))
        for rank, c in enumerate(cands):
            k = c.key()
            if not k.strip() or k in seed_keys or (c.video_id and c.video_id in seed_vids):
                continue
            if _is_bad_title(c.title, allow_text) or not _duration_ok(c.duration, config):
                continue
            pts = s.weight / (1.0 + 0.15 * rank)
            ent = merged.get(k)
            if ent is None:
                merged[k] = [c, pts, {s.key}]
            else:
                ent[1] += pts
                ent[2].add(s.key)
                if not ent[0].video_id and c.video_id:  # prefer a resolved copy
                    ent[0] = c
    out = []
    for c, pts, keys in merged.values():
        out.append((c, pts * (1.0 + 0.5 * (len(keys) - 1)), keys))
    out.sort(key=lambda x: -x[1])
    return out


def _recent_context(core):
    """(artist keys heard recently or queued, video ids in the tracklist/history,
    title keys in the tracklist/history) -- used to avoid repeats and to cool
    down artists that were just played."""
    artists, vids, titles, uris = set(), set(), set(), set()
    try:
        tls = core.tracklist.get_tl_tracks().get() or []
        idx = core.tracklist.index().get()
    except Exception:
        tls, idx = [], None
    if idx is None:
        idx = len(tls) - 1
    with _radio_meta_lock:
        pick_artist = dict(_radio_pick_artist)
    for i, tl in enumerate(tls):
        tr = getattr(tl, "track", None)
        if not tr:
            continue
        uri = getattr(tr, "uri", "") or ""
        uris.add(uri)
        v = _video_id(uri)
        if v:
            vids.add(v)
        a, t = _seed_from_track(tr)
        titles.add(_norm_title(t))
        if i >= idx - 10:  # last ~10 played + everything still queued
            artists.add(_norm_artist(pick_artist.get(uri) or a))
    with _history_lock:
        hist = list(_history)[-60:]
    for h in hist:
        v = _video_id(h.get("uri"))
        if v:
            vids.add(v)
        titles.add(_norm_title(h.get("name", "")))
    artists.discard("")
    titles.discard("")
    return artists, vids, titles, uris


def _refill_radio(core, config, seed_track=None):
    """Pick seeds, gather + rank candidates, resolve them to YouTube and append
    the best `radio_batch` with artist diversity. Runs in a background thread
    (never call from the actor's event loop directly)."""
    global _radio_busy
    ydl = None
    try:
        batch = int(_conf(config, "radio_batch"))
        n_seeds = max(1, int(_conf(config, "radio_seed_count")))
        limit = max(batch * 6, 30)

        pool = [_track_seed(seed_track, 3.0)] if seed_track is not None else _build_seed_pool(core)
        pool = [s for s in pool if s]
        if not pool:
            logger.info("radio: no seeds; nothing to refill")
            return
        seeds = _weighted_shuffle(pool, lambda s: s.weight)[:n_seeds]
        logger.info("radio: seeding from %d of %d seed(s): %s", len(seeds), len(pool),
                    ", ".join("[%s] %s" % (s.kind, s.label) for s in seeds))

        ranked = _rank_candidates(seeds, config, limit)
        if not ranked:
            logger.info("radio: no suitable candidates found")
            return

        recent_artists, recent_vids, recent_titles, existing_uris = _recent_context(core)
        with _radio_meta_lock:
            banned = set(_radio_artist_ban)
        pinned_artists = set(_norm_artist(s.artist) for s in seeds if s.kind == "artist")
        seed_artists = set(_norm_artist(s.artist) for s in seeds if s.artist)
        seed_artist_cap = max(1, batch // 3)
        pinned_artist_cap = max(1, batch // 2)
        allow_text = " ".join("%s %s" % (s.title, s.label) for s in seeds)

        # Weighted-random over the top of the ranking (fresh picks every refill),
        # then the rest in order as a reserve if resolution keeps failing.
        top_n = batch * 4
        order = _weighted_shuffle(ranked[:top_n], lambda x: x[1]) + ranked[top_n:]

        try:
            import yt_dlp
            ydl = yt_dlp.YoutubeDL(_RADIO_YDL_OPTS)
        except Exception as e:
            logger.warning("radio: yt-dlp unavailable; only YouTube Music picks can be used: %r", e)

        added, first_added = 0, None
        batch_artists = {}
        seed_artist_used = 0

        def try_add(cand, keys, strict):
            nonlocal added, first_added, seed_artist_used
            a = _norm_artist(cand.artist)
            if a in banned:
                return False
            if _norm_title(cand.title) in recent_titles:
                return False
            if cand.video_id and cand.video_id in recent_vids:
                return False
            is_pinned = a in pinned_artists
            cap = pinned_artist_cap if is_pinned else 1
            if batch_artists.get(a, 0) >= cap:
                return False
            if strict and not is_pinned:
                if a in recent_artists:
                    return False
                if a in seed_artists and seed_artist_used >= seed_artist_cap:
                    return False
            if cand.video_id:
                uri = "youtube:video:" + cand.video_id
            elif ydl is not None:
                uri = _yt_search_uri(cand, ydl, config, allow_text)
            else:
                uri = None
            vid = _video_id(uri) if uri else None
            if not uri or uri in existing_uris or (vid and vid in recent_vids):
                return False
            try:
                new_tls = core.tracklist.add(uris=[uri]).get()
            except Exception as e:
                logger.warning("radio: add failed for %s: %r", uri, e)
                return False
            if not new_tls:
                return False
            # Key provenance off the URI the tracklist actually stored
            # (mopidy-youtube may canonicalise our youtube:video:ID form).
            canon = uri
            if getattr(new_tls[0], "track", None) and getattr(new_tls[0].track, "uri", None):
                canon = new_tls[0].track.uri
            existing_uris.update((uri, canon))
            if vid:
                recent_vids.add(vid)
            recent_titles.add(_norm_title(cand.title))
            batch_artists[a] = batch_artists.get(a, 0) + 1
            if a in seed_artists:
                seed_artist_used += 1
            added += 1
            if first_added is None:
                first_added = new_tls[0]
            with _radio_meta_lock:
                _radio_provenance[canon] = set(keys)
                _radio_pick_artist[canon] = cand.artist
                while len(_radio_provenance) > 500:
                    _radio_provenance.pop(next(iter(_radio_provenance)))
                while len(_radio_pick_artist) > 500:
                    _radio_pick_artist.pop(next(iter(_radio_pick_artist)))
            logger.info("radio: added %s - %s [%s via %s]", cand.artist, cand.title, canon, cand.source)
            # Let Core interleave other requests between adds, and space out searches.
            time.sleep(0.25)
            return True

        tried = set()
        for cand, _score, keys in order:
            if added >= batch:
                break
            if try_add(cand, keys, strict=True):
                tried.add(cand.key())
        if added < max(1, batch // 2):
            # Not enough diverse picks -- relax the cooldown rather than go quiet.
            logger.info("radio: only %d diverse pick(s); relaxing artist cooldown", added)
            for cand, _score, keys in order:
                if added >= batch:
                    break
                if cand.key() not in tried:
                    try_add(cand, keys, strict=False)

        # If playback had already stopped (e.g. the last song ended before this
        # refill finished), start the first track we just added.
        if added and first_added is not None:
            try:
                if core.playback.get_state().get() == "stopped":
                    core.playback.play(tlid=first_added.tlid)
                    logger.info("radio: playback was stopped, starting %s", first_added.track.uri)
            except Exception as e:
                logger.warning("radio: could not resume playback: %r", e)

        logger.info("radio: refill complete, added %d track(s)", added)
        if added:
            EventSocketHandler.broadcast({"type": "changed"})
    except Exception as e:
        logger.warning("radio: refill error: %r", e)
    finally:
        try:
            if ydl is not None:
                ydl.close()
        except Exception:
            pass
        with _radio_lock:
            _radio_busy = False
            again = _radio_refill_again[0]
            _radio_refill_again[0] = False
        if again:
            _maybe_refill_radio(core, config, force=True)


_radio_refill_again = [False]  # a forced refill was requested while one was running


def _maybe_refill_radio(core, config, force=False):
    """If radio is on (and, unless forced, the queue is running low), kick a
    background refill. Guarded so only one refill runs at a time; a forced
    request during a refill is remembered and run right after it."""
    global _radio_busy
    with _radio_lock:
        if not _radio["on"]:
            return
        if _radio_busy:
            if force:
                _radio_refill_again[0] = True
            return
    if not _radio_available(config):
        return
    try:
        if not force:
            idx = core.tracklist.index().get()
            length = core.tracklist.get_length().get() or 0
            cur = -1 if idx is None else idx
            upcoming = length - (cur + 1)
            if upcoming >= int(_conf(config, "radio_min_queue")):
                return
    except Exception:
        pass
    with _radio_lock:
        if _radio_busy:
            if force:
                _radio_refill_again[0] = True
            return
        _radio_busy = True
    threading.Thread(target=_refill_radio, args=(core, config), daemon=True).start()


def _prune_upcoming_picks(core, should_remove):
    """Remove not-yet-played radio picks for which should_remove(uri, seed_keys)
    is true. Never touches the current or already-played tracks, or songs people
    requested. Returns how many were removed."""
    try:
        tls = core.tracklist.get_tl_tracks().get() or []
        idx = core.tracklist.index().get()
    except Exception:
        return 0
    cur = -1 if idx is None else idx
    with _radio_meta_lock:
        prov = {u: set(s) for u, s in _radio_provenance.items()}
    tlids, uris = [], []
    for i, tl in enumerate(tls):
        if i <= cur:
            continue
        uri = getattr(getattr(tl, "track", None), "uri", None)
        if uri and uri in prov and should_remove(uri, prov[uri]):
            tlids.append(tl.tlid)
            uris.append(uri)
    if not tlids:
        return 0
    try:
        core.tracklist.remove({"tlid": tlids}).get()
    except Exception as e:
        logger.warning("radio: prune remove failed: %r", e)
        return 0
    with _radio_meta_lock:
        for uri in uris:
            _radio_provenance.pop(uri, None)
    return len(tlids)


def _prune_radio_offspring(core, seed_uri):
    """Remove not-yet-played tracks radio added because of `seed_uri`."""
    return _prune_upcoming_picks(core, lambda uri, keys: seed_uri in keys)


def _radio_pins_snapshot():
    with _radio_meta_lock:
        return [dict(p) for p in _radio_pins]


class VoteRequestHandler(tornado.web.RequestHandler):

    def initialize(self, core, data, config):
        self.core = core
        self.data = data
        self.requiredVotes = _conf(config, "votes_to_skip")

    def _getip(self):
        return self.request.headers.get("X-Forwarded-For", self.request.remote_ip)

    def get(self):
        currentTrack = self.core.playback.get_current_track().get()
        if currentTrack == None:
            return
        currentTrackURI = currentTrack.uri

        # If the current track is different to the one stored, clear votes
        if currentTrackURI != self.data["track"]:
            self.data["track"] = currentTrackURI
            self.data["votes"] = []

        if self._getip() in self.data["votes"]:  # User has already voted
            self.write("You have already voted to skip this song =)")
        else:  # Valid vote
            self.data["votes"].append(self._getip())
            if len(self.data["votes"]) == self.requiredVotes:
                self.core.playback.next()
                self.write("Skipping...")
            else:
                self.write(
                    "You have voted to skip this song. ("
                    + str(self.requiredVotes - len(self.data["votes"]))
                    + " more votes needed)"
                )


class AddRequestHandler(tornado.web.RequestHandler):

    def initialize(self, core, data, config):
        self.core = core
        self.data = data
        self.maxQueueLength = _conf(config, "max_queue_length")

    def _getip(self):
        return self.request.headers.get("X-Forwarded-For", self.request.remote_ip)

    def post(self):
        # when the last n tracks were added by the same user, abort.
        if self.data["queue"] and all([e == self._getip() for e in self.data["queue"]]):
            self.write("You have requested too many songs")
            self.set_status(409)
            return

        track_uri = self.request.body.decode()
        if not track_uri:
            self.set_status(400)
            return

        # Idempotency guard: ignore the exact same track from the same client within
        # a few seconds. Catches double taps and proxy (nginx) POST retries, which
        # were queuing songs twice. Distinct users / later re-adds are unaffected.
        now = time.time()
        ip = self._getip()
        recent = self.data.setdefault("recent_adds", {})
        for k in [k for k, ts in recent.items() if now - ts > 10.0]:
            del recent[k]  # prune stale entries
        key = ip + "|" + track_uri
        if key in recent and (now - recent[key]) < 3.0:
            logger.info("add: ignoring duplicate %s from %s (within 3s)", track_uri, ip)
            recent[key] = now
            return  # already queued a moment ago; treat as success
        recent[key] = now

        pos = 0
        if self.data["last"]:
            queue = self.core.tracklist.index(self.data["last"]).get() or 0
            current = self.core.tracklist.index().get() or 0
            pos = max(queue, current)  # after lastly enqueued and after current track
            if (self.maxQueueLength > 0) and (pos >= self.maxQueueLength - 1):
                self.write("Queue at max length, try again later.")
                self.set_status(409)
                return

        try:
            self.data["last"] = self.core.tracklist.add(
                uris=[track_uri], at_position=pos + 1
            ).get()[0]
            self.data["queue"].append(self._getip())
            self.data["queue"].pop(0)
        except Exception as e:
            logger.error("add failed for %s from %s: %r", track_uri, self._getip(), e)
            self.write("Unable to add track. Internal Server Error: " + repr(e))
            self.set_status(500)
            return

        state = self.core.playback.get_state().get()
        logger.info(
            "add: %s from %s at pos %s (state=%s)", track_uri, self._getip(), pos + 1, state
        )
        if state == "stopped":
            # Play the track we just added. With consume off, the tracklist head is
            # an already-played song, so we must NOT start from the head (that would
            # replay the whole list). Playing the newly-added tlid also avoids a bare
            # play() no-op on a stale "current" pointer.
            new_tl = self.data["last"]
            if new_tl is not None:
                logger.info("add: playback was stopped, starting added track %s", track_uri)
                self.core.playback.play(tlid=new_tl.tlid)


class PlaylistHandler(tornado.web.RequestHandler):
    """Handle playlist and album URLs from YouTube, Spotify, etc."""

    def initialize(self, core, data, config):
        self.core = core
        self.data = data
        self.config = config
        self.maxQueueLength = _conf(config, "max_queue_length")

    def _getip(self):
        return self.request.headers.get("X-Forwarded-For", self.request.remote_ip)

    def post(self):
        """Accept a playlist/album URL and expand it to tracks"""
        try:
            request_data = json.loads(self.request.body.decode())
            url = request_data.get("url", "").strip()
            source = request_data.get("source", "auto").lower()
        except Exception as e:
            self.write(json.dumps({"error": "Invalid request format: " + repr(e)}))
            self.set_status(400)
            return

        if not url:
            self.write(json.dumps({"error": "URL is required"}))
            self.set_status(400)
            return

        try:
            # Try to extract tracks from the URL
            if "youtube" in url or source == "youtube":
                tracks = self._extract_youtube_playlist(url)
            elif "spotify" in url or source == "spotify":
                tracks = self._extract_spotify_playlist(url)
            else:
                # Try to use Mopidy library search as fallback
                tracks = self._extract_with_mopidy(url)

            if not tracks:
                self.write(json.dumps({"error": "No tracks found in playlist/album"}))
                self.set_status(404)
                return

            # Check anti-spam condition before adding massive playlists
            # We skip filling data["queue"] with dozens of entries to avoid locking the user out
            if self.data["queue"] and all(
                [e == self._getip() for e in self.data["queue"]]
            ):
                self.write(json.dumps({"error": "You have requested too many songs"}))
                self.set_status(409)
                return

            added_count = 0
            first_added = None
            for track_uri in tracks:
                try:
                    print(f"[NETJammer] Adding track: {track_uri}")

                    pos = 0
                    if self.data["last"]:
                        queue = self.core.tracklist.index(self.data["last"]).get() or 0
                        current = self.core.tracklist.index().get() or 0
                        pos = max(queue, current)
                        if (self.maxQueueLength > 0) and (
                            pos >= self.maxQueueLength - 1
                        ):
                            print(
                                "[NETJammer] Max queue length reached, stopping playlist import."
                            )
                            break

                    last_track = self.core.tracklist.add(
                        uris=[track_uri], at_position=pos + 1
                    ).get()[0]

                    self.data["last"] = last_track
                    if first_added is None:
                        first_added = last_track

                    # Only log one entry in anti-spam queue tracking per playlist chunk
                    if added_count == 0:
                        self.data["queue"].append(self._getip())
                        self.data["queue"].pop(0)

                    added_count += 1
                except Exception as e:
                    print(f"[NETJammer] Error adding track {track_uri}: {repr(e)}")

            # Trigger playback ONCE after all tracks have been processed. Play the
            # first track we just added (consume is off, so the tracklist head is a
            # previously-played song and must not be restarted).
            if (
                added_count > 0
                and first_added is not None
                and self.core.playback.get_state().get() == "stopped"
            ):
                self.core.playback.play(tlid=first_added.tlid)

            self.write(
                json.dumps(
                    {
                        "success": True,
                        "added": added_count,
                        "total": len(tracks),
                        "message": f"Added {added_count} tracks from playlist/album",
                    }
                )
            )

        except Exception as e:
            self.write(json.dumps({"error": "Failed to process playlist: " + repr(e)}))
            self.set_status(500)

    def _extract_youtube_playlist(self, url):
        """Extract track URIs from a YouTube playlist using yt-dlp"""
        try:
            import yt_dlp
        except ImportError:
            raise Exception(
                "yt-dlp is required for YouTube playlist support. Install with: pip install yt-dlp"
            )

        try:
            print(f"[NETJammer] Extracting YouTube playlist from: {url}")
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "extract_flat": "in_playlist",
                "skip_download": True,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

            tracks = []
            if "entries" in info:
                print(f"[NETJammer] Found {len(info['entries'])} entries in playlist")
                for entry in info["entries"]:
                    if entry:
                        video_id = entry.get("id")
                        if video_id:
                            # CRITICAL FIX: Generate Mopidy-YouTube URI schemes instead of generic web URLs
                            # Using full "youtube:video:ID" format ensures proper colon-based parsing
                            video_uri = f"youtube:video:{video_id}"
                            tracks.append(video_uri)
                            print(f"[NETJammer] Added video URI: {video_uri}")
            else:
                # Single video
                video_id = info.get("id")
                if video_id:
                    video_uri = f"youtube:video:{video_id}"
                    tracks.append(video_uri)
                    print(f"[NETJammer] Added single video URI: {video_uri}")

            print(f"[NETJammer] Total tracks extracted: {len(tracks)}")
            return tracks
        except Exception as e:
            print(f"[NETJammer] Error extracting YouTube playlist: {repr(e)}")
            raise Exception(f"Failed to extract YouTube playlist: {repr(e)}")

    def _extract_spotify_playlist(self, url):
        """Extract track URIs from a Spotify playlist"""
        try:
            # Extract Spotify IDs from URLs
            # Spotify URL formats: https://open.spotify.com/playlist/ID or https://open.spotify.com/album/ID
            match = re.search(r"/(playlist|album)/([a-zA-Z0-9]+)", url)
            if match:
                playlist_type, playlist_id = match.groups()
                # Return Spotify URIs that Mopidy can use
                if playlist_type == "playlist":
                    return [f"spotify:playlist:{playlist_id}"]
                elif playlist_type == "album":
                    return [f"spotify:album:{playlist_id}"]
        except Exception as e:
            raise Exception(f"Failed to extract Spotify playlist: {repr(e)}")
        return []

    def _extract_with_mopidy(self, url_or_query):
        """Use Mopidy library search to find tracks"""
        try:
            # Try searching for the query in available sources
            search_result = self.core.library.search({"any": [url_or_query]}).get()
            tracks = []
            for result in search_result:
                if result and hasattr(result, "tracks"):
                    for track in result.tracks:
                        if track and hasattr(track, "uri"):
                            tracks.append(track.uri)
            return tracks
        except Exception as e:
            raise Exception(f"Failed to search with Mopidy: {repr(e)}")


class IndexHandler(tornado.web.RequestHandler):

    def initialize(self, config):
        # Start from safe defaults so the template always has the variables it
        # references (style, hide_pause, hide_skip); then overlay real config.
        self.__dict = {
            "style": _DEFAULTS["style"],
            "hide_pause": _DEFAULTS["hide_pause"],
            "hide_skip": _DEFAULTS["hide_skip"],
            # Cache-buster: appended to the JS/CSS URLs so a version bump forces
            # browsers to fetch fresh assets instead of serving stale cached ones
            # (stale clients have caused queue-looping and other ghost bugs).
            "version": __version__,
        }
        # Make the configuration from mopidy.conf [netjammer] section available as variables in index.html
        try:
            items = list(_section(config).items())
        except (AttributeError, TypeError):
            items = []
        for conf_key, value in items:
            if conf_key != "enabled":
                self.__dict[conf_key] = value

    def get(self):
        return self.render("static/index.html", **self.__dict)


class VersionHandler(tornado.web.RequestHandler):
    """Reports the running backend version so clients can detect when their
    cached JS is stale (after a deploy) and reload themselves."""

    def get(self):
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps({"version": __version__}))


class ConfigHandler(tornado.web.RequestHandler):

    def initialize(self, config):
        self.config = config

    def get(self):
        conf_key = self.get_argument("key", default="")
        if not conf_key:
            self.set_status(400)
            self.write("Query parameter 'key' not present")
            return
        try:
            value = _section(self.config)[conf_key]
        except (KeyError, TypeError):
            value = None
        if value is None and conf_key in _DEFAULTS:
            value = _DEFAULTS[conf_key]
        if value is None:
            self.set_status(404)
            self.write("Configuration '" + conf_key + "' not found")
            return
        self.write(repr(value))


class ErrorsHandler(tornado.web.RequestHandler):
    """Return playback/download errors newer than the given ?since=<id>.

    The web UI polls this and shows any new errors as a toast. Pass no 'since'
    (or empty) to just learn the latest id without receiving old errors."""

    def initialize(self, data):
        self.data = data

    def get(self):
        since = self.get_argument("since", default="")
        errors = list(self.data["errors"])
        latest = errors[-1]["id"] if errors else 0

        if since == "":
            out = []
        else:
            try:
                since_id = int(since)
            except ValueError:
                since_id = 0
            out = [e for e in errors if e["id"] > since_id]

        self.set_header("Content-Type", "application/json")
        self.write(json.dumps({"latest": latest, "errors": out}))


class HistoryHandler(tornado.web.RequestHandler):
    """Report previously-played tracks: a count/last for the back button, plus the
    full most-recent-first list for the History view."""

    def get(self):
        with _history_lock:
            count = len(_history)
            last = _history[-1]["name"] if _history else None
            # Most-recent-first copy for the History drawer (already capped at 200).
            entries = [
                {"uri": h.get("uri"), "name": h.get("name")}
                for h in reversed(_history)
            ]
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps({"count": count, "last": last, "entries": entries}))


class EventSocketHandler(tornado.websocket.WebSocketHandler):
    """A tiny party-wide event channel. Clients open this WebSocket and the server
    pushes shared-state changes (radio on/off, blocklist updates) so every screen
    updates instantly. Mopidy's own WebSocket only carries core events, so
    NETJammer-specific state needs its own channel. Clients also poll as a fallback
    in case this socket can't connect (e.g. a proxy that won't upgrade it)."""

    _clients = set()
    _lock = threading.Lock()

    def check_origin(self, origin):
        return True  # LAN party app served to phones on the same host; allow any

    def open(self):
        self._io = tornado.ioloop.IOLoop.current()
        with EventSocketHandler._lock:
            EventSocketHandler._clients.add(self)
        # Send a snapshot so a freshly-connected client is immediately in sync.
        try:
            with _radio_lock:
                on = _radio["on"]
            with _radio_meta_lock:
                entries = [{"uri": u, "name": n} for u, n in _radio_blocklist.items()]
            self.write_message(json.dumps(
                {"type": "snapshot", "radio": on, "blocklist": entries,
                 "pins": _radio_pins_snapshot()}))
        except Exception:
            pass

    def on_close(self):
        with EventSocketHandler._lock:
            EventSocketHandler._clients.discard(self)

    def on_message(self, message):
        pass  # clients only listen; ignore anything sent up

    def _send(self, msg):
        try:
            self.write_message(msg)
        except Exception:
            with EventSocketHandler._lock:
                EventSocketHandler._clients.discard(self)

    @classmethod
    def broadcast(cls, payload):
        """Push a JSON payload to every connected client. Safe to call from any
        thread: each send is scheduled on its connection's IOLoop."""
        msg = json.dumps(payload)
        with cls._lock:
            clients = list(cls._clients)
        for c in clients:
            try:
                c._io.add_callback(c._send, msg)
            except Exception:
                with cls._lock:
                    cls._clients.discard(c)


class RadioBlockHandler(tornado.web.RequestHandler):
    """The Radio Blocklist: songs radio must never seed from. GET returns the
    current list; POST {uri, name, on} adds (on=true, default) or removes it.
    Blocking a song also prunes the not-yet-played tracks radio spawned from it."""

    def initialize(self, core):
        self.core = core

    def _entries(self):
        with _radio_meta_lock:
            return [{"uri": u, "name": n} for u, n in _radio_blocklist.items()]

    def get(self):
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps({"entries": self._entries()}))

    def post(self):
        try:
            data = json.loads(self.request.body.decode())
        except Exception:
            self.set_status(400)
            self.write(json.dumps({"error": "Invalid request format"}))
            return
        uri = (data.get("uri") or "").strip()
        name = (data.get("name") or uri or "").strip()
        on = data.get("on", True)
        if not uri:
            self.set_status(400)
            self.write(json.dumps({"error": "uri is required"}))
            return
        removed = 0
        if on:
            with _radio_meta_lock:
                _radio_blocklist[uri] = name
            removed = _prune_radio_offspring(self.core, uri)
            logger.info("radio: blocklisted %s [%s]; pruned %d queued offspring", name, uri, removed)
        else:
            with _radio_meta_lock:
                _radio_blocklist.pop(uri, None)
            logger.info("radio: un-blocklisted %s [%s]", name, uri)
        entries = self._entries()
        # Nudge every open screen to re-pull shared state (block buttons, queue
        # colouring, pruned queue) instantly.
        EventSocketHandler.broadcast({"type": "changed"})
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps({"ok": True, "blocked": bool(on), "removed": removed,
                               "entries": entries}))


class RadioHandler(tornado.web.RequestHandler):
    """Shared, party-wide radio toggle. GET reports state; POST {"on": bool}
    sets it. Turning it on kicks an immediate refill of similar songs."""

    def initialize(self, core, config):
        self.core = core
        self.config = config

    def _has_key(self):
        return _radio_available(self.config)

    def get(self):
        self.set_header("Content-Type", "application/json")
        with _radio_lock:
            on = _radio["on"]
        self.write(json.dumps({"on": on, "available": self._has_key()}))

    def post(self):
        try:
            body = json.loads(self.request.body.decode() or "{}")
        except Exception:
            body = {}
        want_on = bool(body.get("on"))
        if want_on and not self._has_key():
            self.set_status(409)
            self.write(json.dumps({"error": "Radio needs a music source: install "
                                   "ytmusicapi on the server, or set lastfm_api_key "
                                   "in the [netjammer] config.",
                                   "on": False, "available": False}))
            return
        with _radio_lock:
            _radio["on"] = want_on
        logger.info("radio: turned %s", "on" if want_on else "off")
        # Nudge every open screen to re-pull shared state so their toggle updates
        # instantly.
        EventSocketHandler.broadcast({"type": "changed"})
        if want_on:
            # Fill immediately (force) so music keeps going without waiting for
            # the next track boundary.
            _maybe_refill_radio(self.core, self.config, force=True)
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps({"on": want_on, "available": self._has_key()}))


def _find_track(core, uri):
    """The Track object for `uri` from the tracklist (has artist metadata)."""
    try:
        for tl in core.tracklist.get_tl_tracks().get() or []:
            if getattr(tl.track, "uri", None) == uri:
                return tl.track
    except Exception:
        pass
    return None


class RadioSeedHandler(tornado.web.RequestHandler):
    """Station steering. POST {action: add|remove|clear, kind: track|artist|genre,
    value, label}. While any pins exist radio seeds ONLY from them; with none it
    falls back to the songs people requested. Adding a pin turns radio on, swaps
    out upcoming radio picks that came from other seeds, and refills right away."""

    MAX_PINS = 5

    def initialize(self, core, config):
        self.core = core
        self.config = config

    def post(self):
        self.set_header("Content-Type", "application/json")
        try:
            data = json.loads(self.request.body.decode() or "{}")
        except Exception:
            self.set_status(400)
            self.write(json.dumps({"error": "Invalid request format"}))
            return
        action = (data.get("action") or "add").strip()
        kind = (data.get("kind") or "").strip()
        value = (data.get("value") or "").strip()[:200]
        label = (data.get("label") or value).strip()[:200]

        if action == "clear":
            with _radio_meta_lock:
                _radio_pins[:] = []
            logger.info("radio: station cleared (back to auto)")
        elif action == "remove":
            with _radio_meta_lock:
                _radio_pins[:] = [p for p in _radio_pins
                                  if not (p["kind"] == kind and p["value"].lower() == value.lower())]
            logger.info("radio: unpinned [%s] %s", kind, value)
        elif action == "add":
            if kind not in ("track", "artist", "genre") or not value:
                self.set_status(400)
                self.write(json.dumps({"error": "kind (track|artist|genre) and value are required"}))
                return
            if not _radio_available(self.config):
                self.set_status(409)
                self.write(json.dumps({"error": "Radio has no music source configured"}))
                return
            pin = {"kind": kind, "value": value, "label": label}
            if kind == "track":
                tr = _find_track(self.core, value)
                if tr is not None:
                    pin["artist"], pin["title"] = _seed_from_track(tr)
                    pin["label"] = label or tr.name or value
                else:
                    # e.g. a History entry: we only have its display name.
                    artist = (data.get("artist") or "").strip()
                    title = _clean_title(label)
                    if not artist and " - " in title:
                        artist, title = [x.strip() for x in title.split(" - ", 1)]
                    pin["artist"], pin["title"] = artist, title
            with _radio_meta_lock:
                _radio_pins[:] = [p for p in _radio_pins
                                  if not (p["kind"] == kind and p["value"].lower() == value.lower())]
                _radio_pins.append(pin)
                del _radio_pins[:-self.MAX_PINS]
                pin_keys = set(s.key for s in (_pin_seed(p) for p in _radio_pins) if s)
            with _radio_lock:
                _radio["on"] = True
            # Out with the old direction: drop queued picks that came from other seeds.
            removed = _prune_upcoming_picks(
                self.core, lambda uri, keys: not (keys & pin_keys))
            logger.info("radio: pinned [%s] %s; replaced %d queued pick(s)", kind, pin["label"], removed)
            _maybe_refill_radio(self.core, self.config, force=True)
        else:
            self.set_status(400)
            self.write(json.dumps({"error": "unknown action"}))
            return
        EventSocketHandler.broadcast({"type": "changed"})
        with _radio_lock:
            on = _radio["on"]
        self.write(json.dumps({"ok": True, "on": on, "pins": _radio_pins_snapshot()}))


class RadioFeedbackHandler(tornado.web.RequestHandler):
    """Thumbs on radio picks. POST {uri, name, artist?, vote: up|down|none}.
    up: the song becomes a seed (more like this). down: block the song, ban its
    artist from radio for this session, drop it (if still queued) and anything
    radio queued because of it. none: undo a thumbs-up."""

    def initialize(self, core, config):
        self.core = core
        self.config = config

    def post(self):
        self.set_header("Content-Type", "application/json")
        try:
            data = json.loads(self.request.body.decode() or "{}")
        except Exception:
            self.set_status(400)
            self.write(json.dumps({"error": "Invalid request format"}))
            return
        uri = (data.get("uri") or "").strip()
        name = (data.get("name") or uri).strip()
        vote = (data.get("vote") or "").strip()
        if not uri or vote not in ("up", "down", "none"):
            self.set_status(400)
            self.write(json.dumps({"error": "uri and vote (up|down|none) are required"}))
            return
        tr = _find_track(self.core, uri)
        with _radio_meta_lock:
            artist = (_radio_pick_artist.get(uri) or data.get("artist") or "").strip()
        title = _clean_title(name)
        if tr is not None:
            a, title = _seed_from_track(tr)
            artist = artist or a
        removed = 0
        if vote == "up":
            with _radio_meta_lock:
                _radio_liked[uri] = {"name": name, "artist": artist, "title": title}
                _radio_blocklist.pop(uri, None)
            logger.info("radio: thumbs up %s (%s)", name, artist or "?")
        elif vote == "none":
            with _radio_meta_lock:
                _radio_liked.pop(uri, None)
        else:
            with _radio_meta_lock:
                _radio_liked.pop(uri, None)
                _radio_blocklist[uri] = name
                if _norm_artist(artist):
                    _radio_artist_ban[_norm_artist(artist)] = artist
            removed = _prune_upcoming_picks(
                self.core, lambda u, keys: u == uri or uri in keys)
            logger.info("radio: thumbs down %s; banned artist %r; removed %d", name, artist, removed)
            _maybe_refill_radio(self.core, self.config)
        EventSocketHandler.broadcast({"type": "changed"})
        self.write(json.dumps({"ok": True, "vote": vote, "artist": artist, "removed": removed}))


class RadioStateHandler(tornado.web.RequestHandler):
    """One shared-state snapshot for the frontend to poll/refresh: radio on/off,
    whether radio is available, the blocklist URIs, the URIs radio added itself
    (algorithm vs user, for queue colouring), and the URIs currently seeding radio
    (for highlighting the influencing songs in History)."""

    def initialize(self, core, config):
        self.core = core
        self.config = config

    def get(self):
        with _radio_lock:
            on = _radio["on"]
        available = _radio_available(self.config)
        with _radio_meta_lock:
            blocklist = list(_radio_blocklist.keys())
            added = list(_radio_provenance.keys())
            pins = [dict(p) for p in _radio_pins]
            liked = list(_radio_liked.keys())
            banned = sorted(_radio_artist_ban.values())
        try:
            seeds = _current_seed_uris(self.core, self.config)
        except Exception:
            seeds = []
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps({
            "on": on, "available": available,
            "blocklist": blocklist, "added": added, "seeds": seeds,
            "pins": pins, "liked": liked, "banned_artists": banned,
        }))


class PreviousHandler(tornado.web.RequestHandler):
    """The "back" button. With consume off the previous track is still in the
    tracklist, so this is just Mopidy's native previous() -- no re-insertion."""

    def initialize(self, core):
        self.core = core

    def post(self):
        try:
            idx = self.core.tracklist.index().get()
            if idx is None or idx <= 0:
                self.set_status(409)
                self.write(json.dumps({"error": "No previous song to play"}))
                return
            tl = self.core.tracklist.get_tl_tracks().get()
            prev = tl[idx - 1]
            self.core.playback.play(tlid=prev.tlid)
            logger.info("back: previous track %s", prev.track.uri)
            self.write(json.dumps({"success": True, "name": prev.track.name}))
        except Exception as e:
            logger.error("back: previous failed: %r", e)
            self.set_status(500)
            self.write(json.dumps({"error": "Could not go to previous song: " + repr(e)}))


class ClientLogHandler(tornado.web.RequestHandler):
    """Ingest a batch of client-side log entries so they merge with server logs."""

    def post(self):
        try:
            payload = json.loads(self.request.body.decode() or "[]")
        except Exception:
            self.set_status(400)
            self.write("bad json")
            return
        if isinstance(payload, dict):
            payload = [payload]
        for e in payload if isinstance(payload, list) else []:
            try:
                _record_log(
                    e.get("ts") or time.time(),
                    e.get("level", "INFO"),
                    "client",
                    e.get("msg", ""),
                    "client",
                )
            except Exception:
                pass
        self.write("ok")


class LogsHandler(tornado.web.RequestHandler):
    """Return the merged server+client diagnostics log. ?format=json for JSON,
    ?download=1 to download as a .txt file. Includes a live playback snapshot."""

    def initialize(self, core, config):
        self.core = core
        self.config = config

    def _snapshot(self):
        lines = []
        # Effective config values, so we can tell whether the config file the user
        # edited is actually the one Mopidy loaded (compare against what they set).
        try:
            key = (_conf(self.config, "lastfm_api_key") or "").strip()
            lines.append("config effective: style=%s votes_to_skip=%s lastfm_api_key=%s"
                         % (_conf(self.config, "style"),
                            _conf(self.config, "votes_to_skip"),
                            "SET" if key else "(empty)"))
        except Exception as e:
            lines.append("config read error: %r" % e)
        try:
            state = self.core.playback.get_state().get()
            cur = self.core.playback.get_current_track().get()
            tl = self.core.tracklist.get_tl_tracks().get()
            vol = self.core.mixer.get_volume().get()
            consume = self.core.tracklist.get_consume().get()
            repeat = self.core.tracklist.get_repeat().get()
            single = self.core.tracklist.get_single().get()
            random = self.core.tracklist.get_random().get()
            lines.append("playback state : %s" % state)
            lines.append("current track  : %s" % (("%s [%s]" % (cur.name, cur.uri)) if cur else "none"))
            lines.append(
                "tracklist len  : %s (consume=%s repeat=%s single=%s random=%s)"
                % (len(tl or []), consume, repeat, single, random)
            )
            for i, t in enumerate((tl or [])[:20]):
                lines.append("   #%d %s [%s]" % (i, t.track.name or "?", t.track.uri))
            lines.append("volume         : %s" % vol)
        except Exception as e:
            lines.append("snapshot error: %r" % e)
        with _history_lock:
            lines.append("history depth  : %d" % len(_history))
        with _radio_lock:
            lines.append("radio          : %s (busy=%s)" % (
                "on" if _radio["on"] else "off", _radio_busy))
        try:
            lines.append("radio config   : min_queue=%s batch=%s seed_count=%s" % (
                _conf(self.config, "radio_min_queue"),
                _conf(self.config, "radio_batch"),
                _conf(self.config, "radio_seed_count")))
        except Exception as e:
            lines.append("radio config read error: %r" % e)
        with _radio_meta_lock:
            lines.append("radio blocklist: %d song(s), provenance=%d" % (
                len(_radio_blocklist), len(_radio_provenance)))
        with EventSocketHandler._lock:
            lines.append("event sockets  : %d connected" % len(EventSocketHandler._clients))
        return lines

    def get(self):
        with _log_lock:
            items = sorted(list(_log_buffer), key=lambda x: x["ts"])
        if self.get_argument("format", "text") == "json":
            self.set_header("Content-Type", "application/json")
            self.write(json.dumps({"version": __version__, "entries": items}))
            return

        out = []
        out.append("NETJammer diagnostics")
        out.append("version   : %s" % __version__)
        out.append("generated : %s" % _fmt_ts(time.time()))
        out.append("entries   : %d" % len(items))
        out.append("")
        out.append("=== current snapshot ===")
        out.extend(self._snapshot())
        out.append("")
        out.append("=== log (oldest first; S=server C=client) ===")
        for it in items:
            out.append(
                "%s %s %-7s %s: %s"
                % (
                    _fmt_ts(it["ts"]),
                    (it.get("source", "?")[:1].upper()),
                    it.get("level", ""),
                    it.get("logger", ""),
                    it.get("msg", ""),
                )
            )
        text = "\n".join(out)
        self.set_header("Content-Type", "text/plain; charset=utf-8")
        if self.get_argument("download", None) is not None:
            self.set_header(
                "Content-Disposition", 'attachment; filename="netjammer-logs.txt"'
            )
        self.write(text)


def party_factory(config, core):
    from tornado.web import RedirectHandler

    data = {
        "track": "",
        "votes": [],
        "queue": [None] * _conf(config, "max_tracks"),
        "last": None,
        "errors": deque(maxlen=50),
        "error_seq": 0,
    }

    # Install the log watcher once, wired to this app's shared error buffer.
    global _handler_installed
    if not _handler_installed:
        error_handler = PlaybackErrorLogHandler(data)
        error_handler.setLevel(logging.WARNING)
        logging.getLogger().addHandler(error_handler)
        # Diagnostics buffer: NETJammer INFO + anything WARNING and above.
        diag_handler = DiagnosticsLogHandler()
        diag_handler.setLevel(logging.INFO)
        logging.getLogger().addHandler(diag_handler)
        logger.setLevel(logging.INFO)  # ensure our own INFO records propagate
        _handler_installed = True
        logger.info("NETJammer %s started; diagnostics logging enabled", __version__)

    return [
        (
            "/",
            RedirectHandler,
            {"url": "index.html"},
        ),  # always redirect from extension root to the html
        ("/index.html", IndexHandler, {"config": config}),
        ("/vote", VoteRequestHandler, {"core": core, "data": data, "config": config}),
        ("/add", AddRequestHandler, {"core": core, "data": data, "config": config}),
        ("/playlist", PlaylistHandler, {"core": core, "data": data, "config": config}),
        ("/version", VersionHandler, {}),
        ("/config", ConfigHandler, {"config": config}),
        ("/errors", ErrorsHandler, {"data": data}),
        ("/history", HistoryHandler, {}),
        ("/previous", PreviousHandler, {"core": core}),
        ("/radio", RadioHandler, {"core": core, "config": config}),
        ("/radio_state", RadioStateHandler, {"core": core, "config": config}),
        ("/radio_block", RadioBlockHandler, {"core": core}),
        ("/radio_seed", RadioSeedHandler, {"core": core, "config": config}),
        ("/radio_feedback", RadioFeedbackHandler, {"core": core, "config": config}),
        ("/events", EventSocketHandler),
        ("/clientlog", ClientLogHandler, {}),
        ("/logs", LogsHandler, {"core": core, "config": config}),
    ]


class Extension(ext.Extension):
    dist_name = "Mopidy-NETJammer"
    ext_name = "netjammer"
    version = __version__

    def get_default_config(self):
        conf_file = os.path.join(os.path.dirname(__file__), "ext.conf")
        return config.read(conf_file)

    def get_config_schema(self):
        schema = super(Extension, self).get_config_schema()
        schema["votes_to_skip"] = config.Integer(minimum=0)
        schema["max_tracks"] = config.Integer(minimum=0)
        schema["hide_pause"] = config.Boolean(optional=True)
        schema["hide_skip"] = config.Boolean(optional=True)
        schema["style"] = config.String()
        schema["max_results"] = config.Integer(minimum=0, optional=True)
        schema["max_queue_length"] = config.Integer(minimum=0, optional=True)
        schema["max_song_duration"] = config.Integer(minimum=0, optional=True)
        schema["default_volume"] = config.Integer(minimum=0, maximum=100, optional=True)
        schema["source_prio"] = config.String(optional=True)
        schema["source_blacklist"] = config.String(optional=True)
        schema["lastfm_api_key"] = config.Secret(optional=True)
        schema["radio_min_queue"] = config.Integer(minimum=1, optional=True)
        schema["radio_batch"] = config.Integer(minimum=1, optional=True)
        schema["radio_seed_count"] = config.Integer(minimum=1, optional=True)
        schema["radio_source"] = config.String(optional=True)
        schema["radio_min_duration"] = config.Integer(minimum=0, optional=True)
        schema["radio_max_duration"] = config.Integer(minimum=0, optional=True)
        return schema

    def setup(self, registry):
        registry.add(
            "http:static",
            {
                "name": self.ext_name,
                "path": os.path.join(os.path.dirname(__file__), "static"),
            },
        )
        registry.add(
            "http:app",
            {
                "name": self.ext_name,
                "factory": party_factory,
            },
        )
        # Frontend actor that records shared play history for the back button.
        registry.add("frontend", NetjammerFrontend)
