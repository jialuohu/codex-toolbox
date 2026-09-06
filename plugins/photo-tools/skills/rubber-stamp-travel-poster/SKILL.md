---
name: rubber-stamp-travel-poster
description: "Create a separate 4:3 rubber stamp travel journal poster from each supplied photo, pairing the original photograph with a small handmade stamp on aged paper. Use for this photo-poster style."
---

# Rubber Stamp Travel Poster

Turn each supplied photograph into one independent, quiet, tactile travel journal
poster. The photograph documents the real place; a handmade rubber stamp records
its most recognizable visual memory. Apply the following defaults unless the
user explicitly changes them.

## Inputs and execution

1. Identify the source photos in the requested batch and keep their order. Ask
   for photos if none are available. Never substitute an invented photograph.
2. Inspect every source image; use `view_image` for local files before editing.
   Note the distinctive silhouette, spatial relationships, foreground
   obstructions, natural light, and two to four characteristic colors.
3. Resolve the exact English caption before generation:
   - Use the user's location name or a reliably identified landmark. If the
     place is uncertain, use a conservative descriptive scene label such as
     `Coastal Cliffs`, rather than inventing a city, country, or landmark.
   - Use the user's number, or a sequential journal entry number such as
     `No. 001`, `No. 002`, in source order. This is an entry number, not a
     claimed historical or official identifier.
   - Choose exactly three short English keywords grounded in the visible scene.
   - Use a supplied or verified capture year in the Gregorian calendar. If
     unavailable, use the verified current year labeled `Journal year`; never
     treat the file modification time or scenery as evidence of a capture date.
4. Use the built-in `image_gen` tool as an image edit, with one call per source
   photo and one separate poster per call. Follow the installed `imagegen`
   skill when available. Supply the selected photo as the edit target, not
   merely a loose style reference. With local paths, pass only that source in
   `referenced_image_paths`. Otherwise use the tool's recent-image mechanism,
   identifying the selected target explicitly and excluding other photos from
   the composition. Never combine the two reference mechanisms.
5. Include the complete visual contract below and the exact quoted caption in
   each edit prompt. Tailor the stamp's subject and palette to that photo; do
   not carry a previous photo's landmarks or colors into the next poster.

Use the built-in tool for ordinary batches as well as single photos. Do not
silently switch to an API, paid third-party service, Python compositing, or an
SVG/HTML substitute. If image editing is unavailable, state the limitation and
retain the prepared prompt; an alternative execution route needs the user's
choice. Creating this skill or preparing a prompt alone does not call for
generating sample images.

## Visual contract

### Canvas and original photograph

- Strict **4:3 landscape**, naturally divided into approximately equal
  side-by-side sections: **50% photograph on the left, 50% paper on the right**.
  Blend the materials into one balanced editorial layout without an obvious
  central dividing line, border, or decorative separator.
- Faithfully preserve the photograph's main subjects, terrain, architecture,
  plants, people, spatial relationships, natural lighting and shadows,
  realistic textures, and original color atmosphere.
- Allow natural cropping to fit, restrained art-publication color grading, and
  extremely subtle fine film grain. Never stretch, distort, move, replace,
  redraw, modify, or creatively reconstruct subjects. Keep scene simplification
  confined to the stamp; do not remove crowds or vehicles from the photograph.
- Produce one poster for each photo. No collages, multi-photo compositions,
  contact sheets, or photo grids.

### Paper and stamp scale

- Warm off-white aged paper with fine fibers, natural texture, subtle signs of
  use, and a matte tactile surface. Leave abundant unprinted negative space.
- Place a small multicolor rubber stamp in the middle-to-lower area of the
  right section. Its height should be approximately **30%–38% of the right
  section's height**, with generous empty space around it.
- Keep the stamp a compact visual memory of the source. Do not enlarge it into
  a complete landscape illustration, conventional artwork, or brand logo.

### Extract the recognizable scene

