import os
import json
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

from mopidy import config, core, ext

__version__ = "1.10.3-NETJAMMER"

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
        # Report whether the Last.fm key was loaded (drives whether Radio is usable).
        key = (_conf(self.config, "lastfm_api_key") or "").strip()
        logger.info(
            "startup: last.fm api key %s",
            "configured (radio available)" if key else "NOT configured (radio disabled)",
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


# ===== Radio mode: auto-queue similar songs (Last.fm -> YouTube) =====

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
    """Return (artist, title) to seed Last.fm from a Mopidy Track."""
    artist = ""
    try:
        if track.artists:
            artist = next(iter(track.artists)).name or ""
    except Exception:
        artist = ""
    title = _clean_title(getattr(track, "name", "") or "")
    return _clean_title(artist), title


def _lastfm_similar(artist, title, api_key, limit):
    """Query Last.fm track.getSimilar -> list of (artist, title). Falls back to
    artist.getSimilar's top artists (as {artist, ''} seeds) if no track match."""
    def _call(params):
        params = dict(params)
        params.update({"api_key": api_key, "format": "json"})
        url = "https://ws.audioscrobbler.com/2.0/?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": "NETJammer/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))

    out = []
    try:
        data = _call({
            "method": "track.getsimilar",
            "artist": artist,
            "track": title,
            "limit": limit,
            "autocorrect": 1,
        })
        for t in (data.get("similartracks", {}) or {}).get("track", []) or []:
            nm = t.get("name")
            ar = (t.get("artist") or {}).get("name")
            if nm and ar:
                out.append((ar, nm))
    except Exception as e:
        logger.warning("radio: last.fm getSimilar failed: %r", e)

    if not out and artist:
        # Fallback: similar artists -> we search by artist name only.
        try:
            data = _call({
                "method": "artist.getsimilar",
                "artist": artist,
                "limit": limit,
                "autocorrect": 1,
            })
            for a in (data.get("similarartists", {}) or {}).get("artist", []) or []:
                nm = a.get("name")
                if nm:
                    out.append((nm, ""))
        except Exception as e:
            logger.warning("radio: last.fm artist.getSimilar failed: %r", e)
    return out


def _norm_key(artist, title):
    return re.sub(r"\s+", " ", ("%s %s" % (artist, title)).strip().lower())


def _refill_radio(core, api_key, batch, seed_track=None):
    """Fetch songs similar to the seed (default: currently playing), resolve each
    to a YouTube track via library.search, and append playable ones. Runs in a
    background thread (never call from the actor's event loop directly)."""
    global _radio_busy
    try:
        seed = seed_track
        if seed is None:
            try:
                seed = core.playback.get_current_track().get()
            except Exception:
                seed = None
        if seed is None:
            logger.info("radio: no seed track; nothing to refill")
            return

        artist, title = _seed_from_track(seed)
        if not title and not artist:
            logger.info("radio: seed has no usable artist/title")
            return
        logger.info("radio: seeding from %s - %s", artist or "?", title or "?")

        similar = _lastfm_similar(artist, title, api_key, max(batch * 4, 20))
        if not similar:
            logger.info("radio: no similar tracks found for %s - %s", artist, title)
            return

        # What's already queued or recently played, to avoid repeats.
        try:
            existing_uris = set(
                t.track.uri for t in (core.tracklist.get_tl_tracks().get() or [])
            )
        except Exception:
            existing_uris = set()
        with _history_lock:
            recent_keys = set(
                _norm_key("", h.get("name", "")) for h in list(_history)[-40:]
            )

        added = 0
        first_added = None
        for sim_artist, sim_title in similar:
            if added >= batch:
                break
            query = (sim_artist + " " + sim_title).strip()
            if not query:
                continue
            try:
                results = core.library.search(
                    query={"any": [query]}, uris=["youtube:"]
                ).get()
            except Exception as e:
                logger.warning("radio: search failed for %r: %r", query, e)
                continue
            uri = None
            for res in results or []:
                for tr in (getattr(res, "tracks", None) or []):
                    if getattr(tr, "uri", None):
                        uri = tr.uri
                        break
                if uri:
                    break
            if not uri or uri in existing_uris:
                continue
            if _norm_key("", sim_title) in recent_keys:
                continue
            try:
                new_tls = core.tracklist.add(uris=[uri]).get()
                existing_uris.add(uri)
                added += 1
                if first_added is None and new_tls:
                    first_added = new_tls[0]
                logger.info("radio: added %s - %s [%s]", sim_artist, sim_title, uri)
            except Exception as e:
                logger.warning("radio: add failed for %s: %r", uri, e)

        # If playback had already stopped (e.g. the last song ended before this
        # refill finished), start the first track we just added so radio keeps
        # the music going without a gap.
        if added and first_added is not None:
            try:
                if core.playback.get_state().get() == "stopped":
                    core.playback.play(tlid=first_added.tlid)
                    logger.info("radio: playback was stopped, starting %s", first_added.track.uri)
            except Exception as e:
                logger.warning("radio: could not resume playback: %r", e)

        logger.info("radio: refill complete, added %d track(s)", added)
    finally:
        with _radio_lock:
            _radio_busy = False


def _maybe_refill_radio(core, config, force=False):
    """If radio is on (and, unless forced, the queue is running low), kick a
    background refill. Guarded so only one refill runs at a time."""
    global _radio_busy
    with _radio_lock:
        if not _radio["on"]:
            return
        if _radio_busy:
            return
    api_key = (_conf(config, "lastfm_api_key") or "").strip()
    if not api_key:
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
            return
        _radio_busy = True
    batch = int(_conf(config, "radio_batch"))
    threading.Thread(
        target=_refill_radio, args=(core, api_key, batch), daemon=True
    ).start()


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
    """Report how many previously-played tracks are available to go back to."""

    def get(self):
        with _history_lock:
            count = len(_history)
            last = _history[-1]["name"] if _history else None
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps({"count": count, "last": last}))


class RadioHandler(tornado.web.RequestHandler):
    """Shared, party-wide radio toggle. GET reports state; POST {"on": bool}
    sets it. Turning it on kicks an immediate refill of similar songs."""

    def initialize(self, core, config):
        self.core = core
        self.config = config

    def _has_key(self):
        return bool((_conf(self.config, "lastfm_api_key") or "").strip())

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
            self.write(json.dumps({"error": "Radio needs a Last.fm API key (set "
                                   "lastfm_api_key in the [netjammer] config).",
                                   "on": False, "available": False}))
            return
        with _radio_lock:
            _radio["on"] = want_on
        logger.info("radio: turned %s", "on" if want_on else "off")
        if want_on:
            # Fill immediately (force) so music keeps going without waiting for
            # the next track boundary.
            _maybe_refill_radio(self.core, self.config, force=True)
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps({"on": want_on, "available": self._has_key()}))


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
        ("/config", ConfigHandler, {"config": config}),
        ("/errors", ErrorsHandler, {"data": data}),
        ("/history", HistoryHandler, {}),
        ("/previous", PreviousHandler, {"core": core}),
        ("/radio", RadioHandler, {"core": core, "config": config}),
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
