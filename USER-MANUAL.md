# Lazy Mixtape Maker: User Manual

Lazy Mixtape Maker turns a folder of your own songs into one seamless DJ-style mixtape. It works out each song's tempo, key and parts, puts the songs in a good order, matches their beats and keys, and blends them together. You can then fix anything you don't like, save your work, export the audio, and make a video with animated visuals.

Everything happens on your computer. Nothing is uploaded, and no internet connection is needed. (The only optional online feature is downloading a visual from a Shadertoy link.)

Works with **mp3, wav, flac and m4a** audio files, and with **video files** (mp4, mkv, mov, webm, avi, m4v), which are used for their sound and, in video exports, their picture.

---

## Contents

1. [Quick start](#1-quick-start)
2. [The main window](#2-the-main-window)
3. [Adding songs](#3-adding-songs)
4. [Generating a mix](#4-generating-a-mix)
5. [Playing the mix](#5-playing-the-mix)
6. [Editing the mix](#6-editing-the-mix)
7. [Effects](#7-effects)
8. [Saving, sharing and reopening](#8-saving-sharing-and-reopening)
9. [Exporting audio and the cue sheet](#9-exporting-audio-and-the-cue-sheet)
10. [Making a video](#10-making-a-video)
11. [Shader library: managing visuals](#11-shader-library-managing-visuals)
12. [Visualization Studio: videos for a mixtape you already have](#12-visualization-studio)
13. [Settings](#13-settings)
14. [Keyboard shortcuts](#14-keyboard-shortcuts)
15. [Command line](#15-command-line)
16. [Tips and troubleshooting](#16-tips-and-troubleshooting)

---

## 1. Quick start

1. Open the app.
2. Drag a folder of songs onto the window (or click **Add folder**). Each song is analysed once; this takes a few seconds per song. When you add a **folder**, the Generate mix options appear first so the first mix is made the way you want.
3. The first mix is made for you automatically. Press **Play**.
4. Don't like something? Drag songs around, change blends, add effects (see [Editing](#6-editing-the-mix)).
5. **File → Save session** to keep your work, **Export audio** for the finished mix, **Export video** for a visual version.

---

## 2. The main window

| Area | What it does |
|---|---|
| **Toolbar** (top) | Add songs, Add folder, Generate mix, Play, Stop, Export audio, Export video, Export mix + video, Visualization Studio. The status bar shows the number of songs and the total mix length (HH:MM:SS). |
| **Songs in the mix** (top left) | The songs in play order, with key, tempo and start time. Drag to reorder. |
| **Inspector** (top right) | Tabs for the selected song: **Song**, **Transition**, **Effects**, **Visual**. |
| **Bottom tabs** | **Timeline**, **Cue sheet**, **Visuals** (video settings), **Shader library**. |
| **Status bar** (bottom) | Song count, tempo range and total length. |

Menus: **File**, **Edit**, **Mix**, **Tools** (Visualization Studio), **Settings**, **Help**.

---

## 3. Adding songs

- Drag music files or folders onto the window, or use **Add songs** / **Add folder** on the toolbar.
- Subfolders are included when you add a folder.
- Each song is analysed for tempo (BPM), key, and its parts (intro, verse, chorus, bridge, outro). The result is saved in a small file next to the song (`Song.mp3.lmmanalysis`) and in the app's cache, so the same song is never analysed twice, even on another computer if you copy the file along. If the song changes, it is analysed again. A read-only music folder is fine.
- The first batch of songs is mixed automatically. Songs added later are placed at the end of the mix; drag them where you want them.
- Songs that can't be read are listed in a message and skipped.

**Remove a song:** select it and press **Remove** (or Delete). Its neighbours are blended together again.

---

## 4. Generating a mix

Use **Generate mix** (Ctrl+G) to build, or rebuild, the mix. Rebuilding replaces anything you changed by hand, and the dialog warns you before it does.

| Option | What it does |
|---|---|
| **Style** | **Whole songs** (the default) uses as much of every song as possible, like a DJ mixtape. **Short clips** plays a highlight of each song instead. |
| **Clip length** | For short clips: how long each highlight is (10–120 seconds). |
| **Longest blend** | The most bars two songs may overlap. The AI uses each song's whole outro and the next song's whole intro, up to this limit. If both songs are in full flow where they meet, it uses a shorter blend. |
| **Transitions** | **Let the AI choose**, **Bass-swap blends** (the bass changes hands, DJ style), **Crossfades**, or **Hard cuts with effects**. |
| **Tempo** | **Let the tempo glide** (best sound): each song plays at its own speed and only speeds up or slows down around a blend to meet its neighbour. **Hold one tempo** forces one tempo for the whole mix. |
| **Cue sheet marks** | Where the track break goes in the cue sheet: when the new song starts to come in, the middle of the blend, or when the old song has gone. |
| **Biggest tempo change** | How far a song may be sped up or slowed down to match its neighbour (default 12%). Pairs further apart than this get a cut with an effect instead of a beat-matched blend. |
| **Let the AI choose the song order** | Orders songs for the smoothest tempo and key flow. Untick to keep your order. |
| **Match keys** | Shifts a song by up to 2 semitones so it sounds good with the song before it. |
| **Let the AI add effects** | Lets the AI use echo, delay, reverb, filter sweeps, flanger, backspin, cut and stutter. |

**Refresh AI suggestions** (Mix menu) redoes everything you haven't changed by hand and keeps your own edits.

---

## 5. Playing the mix

- **Play / Pause** (Space) renders a preview of the whole mix and plays it. It re-renders after you edit something.
- **Stop** returns to the start.
- Click the ruler or empty timeline space to move the playhead.
- To listen to a transition, put the playhead just before it and press Play.

---

## 6. Editing the mix

Everything you change by hand is remembered, and the AI will not overwrite it when it refreshes. **Undo** (Ctrl+Z) and **Redo** (Ctrl+Shift+Z) work for every edit, and a drag counts as one step.

### The timeline

Songs sit in two alternating rows, like two decks. Shaded areas between songs are the blends. Each song shows:

- a **dark waveform** (80% black) over its colour on every song,
- its **parts** (intro, verse, chorus…) in a coloured strip along the bottom,
- its **effects** as small coloured blocks underneath.

Zoom with **−**, **+**, **Fit**, or Ctrl + mouse wheel.

| Drag… | To… |
|---|---|
| The **middle** of a song | Make the blend with the previous song longer or shorter. |
| A song's **left edge** | Start the song later or earlier. The audio stays where it is in the mix; the blend with the previous song gets shorter or longer by the same amount. |
| A song's **right edge** | End the song earlier or later. |
| An **effect block** | Move the effect in time. |

Movements snap to beats.

### Song tab
- **Starts at / Ends at**: type exact times, or pick a part from the list and press **Start here** / **End here**.
- **Back to the AI's choice**: resets the trim.
- Shows the song's tempo, the speed it plays at, and its key (and any pitch shift).

### Transition tab (the blend after the selected song)
- **Style**: bass-swap blend, crossfade, cut with an effect, or hard cut.
- **Blend length**: in beats (4 beats = 1 bar).
- **Effects at this transition**: untick to turn off every effect around this blend, both the AI's and yours. They are only muted, so ticking it again brings them back.
- **Back to the AI's choice**.

### Order
Drag songs in the **Songs in the mix** list, or use the **↑ ↓** buttons.

### Visual tab
Pick the visual for the selected song (used in video export). See [Making a video](#10-making-a-video).

---

### Preview the video live

**Preview video** (Ctrl+Shift+P, in the toolbar and the Tools menu) opens a window that shows the visuals in real time, using the same drawing code as the exporter, so the blends and the cover/artist/title card match the final video. It follows the timeline: press **Play** (in either window) and it plays; drag the playhead and it scrubs. Press Play once so the mix is rendered, and music-reactive visuals then react to your sound. Changing a song's visual, the visual mode or the overlay updates the picture straight away. It's drawn at a reduced size to stay smooth; the export is full quality.

## 7. Effects

Open the **Effects** tab for the selected song. Use **Add at start** or **Add at end**, then adjust the effect's timing and settings. Select an effect in the list or click its block on the timeline. **Remove effect** deletes it.

| Effect | What it does | Main settings |
|---|---|---|
| **Echo** | Repeating echoes that fade away. | beats, feedback, level, damp |
| **Delay (ping-pong)** | Echoes that bounce left and right. | beats, feedback, level, damp |
| **Reverb** | A sense of space. | decay, level, damp |
| **Filter sweep** | Sweeps a low-pass or high-pass filter. | mode, start Hz, end Hz, q |
| **Flanger** | A swirling, jet-like sound. | rate, depth, base |
| **Backspin** | Rewinds like a record being pulled back, then stops. | speed |
| **Cut (crossfader chop)** | Chops the sound in time, like a DJ working the crossfader. | mode, division, duty, floor |
| **Stutter (beat repeat)** | Repeats a slice of the music, and can speed up into a roll. | beats, roll, level |

**Cut modes:** *gate* closes the sound completely on every slice; *bass_kill* removes the lows on closed slices; *highs_kill* removes the highs. **division** is the slice length in beats, and **duty** is how much of each slice stays open.

The AI picks effects too (you can turn that off in Generate mix). Its choices are normal effects: edit, move or delete them. Effects marked as yours are never replaced.

---

## 8. Saving, sharing and reopening

- **Save session** (Ctrl+S) writes a `.lmm` file. **Open session** (Ctrl+O) brings it back with every edit.
- **To share a mix with a friend:** give them the `.lmm` file and a folder with the same songs. They open the file, point the app at their folder if it asks, and get exactly your mix to play or change. Songs are found by their content, so renamed or moved files are fine.
- Visuals you imported travel inside the session file.
- If songs can't be found, use **File → Find missing songs…** and choose the folder that has them.

---

## 9. Exporting audio and the cue sheet

**Export audio** (Ctrl+E) saves the finished mix as:

| Format | Quality |
|---|---|
| **WAV** | 24-bit |
| **MP3** | 320 kbps |
| **FLAC** | 24-bit, best (maximum) compression |

Along with the audio, a **.cue** file and a plain-text **track list** are saved next to it, with a track break where each song comes in. Use **Cue sheet** (bottom tab) to see the list, **Copy track list** to paste it somewhere, or **Save cue sheet…** to save it on its own.

---

## 10. Making a video

**Export mix + video** (Ctrl+Alt+E) saves the audio (with its cue sheet) and the MP4 together. The mix is rendered only once.

**Export video** (Ctrl+Shift+E) makes an **MP4** (H.264 video + AAC audio) of your mix. Visuals blend into each other exactly as the music does, and the current song's **cover art, artist and title** appear in the lower-left corner.

Settings are in the **Visuals** tab at the bottom:

| Visual mode | What it does |
|---|---|
| **Let the app choose** | Picks visuals to suit each song: calm ones for quiet songs, intense ones for loud songs. |
| **Random visual for each song** | A different random visual per song. It draws from the whole library and avoids recent repeats, so every visual gets a turn. |
| **I choose per song** | You pick each song's visual in the **Visual** tab. |
| **One visual for the whole video** | One visual throughout. |

- **Pick different random visuals** reshuffles the random choices.
- **Size**: 854×480, 1280×720, 1920×1080 or 1080×1080 (square). **Frame rate**: 24, 30 or 60 fps.
- **Show cover art, artist and title** turns the lower-left card on or off for this video. See also [Settings](#13-settings).

### Video files in a mix

Add video files (mp4, mkv, mov, webm, avi, m4v) like any song. Their sound is mixed and beat-matched as usual, and **in the exported video the file's own picture is shown instead of a visual**, following the same tempo changes as the sound. Songs that are plain audio keep getting visuals, so you can mix both kinds. In **Video transitions → Default transition** the option **Use video files as the picture** turns this off. A visual you pick for a video song in the **Visual** tab wins over its video. In the **Visual** tab, **Use a video clip…** shows any video file (looped) while a song plays.

### Video transitions

The **Video transitions** tab chooses how the picture changes at each song change. There are 20:

- **Classic (12):** crossfade, dip to black, dip to white, wipe, push / slide, circle iris, clock wipe, zoom through, noise dissolve, pixelate, blinds, swirl.
- **♪ Rhythm (8):** beat zoom, beat flash, beat shake + RGB split, glitch slices, bass ripple, beat strobe, beat mosaic, kick spin. These measure the kick and bass of your music at every frame and pulse with it.
- **🎲 Random** (all 20, classic only, or rhythm only) picks a different one at every change.

Every transition has the same controls (the ones that don't apply to the chosen transition are greyed out):

| Control | What it does |
|---|---|
| **Length** | Seconds the transition takes. *Automatic* follows the audio blend (mixes) or the *Visual blend* setting (studio). |
| **Angle** | Direction of wipes, pushes and blinds; start angle of the clock wipe. |
| **Softness** | How soft the edge of a wipe, iris, clock wipe or dissolve is. |
| **Intensity** | Strength: zoom amount, pixel size, swirl, shake, glitch, flash. |
| **Beat sensitivity** | How strongly the ♪ transitions react to the music (0 = ignore it). |
| **Easing** | Smooth, linear, ease in or ease out. |

The left side sets the **default for every song change**. Select a song and use the right side to give **its own transition** different settings (untick *Use the default transition*). Watch it live in **Preview video**.

Video export needs a graphics card or driver with **OpenGL 3.3**. Rendering takes longer than the length of the mix on slower computers, and you can cancel at any time.

---

## 11. Shader library: managing visuals

The visuals are *Shadertoy* shaders (small programs that draw animated pictures). Eight are built in. You can add more from [shadertoy.com](https://www.shadertoy.com). They are saved on your computer and work offline afterwards. Music-reactive shaders react to your mix.

Open the **Shader library** tab (bottom of the main window, or inside the Visualization Studio).

- **List**: every visual with a thumbnail.
- **Live preview**: the selected visual animates on the right. Use **Pause** and **Restart**.
- **Name**: rename your own visuals (built-ins can't be renamed).
- **Suits**: calm, medium or intense. "Let the app choose" uses this.
- **View/Edit Code**: see and change a saved shader: the code of every pass and what feeds each iChannel. **Save changes** checks that it compiles; if it doesn't, your old version is kept. Built-in visuals are view-only.
- **Back up all…** saves every visual you added (with their textures and clips) into one `.lmmshaders` file. **Import backup…** adds them back (ones you already have are skipped).
- **Export…**: save a visual as a file to back it up or share it.
- **Remove**: delete one of your own visuals. Built-ins can't be removed.
- **Use for the whole video**: sets the video to one visual.

### Adding a visual: **Add from Shadertoy…**

Shadertoy has no download button, so there are three ways in:

**Paste code.** For a simple shader: open it on Shadertoy, copy the code from the editor, and paste it. (Shadertoy JSON also works.)

**Multi-pass.** For shaders with extra tabs (**Common**, **Buffer A**, **Buffer B**, **Buffer C**, **Buffer D**, **Image**):
1. Open the **Multi-pass** tab.
2. Paste each tab's code into the matching tab. Fill in only the tabs the shader has; **Image** is required.
3. For each Buffer and the Image, set what **iChannel0–3** read. Copy this from the small boxes under each tab on Shadertoy: **Music** for audio, **Buffer A–D** for buffers (a buffer reading its own name is a feedback loop), or **Nothing / noise**.
4. Click **Add visual**.

**From a link.** Paste the shader's web address (like `https://www.shadertoy.com/view/XXXXXX`). It's downloaded complete, with all of its passes. **No account or API key is needed.** An API key box is there only as a fallback. This needs internet just for the download. If a shader's author has blocked outside access, use the paste or multi-pass tabs instead.

Textures and video clips: a channel can be set to **Texture image…** or **Video clip…**, which opens a file browser. For shaders you download or import, the app finds the textures and clips the code uses and shows exactly those on the right channel; if a file isn't on your computer yet, it says so and the **…** button next to the channel lets you pick it. Webcam, cube-map and 3D-texture inputs can't work offline and are replaced with noise. A shader's own *sound* tab is ignored: the video always uses your mix's audio. A shader's music input can be on any channel (iChannel0–3) and reacts to the mix.

---

## 12. Visualization Studio

Already have a mixtape (made in another program, or by a DJ)? The studio makes a video for any audio file. Open it from **Tools → Visualization Studio** (Ctrl+Shift+V) or the toolbar.

### Steps
1. **Open audio** (Ctrl+O): choose an mp3, wav, flac, m4a or a video file. The waveform appears, and the file's tags give the first marker. If a `.cue` file with the same name sits next to the audio, the app offers to use it.
2. **Mark where the songs change.** Choose any of:
   - **Import cue sheet** (Ctrl+I): a `.cue` file, or a plain text list with a time at the start of each line, such as `12:34  Artist - Title` or `[1:02:03] Artist – Title`. The track list this app writes works too.
   - **Add markers by hand:** double-click the waveform, right-click it, press **M** at the playhead, or use **Add marker here**.
3. **Edit the markers.** Click a marker (in the list or the timeline) to edit it under **Selected song**: start time, artist, title, cover image, and visual. Drag a marker on the timeline to move it. Right-click a marker (or press Delete) to remove it.
4. **Choose the visuals** under **Video**:
   - **Let the app choose**: matched to how loud each song is.
   - **Random visual for each song**.
   - **I choose a visual for each song**: set it in each marker's **Visual** box.
   - **One visual for the whole video**.
5. **Preview**: press Play. The video preview follows the music live.
6. **Export video** (Ctrl+E): saves an MP4 with your original audio as the soundtrack.

### The timeline
Click to move the playhead. The red line is the playhead; coloured flags are the song markers. Zoom with **−**, **+**, **Fit**.

### Video settings
- **Visual blend**: how many seconds the visuals take to blend at each song change (the *Length* of a transition set to Automatic).
- **Default transition between songs**: one of the 20 transitions with all its controls (see [Video transitions](#video-transitions)). Select a song to give *its* transition different settings under **Transition into this song**.
- **Video files**: if the file you opened is a video, its own picture is shown, in sync with its sound (**Use the file's own video as the picture** turns it off). Pick a visual for a song to replace it, or **Video clip…** to show another video file (looped) for that song.
- **Size**, **Frame rate**, **Pick different random visuals**.
- **Show cover art, artist and title** (lower left) can be turned off for this project. Each marker can have its own cover image; markers without one get a plain coloured tile with the song's initial.
- Before the first marker, the video shows the audio file's own title.

### Projects
**Save project** (Ctrl+S) writes a `.lmv` file that keeps your markers, visuals and settings (imported visuals travel inside). **Open project** (Ctrl+Shift+O) brings it back; if the audio moved, point the app at its folder. **Save cue sheet…** exports your markers as a `.cue` file. Undo/redo work for all edits.

Very long files (over about 40 minutes) work too; the music-reactive part of the visuals uses a lower-detail view of the audio to save memory.

---

## 13. Settings

**Settings → Show cover art, artist and title on videos** is the master switch for the lower-left card.

- It is **on by default**.
- Turn it **off** and no video shows the card: not mix videos, not the studio, not the command line. Each video also has its own checkbox, which only matters while the master switch is on.

---

## 14. Keyboard shortcuts

**Main window**

| Keys | Action |
|---|---|
| Ctrl+N / Ctrl+O / Ctrl+S / Ctrl+Shift+S | New / Open / Save / Save as |
| Ctrl+I / Ctrl+Shift+I | Add songs / Add folder |
| Ctrl+G | Generate mix |
| Space | Play / pause |
| Ctrl+E / Ctrl+Shift+E / Ctrl+Alt+E | Export audio / Export video / Export both |
| Ctrl+Z / Ctrl+Shift+Z | Undo / Redo |
| Delete | Remove the selected song |
| Ctrl+Shift+V | Visualization Studio |
| Ctrl+Q | Quit |

**Visualization Studio**

| Keys | Action |
|---|---|
| Ctrl+O / Ctrl+Shift+O | Open audio / Open project |
| Ctrl+S / Ctrl+Shift+S | Save project / Save as |
| Ctrl+I | Import cue sheet |
| Ctrl+E | Export video |
| Space | Play / pause |
| M | Add a marker at the playhead |
| Delete | Remove the selected marker |
| Ctrl+Z / Ctrl+Shift+Z | Undo / Redo |
| Ctrl+W | Close the studio |

---

## 15. Command line

The same program works from a terminal (`lmm` below stands for the app's program name):

```
lmm mix songs/ -o mix.flac --session mix.lmm       analyse, mix and write a cue sheet
lmm mix songs/ -o clips.mp3 --mode clips            short highlight clips
lmm show mix.lmm                                    print tracklist, transitions, effects
lmm render mix.lmm -o again.wav --library "D:/Music"
lmm video mix.lmm -o mix.mp4 --mode random          add --no-overlay to hide the card
lmm studio mixtape.mp3 --cue mix.cue -o mix.mp4 --mode random
lmm config --overlay off                            turn the lower-left card off everywhere
```

Useful options: `--overlap-bars` (longest blend), `--tempo-mode`, `--no-effects`, `--keep-order`, `--visual NAME`, `--blend SECONDS`, `--save-project x.lmv`. Run any command with `--help` for the full list.

---

## 16. Tips and troubleshooting

**How good is the analysis?** It uses signal processing, not a neural network, so it works fully offline. It does best on beat-driven music with a steady tempo. Key detection on dense or atonal music, and the part labels, are best-effort guesses; you can always fix the result by hand.

**Two songs didn't blend smoothly.** Songs more than about 25% apart in tempo (after trying half and double time) can't be beat-matched, so the app uses a cut with an effect. You can raise **Biggest tempo change** in Generate mix, or choose a different order.

**A blend is too long or short.** Change **Blend length** in the Transition tab, drag the song, or lower **Longest blend** in Generate mix.

**I want fewer effects.** Untick **Let the AI add effects** in Generate mix, or untick **Effects at this transition** on one blend.

**"File not found" on a song.** Use **File → Find missing songs…** and choose the folder that has your copy.

**Video export says OpenGL isn't available.** Video needs OpenGL 3.3. Update your graphics drivers (on a virtual machine or remote desktop, it may not be available). Audio features work without it.

**A visual looks different from Shadertoy.** Some shaders use inputs that can't work offline (webcam, cube maps, 3D textures). They are replaced with noise, and the app shows a warning on that visual. Shaders that use a texture or video need that file: open **View/Edit Code** and pick it.

**A video doesn't react to the music.** Open the shader in **View/Edit Code** and check that one iChannel is set to **Music (audio)**; shaders pasted as plain code use the music on iChannel0.

**No sound from Play.** The preview needs an audio output device. Exporting still works without one.

**Where is my data kept?** Imported visuals and preferences are stored in the app's data folder for your account on your computer. Sessions (`.lmm`) and projects (`.lmv`) are saved wherever you choose.
