---
name: NETJammer
description: A warm, soft-card party jukebox where the host's cartoon self holds the stage and the one bright colour is always something you can press.
colors:
  # Listening Room (default, dark). Unprefixed keys are the default theme.
  ground: "#211a2a"
  card: "#2d2537"
  card-2: "#392f45"
  card-3: "#483c56"
  text: "#fff6ee"
  text-2: "#d0c3d6"
  text-3: "#a99bb2"
  action: "#ff7a59"
  action-ink: "#2a110b"
  action-text: "#ff9c80"
  user: "#ffc574"
  radio: "#8fd0ff"
  ok: "#86e3a8"
  danger: "#ff7b7b"
  scene-bg: "#1b1622"
  # Daylight (light)
  daylight-ground: "#fbf1e4"
  daylight-card: "#ffffff"
  daylight-card-2: "#f6ece0"
  daylight-card-3: "#ecdfcf"
  daylight-text: "#2b241f"
  daylight-text-2: "#62564e"
  daylight-text-3: "#7a6c62"
  daylight-action: "#ff6a3d"
  daylight-action-ink: "#2a1208"
  daylight-action-text: "#b6401b"
  daylight-user: "#9a6418"
  daylight-radio: "#276d9f"
  daylight-ok: "#2a7d4c"
  daylight-danger: "#c0392b"
  # Neon Club (dark, saturated)
  neon-ground: "#0b0614"
  neon-card: "#160e25"
  neon-card-2: "#221636"
  neon-card-3: "#301f4a"
  neon-text: "#fff2fb"
  neon-text-2: "#d6c2ea"
  neon-text-3: "#ad97c8"
  neon-action: "#ff3d9a"
  neon-action-ink: "#1b0010"
  neon-action-text: "#ff7ec0"
  neon-user: "#ffd84d"
  neon-radio: "#2ee6ff"
  neon-ok: "#5cffb0"
  neon-danger: "#ff6b8b"
  # Arcade (dark, pixel)
  arcade-ground: "#120d33"
  arcade-card: "#1e1752"
  arcade-card-2: "#2a2170"
  arcade-card-3: "#3a2f8c"
  arcade-outline: "#0b0826"
  arcade-text: "#f4f1ff"
  arcade-text-2: "#cbc5f2"
  arcade-text-3: "#aaa2e4"
  arcade-action: "#ffcc33"
  arcade-action-ink: "#1a1033"
  arcade-action-text: "#ffd75e"
  arcade-action-shade: "#8a5a00"
  arcade-user: "#ff9ad5"
  arcade-radio: "#4be3ac"
  arcade-danger: "#ff6b6b"
typography:
  display:
    fontFamily: "Nunito, ui-rounded, Segoe UI, system-ui, sans-serif"
    fontSize: "clamp(28px, 2.5vw, 42px)"
    fontWeight: 900
    lineHeight: 1.06
    letterSpacing: "-0.018em"
  numeral:
    fontFamily: "Nunito, ui-rounded, Segoe UI, system-ui, sans-serif"
    fontSize: "54px"
    fontWeight: 900
    lineHeight: 0.9
    letterSpacing: "-0.03em"
    fontFeature: "tnum"
  wordmark:
    fontFamily: "Nunito, ui-rounded, Segoe UI, system-ui, sans-serif"
    fontSize: "27px"
    fontWeight: 900
    lineHeight: 1
    letterSpacing: "-0.025em"
  headline:
    fontFamily: "Nunito, ui-rounded, Segoe UI, system-ui, sans-serif"
    fontSize: "19px"
    fontWeight: 800
    lineHeight: 1.2
    letterSpacing: "-0.005em"
  title:
    fontFamily: "Nunito, ui-rounded, Segoe UI, system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 900
    lineHeight: 1.25
  row-title:
    fontFamily: "Nunito, ui-rounded, Segoe UI, system-ui, sans-serif"
    fontSize: "16.5px"
    fontWeight: 800
  body:
    fontFamily: "Nunito, ui-rounded, Segoe UI, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 600
    lineHeight: 1.45
  label:
    fontFamily: "Nunito, ui-rounded, Segoe UI, system-ui, sans-serif"
    fontSize: "14.5px"
    fontWeight: 800
  meta:
    fontFamily: "Nunito, ui-rounded, Segoe UI, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 700
    fontFeature: "tnum"
  arcade-body:
    fontFamily: "Pixelify Sans, ui-monospace, monospace"
    fontSize: "17px"
    fontWeight: 500
    lineHeight: 1.45
  arcade-display:
    fontFamily: "Pixelify Sans, ui-monospace, monospace"
    fontSize: "clamp(28px, 2.5vw, 42px)"
    fontWeight: 700
    lineHeight: 1.06
    letterSpacing: "0em"
  neon-wordmark:
    fontFamily: "Monoton, Nunito, sans-serif"
    fontSize: "25px"
    fontWeight: 400
    lineHeight: 1
    letterSpacing: "0.02em"