Keep the minimum visual information needed to recognize the subject and scene
relationships: distinctive silhouettes, structures, terrain contours, plant
forms, roads, or coastlines. Simplify crowds, vehicles, dense windows, repetitive
buildings, fragmented vegetation, decorative details, and irrelevant background
elements out of the stamp. Never apply this removal to the left photograph.

Choose the relevant treatment for the source:

| Scene | Keep in the stamp |
| --- | --- |
| Iconic architecture | Distinctive exterior silhouette, roof, dome, arch, tower, or primary structure |
| Mountain settlement | Several terraced building color blocks following the terrain |
| Coast | Mountain contours, sediment layers, coastline, and sparse intermittent water patterns |
| City panorama | Main skyline, one iconic building when present, and one or two distant mountain layers when visible |
| Natural landscape | Dominant mountain forms, trees, coastline, or road direction |
| Important foreground obstruction | Its silhouette as a foreground stamp element, preserving its relation to the background |

Use only features present in the source; do not invent mountains, icons, or
landmarks to complete a scene category.

### Colors and physical print texture

Extract **2–4 key colors** from the photo. Prefer subdued carbon black, deep
green, brick red, ochre yellow, slate blue, or gray-brown when appropriate, but
never force a fixed palette. Retain the source's recognizable color character
and reserve small color areas for emphasis.

Render each color as a hand-stamped layer: engraved rubber texture, hand-carved
marks, uneven line weights, broken contours, edge gaps, dry-ink shortages,
paper bleed-through, granular ink, uneven pressure, partial ghosting, and subtle
registration misalignment with the visual feel of **1–2 mm** at poster scale.
Allow natural misregistration between color layers. Do not digitally smooth
the edges. The result should resemble an engraved rubber stamp physically
pressed onto aged paper, rather than a photo filter, smooth vector illustration,
or line-art logo.

### Typography and mood

Place the resolved location or scene label, number, three keywords, and year
below or beside the stamp in its surrounding negative space. Use small,
restrained typewriter lettering with slightly imperfect mechanical character.
Require correct spelling and verbatim caption rendering. Keep the text like
field notes, architectural documentation, or a natural observation record,
with no advertising headline, unrelated slogan, brand name, or decorative copy.

Aim for an architect's, travel writer's, or nature observer's journal: quiet,
restrained, tactile, authentic, location-specific, slightly imperfect, and
collectible.

Avoid circular stamps, Chinese-red postage stamps, postage perforations, wax
seals, sticker collages, generic souvenir templates, generic city icons,
complete reproduction of every building, excessive density, childish handmade
styling, cartoons, 3D rendering, plastic textures, glossy digital gradients,
oversaturation, excessive text, and decorative clutter.

## Check and deliver

Inspect each result against its source before describing it as finished:

- Confirm a separate output for every source, with no cross-photo mixing.
- Verify actual image dimensions when accessible: `width * 3 == height * 4`.
  Request 4:3 explicitly in the prompt; do not assume the generator obeyed it.
- Compare the left photograph's subjects, geometry, relative positions,
  foreground, lighting, and atmosphere with the original, allowing only the
  permitted crop and restrained grading.
- Check the approximate half-width balance, absence of a central divider,
  stamp height and placement, negative space, limited palette, and ink texture.
- Read the caption and check spelling, three keywords, entry number, and the
  distinction between capture year and journal year.

Repair visible failures through a targeted edit that retains the original
photo as the fidelity reference and restates its invariants. Image editing can
alter source details; do not claim exact or pixel-identical preservation solely
because the prompt requested it. If fidelity, aspect ratio, or typography
remains incorrect or cannot be verified, say which requirement is unresolved.

Return each poster separately in source order using native inline images or
absolute image paths, never a combined preview grid. Keep source files intact.
For a requested destination, save distinct names such as
`travel-journal-001.png`; follow the image tool's save-path contract. Briefly
identify any descriptive location label or journal-year fallback used.
