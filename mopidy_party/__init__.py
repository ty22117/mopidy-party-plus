import os
import json
import re

import tornado.web

from mopidy import config, ext

__version__ = "1.3.0-PARTY_PLUS_FIXED_v2"
# VERSION MARKER: If you see "1.3.0-PARTY_PLUS_FIXED_v2" in logs, the latest code is loaded


class VoteRequestHandler(tornado.web.RequestHandler):

    def initialize(self, core, data, config):
        self.core = core
        self.data = data
        self.requiredVotes = config["party_plus"]["votes_to_skip"]

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
        self.maxQueueLength = config["party_plus"]["max_queue_length"]

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
        self.maxQueueLength = config["party_plus"]["max_queue_length"]

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

            # Add all extracted tracks to queue
            added_count = 0
            for track_url in tracks:
                try:
                    # Use the URL directly - mopidy backends handle URLs
                    track_uri = track_url
                    print(f"[PARTY_PLUS] Adding track: {track_uri}")

                    pos = 0
                    if self.data["last"]:
                        queue = self.core.tracklist.index(self.data["last"]).get() or 0
                        current = self.core.tracklist.index().get() or 0
                        pos = max(queue, current)
                        if (self.maxQueueLength > 0) and (
                            pos >= self.maxQueueLength - 1
                        ):
                            break

                    last_track = self.core.tracklist.add(
                        uris=[track_uri], at_position=pos + 1
                    ).get()[0]
                    self.data["last"] = last_track
                    self.data["queue"].append(self._getip())
                    self.data["queue"].pop(0)
                    added_count += 1
                    print(f"[PARTY_PLUS] Successfully added track to queue")
                except Exception as e:
                    print(f"[PARTY_PLUS] Error adding track {track_uri}: {repr(e)}")
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
            print(f"[PARTY_PLUS] Extracting YouTube playlist from: {url}")
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
                print(f"[PARTY_PLUS] Found {len(info['entries'])} entries in playlist")
                for entry in info["entries"]:
                    if entry:
                        video_id = entry.get("id")
                        if video_id:
                            # Create full YouTube URL for mopidy-youtube backend
                            video_url = f"https://www.youtube.com/watch?v={video_id}"
                            tracks.append(video_url)
                            print(f"[PARTY_PLUS] Added video: {video_url}")
            else:
                # Single video
                video_id = info.get("id")
                if video_id:
                    video_url = f"https://www.youtube.com/watch?v={video_id}"
                    tracks.append(video_url)
                    print(f"[PARTY_PLUS] Added single video: {video_url}")

            print(f"[PARTY_PLUS] Total tracks extracted: {len(tracks)}")
            return tracks
        except Exception as e:
            print(f"[PARTY_PLUS] Error extracting YouTube playlist: {repr(e)}")
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
        # Make the configuration from mopidy.conf [party_plus] section available as variables in index.html
        for conf_key, value in config["party_plus"].items():
            if conf_key != "enabled":
                self.__dict[conf_key] = value

    def get(self):
        return self.render("static/index.html", **self.__dict)


class ConfigHandler(tornado.web.RequestHandler):

    def initialize(self, config):
        self.party_cfg = config["party_plus"]

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


def party_factory(config, core):
    from tornado.web import RedirectHandler

    data = {
        "track": "",
        "votes": [],
        "queue": [None] * config["party_plus"]["max_tracks"],
        "last": None,
    }

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
    ]


class Extension(ext.Extension):
    dist_name = "Mopidy-Party-Plus"
    ext_name = "party_plus"
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