rounded:
  card: "30px"
  inner: "20px"
  row: "16px"
  cover: "18px"
  ctl: "999px"
  arcade: "0px"
spacing:
  gap: "20px"
  gap-phone: "14px"
  card-pad: "22px 24px"
  stage-pad: "12px"
  row-pad: "8px 10px"
  app-pad: "18px 28px 26px"
components:
  button-action:
    backgroundColor: "{colors.action}"
    textColor: "{colors.action-ink}"
    rounded: "{rounded.ctl}"
    padding: "0 22px"
    height: "46px"
    typography: "{typography.label}"
  button-quiet:
    backgroundColor: "{colors.card-2}"
    textColor: "{colors.text}"
    rounded: "{rounded.ctl}"
    padding: "0 22px"
    height: "46px"
  button-quiet-hover:
    backgroundColor: "{colors.card-3}"
  button-sm:
    rounded: "{rounded.ctl}"
    padding: "0 14px"
    height: "36px"
  control-play:
    backgroundColor: "{colors.action}"
    textColor: "{colors.action-ink}"
    rounded: "{rounded.ctl}"
    size: "86px"
  control-secondary:
    backgroundColor: "{colors.card-2}"
    textColor: "{colors.text}"
    rounded: "{rounded.ctl}"
    size: "58px"
  add-button:
    backgroundColor: "{colors.action}"
    textColor: "{colors.action-ink}"
    rounded: "{rounded.ctl}"
    size: "44px"
  chip:
    backgroundColor: "{colors.card-2}"
    textColor: "{colors.text}"
    rounded: "{rounded.ctl}"
    padding: "0 15px"
    height: "38px"
    typography: "{typography.label}"
  chip-hover:
    backgroundColor: "{colors.card-3}"
  tag-origin:
    backgroundColor: "{colors.card-2}"
    textColor: "{colors.text}"
    rounded: "{rounded.ctl}"
    padding: "0 11px 0 9px"
    height: "26px"
  search-field:
    backgroundColor: "{colors.card-2}"
    textColor: "{colors.text}"
    rounded: "{rounded.ctl}"
    padding: "6px 6px 6px 20px"
    height: "46px"
  search-field-focus:
    backgroundColor: "{colors.card}"
  tabs:
    backgroundColor: "{colors.card-2}"
    rounded: "{rounded.ctl}"
    padding: "4px"
  tab-on:
    backgroundColor: "{colors.card}"
    textColor: "{colors.text}"
    rounded: "{rounded.ctl}"
    height: "40px"
    padding: "0 16px"
  card:
    backgroundColor: "{colors.card}"
    textColor: "{colors.text}"
    rounded: "{rounded.card}"
    padding: "22px 24px"
  list-row:
    rounded: "{rounded.row}"
    padding: "8px 10px"
    height: "62px"
  icon-button:
    textColor: "{colors.text-2}"
    rounded: "{rounded.ctl}"
    size: "38px"
---

# Design System: NETJammer

## Overview

**Creative North Star: "The Host's Jukebox"**

