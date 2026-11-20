# NETJammer theme art

Drop files here to change the artwork. No code changes are needed: the page checks
for each file when a theme is chosen and falls back when it isn't there. After you
add or replace a file, `git pull` on the Pi and reload the page.

```
art/listening-room/scene.png   Listening Room (default, dark)
art/daylight/scene.png         Daylight (light)
art/neon-club/scene.png        Neon Club
art/arcade/scene.png           Arcade (pixel art)
art/<theme>/guy.png            optional cut-out of the guy (see below)
art/face.png                   face mark for the logo, empty states, toasts and favicon
```

**scene.png:** a wide 16:9 image, at least 1920 px wide, with the guy on the right
third. The app crops it into the Now Playing card and keeps the right side (the guy)
in view, so keep his head and mustache away from the very top and right edges.

**guy.png (optional):** a transparent cut-out of just the guy for that theme. When it
exists, the app layers it over `scene.png` and gives him a gentle bob while music
plays, so make that theme's `scene.png` the empty room.

**face.png:** square, transparent background, readable at 32 × 32 px. Until it exists
the app uses `face.svg`, a drawn placeholder.

## Fallbacks used today

- **Listening Room** and **Daylight** use the original illustrations (moved here from
  `static/background.png` and `static/light.png`).
- **Neon Club** has no art yet, so it borrows the Listening Room scene and re-lights it
  in neon with a glowing grid floor.
- **Arcade** has no art yet, so it draws a pixel-art scene in code (`art.js`): the guy
  with his swept-up hair, round glasses and handlebar mustache, a boombox, notes and a
  starry sky.

Prompts for making new art with free image tools are in `docs/art-prompts.md`.
