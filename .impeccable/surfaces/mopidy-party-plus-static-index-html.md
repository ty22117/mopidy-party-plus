---
version: 1
slug: "mopidy-party-plus-static-index-html"
primary_target: "mopidy_party_plus/static/index.html"
related_targets: ["mopidy_party_plus/static/controller.js","mopidy_party_plus/static/netjammer.css"]
---

# NETJammer web app (main screen)

Scope: the single-page jukebox at `/netjammer/` (index.html, controller.js, netjammer.css). Mode: Operate.

Audience/job: party guests on laptops (some phones) add songs, set volume, skip, steer radio; host also monitors history, blocklist, diagnostics. Constraints: AngularJS 1.x, no build step, no Bootstrap, self-hosted fonts, four themes with replaceable art under `static/art/<theme>/`.

Chosen direction: Warm Consumer App (challenger, picked on the decision page from hand 2), built code-led from the picked sketch `.impeccable/mocks/decision/challenger-warm.html`.

## Direction contract

THESIS: A friendly, soft-card jukebox where the one bright colour is always something you can press, and the guy is framed as the star of the main card. It refuses the streaming-app shell (left nav, bottom player bar) and the dark single-neon "music app" look.

OWN-WORLD: Warm tinted ground (plum-charcoal in Listening Room, warm paper in Daylight, violet-black in Neon Club, night-blue pixel in Arcade), large-radius cards one step lighter, one saturated action colour per theme (coral by default) used only on actionable things, rounded humanist sans (Nunito), plain-language labels, spring press feedback. Album-art hue tints the ground glow and scene lighting within the theme's range.

STORY: A guest sees what's playing and who chose it, nudges the volume, types a song into "Add a song" and taps a result, and sees it land in Up next. The host flips to Radio or History in the same card, and finds themes and diagnostics behind the header settings button, which opens Settings in the list card with a back arrow.

FIRST VIEWPORT: Desktop 1440x900: slim header (face mark + NETJammer wordmark left, radio status + settings right). Left, a tall Stage card (about 42% width): the guy's scene framed large at top with album art inset, then title, artist with its origin chip beside it (never as an eyebrow above the title, which the craft floor bans), seek bar, prev / big play / skip, and radio actions. Right, top row: "Add a song" card (search input, primary action) beside a Volume card (giant number + fader). Below, one wide card with tabs Up next / Radio / History, showing the queue. Phones stack the same cards in priority order.

FORM: Warm consumer app surface, dealt challenger in re-roll 1, chosen over the assigned direction. seed:2f03d104a34d391f (re-roll 1). Signature move: the guy's stage, notes float off the scene while music plays and stop on pause.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Unresolved

- Final art for all four themes arrives later from the host (`docs/art-prompts.md`); Neon Club uses a CSS treatment of the Listening Room scene and Arcade a code-drawn pixel scene until then.