NETJammer is a friendly, soft-card jukebox for a room of friends sharing one set of speakers. The host's cartoon self (swept-up hair, round glasses, handlebar mustache) is framed as the star of the main card, and everything around him is calm, warm and pressable. The system is built from one stylesheet and four themes (Listening Room, Daylight, Neon Club, Arcade) selected by `data-theme` on the root; every theme defines the same token names and every component reads only tokens, so a theme is a different art style and material, never a different layout.

Density is relaxed: big rounded cards on a warm tinted ground, generous 20px gutters, large tap targets (46px controls, an 86px play button), plain-language labels in sentence case. The one saturated colour in each theme belongs to things you can press, and the current song's album art gently re-hues the ground glow and scene lighting within the theme's range. Motion is springy and brief on press, slow and ambient on the stage: notes drift off the scene while music plays and stop the moment it pauses.

The world deliberately refuses the streaming-app shell (left navigation rail, persistent bottom player bar): the stage card is the player, and the list card switches between Up next, Radio and History in place.

**Key Characteristics:**
- Warm tinted ground per theme with a soft radial glow driven by `--tint-hue`.
- Cards one step lighter than the ground; inset controls one or two steps lighter again (card-2, card-3).
- One saturated action colour per theme, reserved for pressable things and their on-states.
- One rounded humanist family (Nunito) at heavy weights; Arcade swaps in Pixelify Sans, Neon Club's wordmark uses Monoton.
- Pill controls and 30px cards; Arcade sets every radius to zero.
- Spring press feedback (scale .94) on every button-like control.
- Replaceable per-theme art under `static/art/<theme>/`, with code-drawn fallbacks.

## Colors

Each theme is a warm or night-tinted neutral ladder (ground, card, card-2, card-3, three text steps) plus one loud action colour and two semantic origin hues. The frontmatter lists Listening Room unprefixed and the other themes with `daylight-`, `neon-` and `arcade-` prefixes; the token names in code are identical across themes.

### Primary
- **Ember Coral** (action, Listening Room): fills the play button, the Search button, add buttons, the radio switch when on, seek and volume fills, the active-theme ring, and the NET chip of the wordmark. Ink on it is the near-black **Coal Ink** (action-ink).
- **Daylight Tangerine** (daylight-action): the same role on paper; because it is too light for text on white, link and on-state text uses the deeper **Burnt Orange** (daylight-action-text).
- **Hot Magenta** (neon-action): the same role in Neon Club, always paired with a glow ring.
- **Coin Yellow** (arcade-action): the same role in Arcade, with **Coin Shade** (arcade-action-shade) as its hard pixel drop.
- **Action Text** (action-text per theme): the readable tint of the action colour used for links, focus outlines, on-state icons and the caret.

### Secondary
- **Requested Amber** (user; Daylight Ochre, Neon Gold, Arcade Bubblegum): marks a song a guest requested. Appears as a solid dot.
- **Radio Sky** (radio; Daylight Harbor Blue, Neon Cyan, Arcade Mint): marks a song Radio picked, the station pins and the "radio thinking" ripples. Appears as a dashed ring.

### Tertiary
- **Mint OK** (ok) and **Soft Red** (danger): confirmation (added-already state, toast success badge) and destructive actions. Warn reuses the user hue in Listening Room, Daylight and Neon Club, and the action yellow in Arcade.

### Neutral
- **Plum Charcoal** (ground), **Plum Card** (card), **Raised Plum** (card-2), **Lifted Plum** (card-3): Listening Room's ladder. Ground is the page, card is every surface, card-2 is inset controls (search pill, tabs track, chips, quiet buttons), card-3 is hover and track backgrounds.
- **Warm Paper** (daylight-ground) under pure white cards with sand insets in Daylight; **Violet Black** in Neon Club; **Night Blue** in Arcade, outlined in **Pixel Outline** (arcade-outline).
- **Cream** (text), **Lilac Grey** (text-2), **Dusk Grey** (text-3): primary text, secondary text (artists, row sub-lines), and tertiary meta (times, hints, counts).
- **Scene Ground** (scene-bg): the colour behind the art before it loads.

