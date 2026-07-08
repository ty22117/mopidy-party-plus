import os
import json
import re
import logging
import threading
from collections import deque

import tornado.web

from mopidy import config, ext

__version__ = "1.5.0-NETJAMMER"

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


class VoteRequestHandler(tornado.web.RequestHandler):

    def initialize(self, core, data, config):
        self.core = core
        self.data = data
        self.requiredVotes = config["netjammer"]["votes_to_skip"]

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
        self.maxQueueLength = config["netjammer"]["max_queue_length"]

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
            self.write("Unable to add track. Internal Server Error: " + repr(e))
            self.set_status(500)
            return

        self.core.tracklist.set_consume(True)
        if self.core.playback.get_state().get() == "stopped":
            self.core.playback.play()


class PlaylistHandler(tornado.web.RequestHandler):
    """Handle playlist and album URLs from YouTube, Spotify, etc."""

    def initialize(self, core, data, config):
        self.core = core
        self.data = data
        self.config = config
        self.maxQueueLength = config["netjammer"]["max_queue_length"]

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

                    # Only log one entry in anti-spam queue tracking per playlist chunk
                    if added_count == 0:
                        self.data["queue"].append(self._getip())
                        self.data["queue"].pop(0)

                    added_count += 1
                except Exception as e:
                    print(f"[NETJammer] Error adding track {track_uri}: {repr(e)}")

            # CRITICAL FIX: Trigger playback ONCE after all tracks have been processed
            if added_count > 0 and self.core.playback.get_state().get() == "stopped":
                self.core.playback.play()

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
        self.__dict = {}
        # Make the configuration from mopidy.conf [netjammer] section available as variables in index.html
        for conf_key, value in config["netjammer"].items():
            if conf_key != "enabled":
                self.__dict[conf_key] = value

    def get(self):
        return self.render("static/index.html", **self.__dict)


class ConfigHandler(tornado.web.RequestHandler):

    def initialize(self, config):
        self.party_cfg = config["netjammer"]

    def get(self):
        conf_key = self.get_argument("key")
        if conf_key == []:
            self.set_status(400)
            self.write("Query parameter 'key' not present")
            return
        try:
            value = self.party_cfg[conf_key]
            self.write(repr(value))
        except KeyError:
            self.set_status(404)
            self.write("Party configuration '" + conf_key + "' not found")
            return
        except Exception as e:
            self.set_status(500)
            self.write("Internal server error: " + repr(e))
            return


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


def party_factory(config, core):
    from tornado.web import RedirectHandler

    data = {
        "track": "",
        "votes": [],
        "queue": [None] * config["netjammer"]["max_tracks"],
        "last": None,
        "errors": deque(maxlen=50),
        "error_seq": 0,
    }

    # Install the log watcher once, wired to this app's shared error buffer.
    global _handler_installed
    if not _handler_installed:
        handler = PlaybackErrorLogHandler(data)
        handler.setLevel(logging.WARNING)
        logging.getLogger().addHandler(handler)
        _handler_installed = True

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
        schema["source_prio"] = config.String(optional=True)
        schema["source_blacklist"] = config.String(optional=True)
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
