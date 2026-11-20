# NETJammer redesign brief

Product facts live in `PRODUCT.md`. This file holds the **visual direction** the host decided on. Read both before starting.

## The ask

A complete design overhaul. The current UI feels like a Bootstrap template; it should feel **slick and cool**. Screens, menus, navigation and layout can all be redesigned from scratch. Ease of use and looks come first, and every existing feature must survive.

## Layout

- Design for **desktop and laptop first** (personal computers at normal distance), and keep it fully usable on phones.
- **The music controller is the center of the UI.** The guy is the visual hero, but the controls are the focus.
- The host worries the screen will feel bloated if everything sits on one page. Their instinct is a calm first screen showing Now Playing, volume, a way to search and a short look at what's next, with the full queue, radio, history and settings a click away. **This is a feeling, not a rule.** If you know a better design, go with it, and explain why.
- Priority: Now Playing → Volume → Search → Queue → Radio → History → Diagnostics.

## The guy

- He's the **hero** of the page, not wallpaper hidden behind cards. Place and frame him deliberately.
- **Always keep:** the swept-up hair, round glasses and big handlebar mustache. Everything else (clothes, pose, scene, style) is open.
- Use him around the app where it makes sense: a face mark for the favicon and logo, and poses for empty and loading states (empty queue, no results, radio thinking).
- Give him gentle motion while music plays (floating notes, bobbing headphones), and stop it when paused or with `prefers-reduced-motion`.

## Themes

There are four themes. Each one has its **own art style**, not just a recolor. A theme picker sits in the settings menu, and each browser remembers its own choice:

| Theme | Feel | Art |
|---|---|---|
| **Listening Room** (default) | Dark, cozy, late-night. The UI glows the way the notes and laptop glow in the art. | Polished version of the current illustration. |
| **Daylight** | The same cozy room in soft, light colors. | Light/pastel illustration. |
| **Neon Club** | Louder and saturated, for when the party is going. | The guy as glowing neon line art (synthwave). |
| **Arcade** | Playful, retro game. | The guy as pixel art in a pixel-art music scene. |

- **Colors and type are your call.** Make it look great. Nothing is inherited from the current design (BYU navy is gone).
- **Album-art tint:** gently tint the glow and accents (and the scene's lighting if possible) from the current song's album art, kept within each theme's colors so text always stays readable. Do it if it can be done well.
- Make the wordmark **NETJammer** (required) a real logo that adapts to each theme.

## Artwork pipeline (no image generation)

No image generator is available. Build the theme system so **each theme's art is a set of files the host can replace without touching code**:

```
mopidy_party_plus/static/art/<theme>/scene.png    full scene with the guy
mopidy_party_plus/static/art/<theme>/guy.png      optional transparent cut-out of the guy (for layering/motion)
mopidy_party_plus/static/art/face.png             face mark for favicon/logo
```

where `<theme>` is `listening-room`, `daylight`, `neon-club` or `arcade`.

- **Placeholders until new art arrives:** `listening-room` uses the current `background.png` and `daylight` uses `light.png`. Neon Club and Arcade can use the Listening Room scene with a CSS treatment.
- **Arcade can be drawn in code** (an SVG or canvas pixel grid) if no supplied art arrives. Pixel art is the one style that's realistic to draw by hand.
- The host is producing the new art with free image tools. The prompts are in `docs/art-prompts.md`.
