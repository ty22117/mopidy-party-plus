# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Friends at a gathering who share one music system. Each person opens NETJammer in their own browser, **mostly on a personal laptop or desktop at normal viewing distance**, sometimes on a phone. They search for songs and queue them, adjust the volume, skip, and steer the radio. Many are first-time visitors who should understand it at a glance, with no instructions.

The host (the project owner) runs the Raspberry Pi and also uses the page to monitor it and fix problems (history, radio blocklist, diagnostics).

## Product Purpose

NETJammer is a shared jukebox. It is a web front end for a Mopidy server on a Raspberry Pi that plays through the room's speakers. Anyone on the network can see what's playing, add songs, reorder the queue and steer an automatic radio that keeps music going when the queue runs dry.

Success means the music never stops, anyone can add a song in seconds, and the radio stays close to what the room actually wants.

## Positioning

It's a party jukebox with a personality, the host's own cartoon self, and a radio people can steer together (pins, stations, thumbs up/down), unlike an anonymous queue or a single person's streaming app.

## Operating Context

- Served by the Mopidy HTTP extension at `http://<pi>:6680/netjammer/`. The Pi is a Raspberry Pi running Mopidy 3.4 with the system Python.
- Music comes mostly from YouTube (mopidy-youtube). Search results show their source with an icon.
- Several people use it at the same time. Every client polls and reflects the shared state (queue, now playing, radio, volume).
- Deployment is `git pull` on the Pi plus a Mopidy restart. There is no build step.

## Capabilities and Constraints

Every existing capability must survive the redesign:

- **Now Playing:** album art, title and artist, a seekable progress bar, previous/restart, play/pause, skip. Skipping is subject to `votes_to_skip` (default 3), and the host can hide skip with `hide_skip`.
- **Volume:** a shared volume slider. This is the **2nd most important** control.
- **Search:** searches every source in order, with a source icon on each result. Results can add a single track or a whole playlist, and there's a browse view. Config limits apply (`max_results`, `max_queue_length`, `max_song_duration`, `max_tracks`).
- **Queue:** list with origin tint (user-added vs radio-added vs current radio seed), move up/down, drag reorder, remove one, clear all, refresh.
- **Radio:** on/off; "Radio from this" pin on a song; artist/genre station panel with removable pin chips and clear station; thumbs up/down on radio picks; radio blocklist. Endpoints: `/radio_state`, `/radio_seed`, `/radio_feedback`.
- **History:** previously played songs, with requeue and block/unblock from radio.
- **Toast messages** for errors and confirmations, and a **diagnostics** log download for troubleshooting.
- **Themes:** each browser remembers its own choice in `localStorage`, applied before first paint so the page doesn't flash.

Priority (most to least important): Now Playing → Volume → Search → Queue → Radio → History → Diagnostics.

Technical constraints:
- Keep **AngularJS 1.x** (`controller.js`, `{{! }}` interpolation, existing scope functions and endpoints) and **no build step**. Static files are served from `mopidy_party_plus/static/`.
- **Remove Bootstrap** entirely. Font Awesome can stay or be replaced.
- Fonts and other assets must be **self-hosted** in `static/` (no CDN), so the page works even when the internet is unreliable.
- **No image generation is available** (no OpenAI key, no native image tool). Build code-first. New artwork is supplied by hand, see `docs/redesign-brief.md`.

## Brand Commitments

- The name **NETJammer** is required. It needs a proper custom wordmark, not plain bold text.
- **The guy** is a cartoon of the host and the visual hero of the product. His **swept-up hair, round glasses and big handlebar mustache must always stay** so he's recognizable as the host. Clothes, pose, scene and art style can change. The current art is `static/art/listening-room/scene.png` (dark) and `static/art/daylight/scene.png` (light). `final.png` at the repo root is a wider dark variant.
- The existing BYU navy accent is **not** binding.

## Evidence on Hand

- Character art: `mopidy_party_plus/static/art/listening-room/scene.png`, `mopidy_party_plus/static/art/daylight/scene.png`, `final.png`. These are the only images of the guy. Don't invent a different-looking character.
- No testimonials, user counts or other claims exist. Don't fabricate any.

## Product Principles

1. **The music controller is the center.** Everything else serves keeping the music going.
2. **Instant to understand.** A first-time guest can add a song in seconds without instructions.
3. **Calm, not cluttered.** The host prefers a calm first screen with secondary tools a click away. This is a preference, not a rule; a better idea wins.
4. **Personality through the guy.** The host's character makes it feel like *their* party, not a generic app.
5. **Shared and live.** Everyone sees the same state, so changes others make should feel visible and immediate.

## Accessibility & Inclusion

Used in dim rooms, often by people who are mid-conversation. Text must be easy to read on every theme and over the art. All controls must work by keyboard. Respect `prefers-reduced-motion`.