### Named Rules
**The One Bright Thing Rule.** The action colour appears only on things you can press and on their on-states (switch on, chip on at 20% mix, active theme ring, radio state dot). Never use it for decoration, headings, or status that cannot be acted on.

**The Shape-First Origin Rule.** Requested is a solid dot, Radio is a dashed ring, the current Radio seed is a solid ring with a soft halo. Colour reinforces the shape; it never carries the meaning alone.

**The Tint Within Range Rule.** The album-art hue (`--tint-hue`, animated over 1.6s) reaches only alpha-limited glows: the two ground radials, the scene light, and the row-arrival flash. Text, cards and the action colour never take the tint, so contrast never depends on the cover art.

## Typography

**Display Font:** Nunito variable, self-hosted (with ui-rounded, Segoe UI, system-ui)
**Body Font:** Nunito (same family)
**Arcade Font:** Pixelify Sans, self-hosted (with ui-monospace)
**Neon Club Wordmark:** Monoton, self-hosted

**Character:** One rounded humanist family at heavy weights (600 body, 800 labels, 900 titles) reads friendly and confident across the room. Arcade replaces the whole family with a pixel face rather than mixing; Monoton appears only as Neon Club's glowing wordmark.

### Hierarchy
- **Display** (900, clamp 28 to 42px, 1.06, balanced, two-line clamp): the now-playing title only. Arcade drops to 700 with no tracking.
- **Numeral** (900, 54px, 0.9, tabular): the volume readout, with a 22px tertiary percent sign.
- **Wordmark** (900, 27px): "NET" as a tilted action-colour chip at .72em, "Jammer" over a mustache stroke drawn in the action colour.
- **Headline** (800, 19px, 1.2): card headings such as "Add a song" and "Volume"; 22px/900 inside the Radio hero.
- **Title** (900, 17px, 1.25): block headings inside the list card and empty states (20px there).
- **Row title** (800, 16.5px, single line, ellipsis): song names in lists.
- **Body** (600, 16px, 1.45): base text; Arcade runs 17px/500. Prose blocks cap at 40 to 52ch.
- **Label** (800, 14.5px): buttons-small, chips, pins, hints at 600.
- **Meta** (700 to 900, 13 to 14px, tabular): times, counts, row numbers, source names.

### Named Rules
**The One Family Rule.** Each theme speaks in exactly one UI family. Never pair a second display face with Nunito; Arcade changes the whole family, Neon Club changes only the wordmark.

**The Plain Label Rule.** Labels are sentence-case plain language ("Add a song", "Up next", "Kept off Radio"). No kickers or eyebrows above titles: a song's origin sits as a tag beside the artist, never above the title. Small uppercase text is limited to group labels inside a list block (800, 13px, .06em tracking).

## Layout

A full-height grid at desktop (max 1760px, padding 18/28/26px, 20px gap): a slim header across the top; the Stage card on the left (1.3fr) spanning two rows; "Add a song" (1fr) and Volume (.82fr) side by side top-right; the list card below them filling the remaining height and scrolling internally, its body fading out over the last 34px with a mask.

- **At 1240px and below** the right column stacks Add, Volume and the list card beside the Stage.
- **Below 900px (phones)** the grid becomes one column in priority order: Stage, Volume, Add, list. The scene goes 4:3, the list scrolls with the page (no mask), and a fixed pill dock at the bottom carries the add and list shortcuts; toasts lift above it.
- **Short laptops (height 800px and below)** shrink the scene to 120px minimum so every control stays on screen. From 741 to 800px tall only the scene gives up height (play 80px, prev/skip 56px); at 740px and below the transport also tightens (play 64px, prev/skip 48px). Below 600px the page scrolls. The scene, never a control, absorbs the difference.
- **The list card is a container**: below 620px tab labels collapse to icons; below 520px durations and source names hide and history actions wrap.
- **Hover vs touch**: with a mouse, queue row actions float over the row's right end on hover or focus; on touch, each row gets one "more" button that opens its actions on a second line.

