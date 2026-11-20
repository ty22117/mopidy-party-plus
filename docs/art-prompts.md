# Art prompts (free image tools)

Use the **Gemini app** (gemini.google.com) or **ChatGPT's free tier**. Both can restyle an image you upload. Upload `mopidy_party_plus/static/art/listening-room/scene.png` (or `art/daylight/scene.png` for Daylight) with each prompt, so the guy still looks like you.

Save each result into `mopidy_party_plus/static/art/<theme>/scene.png`. Aim for a **wide 16:9 image at least 1920 px wide**. Keep the guy on the **right third**: the app crops the scene into the Now Playing card and keeps the right side in view. See `mopidy_party_plus/static/art/README.md` for every file the app looks for.

**Lines to add to every prompt** (paste these on the end):
> Keep the character recognizably the same person: same swept-up brown hair, same round glasses, same big handlebar mustache, same face shape. No text, no logos, no UI, no watermark. Wide 16:9 composition, character on the right third, calm open space on the left.

## Listening Room (default, dark)
> Redraw this illustration as a polished, cozy late-night listening room. Same cartoon style but cleaner linework and richer lighting: deep charcoal and indigo shadows, warm lamp glow, softly glowing cyan and blue music notes, a glowing laptop, headphones and a small synth keyboard floating near him. He can wear something stylish (e.g. a dark overshirt or cardigan).

## Daylight (light)
> Redraw this illustration as the same cozy listening room in soft daylight: cream and pale sage background, pastel greens, lilac and peach accents, gentle shadows, light airy feel. Same character, same music props, same composition.

## Neon Club
> Redraw this character as glowing neon line art on a near-black background, synthwave style: hot pink, electric cyan and violet neon tubes, light bloom, a retro grid floor and neon music notes. Simple bold line drawing, like a neon sign of this man. The hair, round glasses and handlebar mustache must be clearly readable in the neon lines.

## Arcade (pixel art)
> Redraw this character and scene as 16-bit pixel art, like a retro game title screen: limited palette, crisp pixels, no anti-aliasing, pixel music notes, a pixel boombox or arcade cabinet, a starry pixel sky. The character's swept-up hair, round glasses and handlebar mustache must be clearly visible even at pixel scale.

## Face mark (favicon / logo)
> From this illustration, make a simple, bold icon of just this man's face: swept-up hair, round glasses, handlebar mustache. Flat colors, thick outline, readable at 32×32 pixels, centered on a plain transparent or solid background, square.

**Optional:** a transparent cut-out of just the guy (`guy.png`) for each theme lets the site animate him separately from the background. Ask the tool for "the same character only, full body, on a transparent background."
