# Lazy Mixtape Maker 6.1 — The Whole Milk Update

## What's new

### MilkDrop visuals
The classic Winamp visualizer is now a second kind of visual, next to Shadertoy. It's drawn by **projectM**, the open-source MilkDrop engine, built into every download. It works offline on Windows, macOS and Linux (Steam Deck included).
- **60 featured presets** in the library from the start: six hand-picked from each of the ten categories (Dancer, Drawing, Fractal, Geometric, Hypnotic, Particles, Reaction, Sparkle, Supernova and Waveform).
- **The full Cream of the Crop pack** (9,795 presets) plus the MilkDrop texture pack, in a new **MilkDrop browser** (**Add MilkDrop…** in the Shader library and the Visuals tab). Browse by category, search names and authors, watch presets live, and add as many as you like.
- **Import your own `.milk` files.** Any MilkDrop 1 or 2 preset works, and picture files it uses that sit next to it come along. Pasting a preset's text into *Add from Shadertoy…* works too.
- MilkDrop presets work everywhere visuals do: the app's own picks, per-song choices, one visual for the whole video, and the Visualization Studio. They react to your music, with every exported frame drawn from the exact audio at that moment.
- **Kept apart from Shadertoy:** a new **The app picks from** setting (Shadertoy and MilkDrop / Shadertoy only / MilkDrop only) for "Let the app choose" and "Random". The Shader library can also show one kind at a time. MilkDrop presets are marked **◈ MilkDrop** in every list.
- **View/Edit Preset** to rename and edit your own presets. **Export…** saves a `.milk`. Your presets and their pictures travel in saved sessions and backups.

### Faster previews
- A new **Preview** choice next to the time above the timeline decides what Play renders:
  - **1 transition (2 songs):** just the blend nearest the playhead, with about 10 seconds either side. Ready in a few seconds, so you can tweak a transition and hear it right away.
  - **4 songs:** the four songs around that blend, for hearing how a run of songs flows.
  - **Whole mix:** everything, as before.
- Short previews sound exactly like that part of the finished mix, and the playhead moves along the mix's own timeline while they play. The app remembers your choice.

### Easier-to-see, easier-to-move timeline markers
- **Transitions** are now coloured zones (blue bass swap, green crossfade, orange cut with an effect, red hard cut, purple stem transitions). They have solid edges and a coloured bar across both songs. Each one has a **badge** above the songs showing its kind and length in beats.
- **Drag a badge** left or right to make the blend longer or shorter. Hard cuts get a badge too, and dragging one longer turns it into a blend. **Click a badge** to open that transition in the Transition tab.
- **Effects** are bigger, labelled markers (with a short code such as ECH or FLT when space is tight). A line shows exactly where each one starts in the song, and they're never too small to grab. Clicks that land just next to one still pick it up.
- **Drag an effect's right end** to make it longer or shorter.
- **Arrow keys** nudge the selected effect by a quarter beat (Shift: a whole beat).
- Hovering lights a marker up and shows its details. While dragging, a readout next to the pointer shows the new value in beats and seconds.

### Steam Deck and small screens
- Maximising the window on a small screen (Steam Deck, 1280×800) no longer piles controls on top of each other in the Visuals, Shader library and other panels. Panels short on room now scroll, the shader and MilkDrop previews shrink to fit, and the window fits the Deck's screen even with large text.

## Credits
- projectM / libprojectM (LGPL-2.1): https://github.com/projectM-visualizer/projectm
- Cream of the Crop preset pack, compiled by Jason Fletcher (ISOSCELES). Each preset belongs to its author, named in its file name.
- MilkDrop texture pack: https://github.com/projectM-visualizer/presets-milkdrop-texture-pack
- MilkDrop by Ryan Geiss / Nullsoft.

## Downloads
- **Windows, macOS, Linux:** the standard app.
- **-Stems** versions: the same, plus the stem engine (stem transitions, Mashup Studio, deep analysis) built in.