Spacing rhythm is loose and soft: 20px between cards, 22/24px inside cards, 12px inside the Stage, 8/10px in rows with 2px between rows, 8 to 12px between controls.

## Elevation & Depth

Depth is tonal first: cards are one step lighter than the ground, insets one step lighter again. A single card shadow per theme sits underneath, and each theme expresses it in its own material: a long soft plum drop in Listening Room, a hairline plus soft warm drop in Daylight, a faint cyan ring with a magenta under-glow in Neon Club, and a hard 6px pixel drop in Arcade. Action controls carry a coloured glow (`--action-glow`) that makes the bright thing feel lit.

### Shadow Vocabulary
- **Card** (`--shadow-card`, per theme; see sidecar): every card, the header radio switch and the settings button.
- **Action glow** (`--action-glow`, per theme): play, add, primary buttons and the switch when on.
- **Cover lift** (`0 0 0 4px var(--card), 0 16px 34px -10px rgba(0,0,0,.65)`): the album-art inset, ringed in the card colour so it reads as set into the scene.
- **Tab / segment lift** (`0 3px 10px -4px rgba(0,0,0,.4)`): the selected tab or segment rising out of its track.
- **Drag lift** (`0 14px 30px -12px rgba(0,0,0,.55)`): a queue row being dragged.

### Named Rules
**The One Step Lighter Rule.** Never stack a surface darker than what it sits on. Ground, card, card-2, card-3 is the only order.

**The Material Shadow Rule.** Shadows follow the theme's material: soft in Listening Room and Daylight, glow in Neon Club, hard offset only in Arcade, where a solid pixel drop is the native sprite depth. Hard offset shadows never appear in the other three themes.

## Shapes

Generously rounded: 30px cards, 20px inner panels (scene, Radio hero, theme cards), 16px rows, 18px album cover, and full pills for every control, field, tab, chip, tag, switch and toast. Faces in the header, empty states and toasts sit in circles. Arcade sets all four radius tokens to zero, squares the dots and faces, and swaps focus outlines to dashed, so the same components read as pixel blocks.

**The Same Tokens, Different Corners Rule.** Components read `--r-card`, `--r-inner`, `--r-row` and `--r-ctl`; never hard-code a radius, or Arcade breaks.

## Components

Every button-like control shares one spring press: `transform: scale(.94)` on `:active` with `cubic-bezier(.3, 1.3, .6, 1)` over .25s. In Arcade, primary and play controls instead sink 3px onto their shade. Focus is a 3px outline in action-text with 3px offset.

### Buttons
- **Shape:** full pill (999px), 46px tall; small variant 36px.
- **Action:** action fill, action-ink text, 800 weight, action glow; hover brightens 6%. Used for Search, empty-state next steps.
- **Quiet:** card-2 fill, text colour; hover card-3. Used for Clear and secondary actions.
- **Danger:** danger fill with near-black ink, for confirming destructive actions only.
- **Link:** action-text, 800, 15px, underline (2px, 4px offset) on hover; "Browse the library", "Add a playlist link".
- **Icon button:** 38px pill, text-2, hover card-3; on-state takes action-text; the 46px header variant sits on a card with the card shadow.

### Transport (signature)
- **Play/pause:** 86px circle (80px at 741–800px tall, 64px at 740px and below, 76px on phones), action fill, action glow, 30px icon.
- **Previous / skip:** 58px card-2 circles; disabled controls go card-2 with text-3 at .7 opacity.

### Chips and tags
- **Chip:** 38px pill, card-2, 800/14.5px with a text-3 icon; hover card-3. **On** mixes 20% action into card-2 and lifts the icon to action-text; **warn** mixes 18% warn. Used for "More like this", thumbs, "Block from Radio".
- **Origin tag:** 26px pill, card-2, 13px/800, with the origin mark. Sits beside the artist.
- **Pin:** 38px pill tinted 16% radio, with a 30px round remove button.
- **Count:** 22px card-3 pill, 900 tabular.

### Cards / Containers
- **Corner Style:** 30px (zero in Arcade).
- **Background:** card, with the theme's card border (hairline in Listening Room and Daylight, magenta hairline in Neon Club, 3px pixel outline in Arcade).
- **Shadow Strategy:** the theme's card shadow; see Elevation.
- **Internal Padding:** 22/24px; Stage 12px around the scene.

### Inputs / Fields
- **Style:** card-2 pill with a 2px transparent border, 46px input at 18px/700, text-3 placeholder; the Search action button sits inside the pill.
- **Focus:** the border turns action and the fill rises to card; the caret is action.
- **Disabled:** .55 opacity.

### Sliders
- **Seek:** 8px pill track, action fill to the played point over card-3, 22px thumb in `--thumb`.
- **Volume:** 14px track, 30px thumb, flanked by 42px minus and plus circles. Thumb scales 1.12 on hover; focus rings the thumb in action-text.

### Navigation
- **Tabs:** a card-2 pill track with 4px padding holding 40px pill tabs (800, text-2). The selected tab becomes a card pill with the tab lift. Each tab carries a count pill or the radio state dot (action when Radio is on).
- **Header:** face mark and wordmark left; radio switch and a settings gear right. Settings opens inside the list card with a back arrow, not as a tab.
- **Radio switch:** a pill on the card with a broadcast icon, label and a 46x28 track; on, the track fills action with action glow and the white knob springs 18px. A 64x38 large variant lives in the Radio hero.

### List rows
- 62px minimum, 16px radius, 12px gaps: drag handle, tabular number, title over a sub-line (origin mark plus artist), duration, actions. Hover mixes card-2 at 70%. A newly arrived row flashes the tinted arrive colour and settles from -6px over 2.4s. Blocked history rows strike through in text-3; the seed row tints 9% radio.

### Stage scene (signature)
The guy's scene fills the top of the Stage card at 20px radius, cropped to keep the right third (where he stands) in view, with a tinted radial light blended over it (screen in dark themes, soft-light in Daylight, none in Arcade). The album cover is inset bottom-left, ringed in the card colour. Notes in three per-theme colours float up off the scene on a 7s loop while music plays and stop on pause; Arcade uses pixel notes that move in 10 steps; an optional `guy.png` cut-out bobs 6px. Neon Club without its own art re-lights the Listening Room scene and adds a perspective grid floor; Arcade without art draws a pixel scene in code.

### Empty states and toasts
- **Empty state:** the guy's face in a 96px card-2 circle with an optional badge or radio ripples, a 20px title, one line of text-2 (max 40ch), and one action button.
- **Toast:** a pill that springs up from the bottom (.5s), with the face in a 40px circle and an ok/danger badge, in the theme's toast colours.

## Do's and Don'ts

### Do:
- **Do** read every colour, radius and shadow from the theme tokens so all four themes keep working; add a new token to all four theme blocks at once.
- **Do** reserve the action colour for pressable things and their on-states (The One Bright Thing Rule).
- **Do** mark origin by shape first: solid dot for Requested, dashed ring for Radio, ring with halo for the seed.
- **Do** keep album-art tint inside alpha-limited glows; never let it reach text or the action colour.
- **Do** give every button-like control the spring press (scale .94, .25s spring) and a 3px action-text focus outline.
- **Do** stop the notes and the guy's bob when paused, and remove notes and shorten all motion under `prefers-reduced-motion`.
- **Do** use the guy's face for empty, loading and toast states, and keep his hair, round glasses and mustache in any new art.
- **Do** self-host every font and asset under `static/`.

### Don't:
- **Don't** add a left navigation rail or a persistent bottom player bar; the Stage card is the player.
- **Don't** put kickers or eyebrows above titles; origin and status sit beside or below.
- **Don't** use hard offset shadows outside Arcade.
- **Don't** hard-code a radius; Arcade depends on the radius tokens going to zero.
- **Don't** add a second display face beside Nunito, or mix Pixelify Sans into non-Arcade themes.
- **Don't** stack a surface darker than the one beneath it.
