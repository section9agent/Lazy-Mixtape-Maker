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
17. [OpenGL troubleshooting (Linux and Steam Deck)](#troubleshooting-opengl-not-available-linux-and-steam-deck)
18. [About, donations and updates](#about-donations-and-updates)
19. [Stems and stem transitions](#stems-and-stem-transitions)
20. [Mashup Studio](#mashup-studio)
21. [MilkDrop visuals](#milkdrop-visuals)

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
- **Playlists:** **Add playlist** (toolbar and File menu) or dropping a `.m3u`, `.m3u8`, `.pls` or `.xspf` file adds its songs **in the playlist's order, and the mix keeps that order**: the AI never reorders a playlist (it still beat-matches, blends and picks effects). Relative paths work, and songs the playlist lists that can't be found are reported and skipped. Songs you add afterwards go to the end. On the command line, a playlist given to `mix` is kept in order too.
- **Every song is levelled to the same loudness.** Its loudness is measured when it's added (integrated LUFS, as streaming services measure it), and from then on the app plays it at -16 LUFS (up to 15 dB louder or 20 dB quieter) in mixes and in the Mashup Studio. A quiet old recording and a loud modern master then sit at the same volume. Your files are never changed. The master limiter catches any peaks.
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

**Project settings…** (Mix menu, Ctrl+Shift+G) opens these same options at any time, without starting over. With **Rebuild the whole mix with these settings now** unticked (the default), the settings are applied to the mix as it is: tempos, blends, key matching and the AI's effects are refreshed, while your song order and your hand edits (trims, your own effects, your own transitions) stay. Tick the box to make the mix again from scratch. Changes can be undone.

**Refresh AI suggestions** (Mix menu) redoes everything you haven't changed by hand and keeps your own edits.

**New mix** (toolbar, Mix menu, Ctrl+Shift+N) makes a whole new mix from **every song you've added** - including songs you took out of the mix - with a different song order, different transitions and different effects each time. The order is still a smooth one: the AI picks among the good orders instead of always the same best one. Press it again for another mix; Undo brings the previous one back. If you had kept your own song order, New mix lets the AI order the songs.

---

## 5. Playing the mix

- **Play / Pause** (Space) renders a preview and plays it. It re-renders after you edit something.
- **Preview** (beside the time, above the timeline) chooses what Play renders:

| Preview | What plays | Good for |
|---|---|---|
| **1 transition (2 songs)** | The blend nearest the playhead, from about 10 seconds before it to 10 seconds after. | Checking a transition after you change it. Ready in a few seconds. |
| **4 songs** | The four songs around the playhead's nearest blend, from 10 seconds before the first of their three blends to 10 seconds after the last. | Hearing how a run of songs flows. |
| **Whole mix** | Everything, starting at the playhead. | Listening right through. |

- A short preview sounds exactly like that part of the finished mix. Its playhead moves along the mix's own timeline, so you can see where you are. Click inside it to jump around in it. Click outside it and the next Play makes a new preview there. If it was playing, that starts straight away.
- When a short preview ends, the playhead goes back to its start, so Play hears it again. Editing the mix makes it out of date, and the next Play renders it afresh.
- **Stop** returns to the start (of the short preview, or of the mix).
- Click the ruler or empty timeline space to move the playhead.
- The app remembers your choice of Preview.

---

## 6. Editing the mix

**Small screens (Steam Deck).** The window fits a 1280×800 screen even with large text. When a panel has less room than it needs, it gets a scroll bar instead of squeezing its controls together. Drag the bar between the top and bottom halves of the window to give either half more room. The visual previews shrink to fit.

Everything you change by hand is remembered, and the AI will not overwrite it when it refreshes. **Undo** (Ctrl+Z) and **Redo** (Ctrl+Shift+Z) work for every edit, and a drag counts as one step.

### The timeline

Songs sit in two alternating rows, like two decks. Each song shows:

- a **dark waveform** (80% black) over its colour on every song,
- its **parts** (intro, verse, chorus…) in a coloured strip along the bottom,
- its **effects** as coloured markers underneath (see below).

**Transitions** are the coloured zones where two songs overlap, with solid edges and a coloured bar along the top of both songs. Each one has a **badge** in the row under the time ruler saying what it is and how many beats it lasts (for example *⟷ bass swap · 16*). The colour tells the kind at a glance:

| Colour | Transition |
|---|---|
| Blue | Bass-swap blend |
| Green | Crossfade |
| Orange | Cut with an effect |
| Red | Hard cut (a thin line, no overlap) |
| Purple | Any stem transition |

**Effects** sit under their song as labelled blocks (*echo*, *filter*… or a short code such as **ECH** or **FLT** when there isn't room). A thin line runs up into the song to show exactly where the effect starts. Even a very short effect is drawn big enough to grab. Effects that are switched off at their transition are grey and say *(off)*.

Point at a badge or an effect to see its details. Hovered and selected markers light up.

Zoom with **−**, **+**, **Fit**, or Ctrl + mouse wheel.

| Drag… | To… |
|---|---|
| A transition's **badge** (or the edge of its zone, between the rows) | Make the blend longer (drag left) or shorter (drag right). A hard cut becomes a blend when you drag it longer. |
| The **middle** of a song | The same: make the blend with the previous song longer or shorter. |
| A song's **left edge** | Start the song later or earlier. The audio stays where it is in the mix; the blend with the previous song gets shorter or longer by the same amount. |
| A song's **right edge** | End the song earlier or later. |
| An **effect** | Move the effect in time. |
| An effect's **right end** (the two little lines) | Make the effect longer or shorter. |

While you drag, a small box next to the pointer shows the new value (beats and seconds). **Click** a transition's badge to open it in the **Transition** tab. With an effect selected, the **← →** arrow keys nudge it by a quarter beat (**Shift**: a whole beat).

Movements snap to beats.

### Song tab
- **Edit song info (cover, artist, title)…** (also the **Song info…** button under the list, a double-click on a song, or Edit → Edit song info, Ctrl+Shift+E): change the song's cover art, artist and title. The window starts with what the song has now, which is what the audio file's own tags say until you change it. **Choose picture…**, **No cover** or **Use the file's cover** set the cover; **Reset everything to the file's own information** goes back to the tags. The change shows in the list, the cue sheet and track list, the live preview and the exported video's card, is saved in the session (a chosen picture is kept inside the `.lmm`), and can be undone. The Visualization Studio has the same dialog.
- **Starts at / Ends at**: type exact times, or pick a part from the list and press **Start here** / **End here**.
- **Back to the AI's choice**: resets the trim.
- Shows the song's tempo, the speed it plays at, and its key (and any pitch shift).

### Transition tab (the blend after the selected song)
- **Style**: bass-swap blend, crossfade, cut with an effect, or hard cut.
- **Blend length**: in beats (4 beats = 1 bar).
- **Effects at this transition**: untick to turn off every effect around this blend, both the AI's and yours. They are only muted, so ticking it again brings them back.
- **Back to the AI's choice**.

### Order
Drag songs in the **Songs in the mix** list, or use the bold **up / down arrow** buttons under the list.

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

- **Save session** (Ctrl+S) saves the mix as a **project folder** named after it, so everything the mix needs is in one place. Choosing *Music/Sunday.lmm* makes:

| In *Music/Sunday/* | What it is |
|---|---|
| `Sunday.lmm` | The session: the mix, every edit, the video settings and the visuals you added |
| `songs/` | Copies of the mix's songs, with their saved analysis (so nothing is analysed again) |
| `stems/` | The stems split for its songs, and their deep analysis |
| `exports/` | Where **Export audio**, **Export video**, the cue sheet and **Export audio + video** save by default |
| `mashups/` | Where the Mashup Studio saves and exports by default while this project is open |

  If you pick a spot inside the mix's own folder, it's saved there. **Open session** (Ctrl+O) brings it back with every edit, and it finds its songs and stems inside the folder. **Back up or move the whole folder** (another drive, another computer, a friend) and it opens complete, even if the original songs have since moved or been deleted.
- **Songs** are copied in when you save, with a progress bar (**Cancel** stops the save and changes nothing). Songs you add later are copied in at the next save. If two different songs share a file name, the second one gets " (2)" added. The original files are left alone. To keep the project small instead, switch off **Settings → Copy songs into the project folder**. The session then refers to the songs where they are, as before.
- **Before a mix is saved**, its stems go into a working folder inside the app's data folder. Saving moves them into the project folder and deletes the working folder. If you close an unsaved mix that has stems, the app asks whether to save it first, because choosing **Discard** deletes those stems. Working folders left behind by a crash are cleaned up after two weeks.
- **Save session as…** from a saved project copies its stems into the new project folder, so the original project keeps its own.
- A session saved by an earlier version opens as before. The next time you save it, it becomes a project folder (the old `.lmm` file is left where it was). Stems that earlier versions kept in one shared folder are still used, and they're copied into the project when you save.
- **To share a mix with a friend:** give them the whole project folder. It has the songs and the stems, so they can open it and play it straight away. (The `.lmm` file on its own works too, with a folder of the same songs: they open it, point the app at their folder if it asks, and get exactly your mix. Songs are found by their content, so renamed or moved files are fine.)
- **Settings → Clear the old stem cache…** deletes the stems that earlier versions kept in one shared folder, and shows how much space that frees. Saved projects keep their own copies. An older session that hasn't been saved since will split its songs again if it needs stems.
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
- **The app picks from**: **Shadertoy and MilkDrop** (the default), **Shadertoy only** or **MilkDrop only**. This decides what "Let the app choose" and "Random" draw from. You can still give any song any visual by hand. See [MilkDrop visuals](#milkdrop-visuals).
- **Size**: 854×480, 1280×720, 1920×1080 or 1080×1080 (square). **Frame rate**: 24, 30 or 60 fps.
- **Show cover art, artist and title** turns the lower-left card on or off for this video. See also [Settings](#13-settings).

### Video files in a mix

Add video files (mp4, mkv, mov, webm, avi, m4v) like any song. Their sound is mixed and beat-matched as usual (and split into stems: the app takes the sound out for the stem engine), and **in the exported video the file's own picture is shown instead of a visual**, following the same tempo changes as the sound. Songs that are plain audio keep getting visuals, so you can mix both kinds. In **Video transitions → Default transition** the option **Use video files as the picture** turns this off. In the **Visual** tab, the list of a video song starts with **▶ This song's own video**: pick any visual to show that instead of the video, and pick **▶ This song's own video** to switch back. A clip you chose with **Use a video clip…** is remembered the same way (**▶ Video clip: …**), so you can try a visual and go back. In the **Visual** tab, **Use a video clip…** shows any video file (looped) while a song plays.

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

There are two kinds of visuals: *Shadertoy* shaders (small programs that draw animated pictures) and *MilkDrop* presets (the classic music visualizer, see [MilkDrop visuals](#milkdrop-visuals)). MilkDrop presets are marked **◈ MilkDrop** in every visual list. Eight Shadertoy visuals are built in. You can add more from [shadertoy.com](https://www.shadertoy.com). They are saved on your computer and work offline afterwards. Music-reactive shaders react to your mix.

Open the **Shader library** tab (bottom of the main window, or inside the Visualization Studio).

- **List**: every visual with a thumbnail. **Show** above it picks **All visuals**, only **Shadertoy** or only **MilkDrop**.
- **Add MilkDrop…** opens the MilkDrop browser (also in the **Visuals** tab).
- **Live preview**: the selected visual animates on the right. Use **Pause** and **Restart**.
- **Name**: rename your own visuals (built-ins can't be renamed).
- **Suits**: calm, medium or intense. "Let the app choose" uses this.
- **View/Edit Code**: see and change a saved shader: the code of every pass and what feeds each iChannel. **Save changes** checks that it compiles; if it doesn't, your old version is kept. Built-in visuals are view-only.
- **Back up all…** saves every visual you added (with their textures and clips) into one `.lmmshaders` file. **Import backup…** adds them back (ones you already have are skipped).
- **Export…**: save a visual as a file to back it up or share it.
- **Remove**: delete one of your own visuals. Built-ins can't be removed.
- **Use for the whole video**: sets the video to one visual.

### Shader Remix Studio: make a visual react to the music

Many Shadertoy visuals just animate and ignore your music. The list says **static** for those and **♪ reacts to music** for the ones that listen. Select any visual and click **♪ Remix…** (also in the studio's Shader library) to open the **Shader Remix Studio**.

- Two pictures play side by side: the **Original** and your **Remix**, both fed by a made-up beat loop (or silence, to compare).
- Tick the effects you want: **Beat zoom**, **Flash**, **Colour shift**, **Shake**, **RGB split**, **Wobble**, **Kaleidoscope**, **Time push** (the visual's own animation speeds up and jumps with the music) and **Contrast pump**. For each, set the **Amount** and which part of the music drives it: **Bass (kick)**, **Mids**, **Treble (hats)** or the **Whole sound**.
- **Start from a preset…** (Gentle, Club, Wild) sets a good starting point; **Strength** scales everything (turn it up for quiet music).
- **Save as new visual** adds the remix to your library (the original is untouched), **♪ reacts to music**, and it can be used anywhere a visual can. Open a remix again and use **Update this remix** to re-tune it. Remixing a remix starts again from the original code. Editing a remix's code by hand turns it into an ordinary visual.
- Remixes work with multi-pass shaders too (they use a free input for the music); if all four inputs of the Image pass are taken, it says so. They also travel with sessions and backups.

### Adding a visual: **Add from Shadertoy…**

Shadertoy has no download button, so there are three ways in:

**Paste code.** For a simple shader: open it on Shadertoy, copy the code from the editor, and paste it. (Shadertoy JSON also works.)

**Multi-pass.** For shaders with extra tabs (**Common**, **Buffer A**, **Buffer B**, **Buffer C**, **Buffer D**, **Image**):
1. Open the **Multi-pass** tab.
2. Paste each tab's code into the matching tab. Fill in only the tabs the shader has; **Image** is required.
3. For each Buffer and the Image, set what **iChannel0–3** read. Copy this from the small boxes under each tab on Shadertoy: **Music** for audio, **Buffer A–D** for buffers (a buffer reading its own name is a feedback loop), or **Nothing / noise**.
4. Click **Add visual**.

**From a link.** Paste the shader's web address (like `https://www.shadertoy.com/view/XXXXXX`). It's downloaded complete, with all of its passes. **No account or API key is needed.** An API key box is there only as a fallback. This needs internet just for the download. If a shader's author has blocked outside access, use the paste or multi-pass tabs instead.

**Shaders that need files.** When a Shadertoy shader uses textures or video clips, the app tries to download them straight away and saves them **with the shader**: such a shader gets its own folder, `shaders/<shader name>/`, holding its `.json` and its files (shaders that need nothing stay as single files in `shaders`). If a file can't be downloaded (no internet, or Shadertoy refused), the app tells you which files are missing, the link to get each one, and the folder to put it in. The same steps are saved in that folder as `HOW-TO-ADD-MISSING-FILES.txt`. Save the file there under the exact name shown, then click **Download missing files** (or just reopen the shader). **Open its folder** opens it for you.

Textures and video clips: a channel can be set to **Texture image…** or **Video clip…**, which opens a file browser. For shaders you download or import, the app finds the textures and clips the code uses and shows exactly those on the right channel; if a file isn't on your computer yet, it says so and the **…** button next to the channel lets you pick it. Webcam, cube-map and 3D-texture inputs can't work offline and are replaced with noise. A shader's own *sound* tab is ignored: the video always uses your mix's audio. A shader's music input can be on any channel (iChannel0–3) and reacts to the mix.

---

## 12. Visualization Studio

Already have a mixtape (made in another program, or by a DJ)? The studio makes a video for any audio file. Open it from **Tools → Visualization Studio** (Ctrl+Shift+V) or the toolbar.

### Steps
1. **Open audio** (Ctrl+O): choose an mp3, wav, flac, m4a or a video file. The waveform appears, and the file's tags give the first marker. If a `.cue` file with the same name sits next to the audio, the app offers to use it.
2. **Mark where the songs change.** Choose any of:
   - **Import cue sheet** (Ctrl+I): a `.cue` file, or a plain text list with a time at the start of each line, such as `12:34  Artist - Title` or `[1:02:03] Artist – Title`. The track list this app writes works too.
   - **Add markers by hand:** double-click the waveform, right-click it, press **M** at the playhead, or use **Add marker here**.
3. **Edit the markers.** Click a marker (in the list or the timeline) to edit it under **Selected song**: start time, artist, title, cover image, and visual. **Edit song info (cover, artist, title)…** opens the same dialog as the mix window (the first song starts with the audio file's own tags and cover; **Reset** goes back to them). Drag a marker on the timeline to move it. Right-click a marker (or press Delete) to remove it.
4. **Choose the visuals** under **Video**:
   - **Let the app choose**: matched to how loud each song is.
   - **Random visual for each song**.
   - **I choose a visual for each song**: set it in each marker's **Visual** box.
   - **One visual for the whole video**.
5. **Preview**: press Play. The video preview follows the music live.
6. **Export video** (Ctrl+E): saves an MP4 with your original audio as the soundtrack.

### The timeline
Click to move the playhead. The red line is the playhead; coloured flags are the song markers. Zoom with **−**, **+**, **Fit**.

### Putting a video on the timeline
Instead of a visual, a song's section can show a video of your own. Select a marker, then under **Video on this song** click **Import video…**.
- **Line up by sound**: the app compares the video's sound with the music of that section and moves the video to its best-guess position. It works best when the clip was cut from the same music at normal speed. If the match is weak it says so; if the video has no sound it can't try. Click the button again any time.
- **Adjust by hand**: drag the video's bar in the **video lane** under the waveform, or type its start time. The **−1 s / −100 ms / −10 ms / −1 ms** and **+** buttons nudge it in milliseconds. Play to check it against the music.
- **Speed**: change the playback speed (0.25x to 4x, with nudge buttons and a reset to 1x). **Loop** repeats a short video.
- The video's own sound is **never** used: it is muted, and the exported soundtrack is only your audio.
- **Visual or video:** the song's **Visual** list starts with **▶ Video: name** (and **▶ The file's own video** when you opened a video file). Pick any visual to show that instead; the video stays on the song (it isn't drawn on the video lane while a visual is chosen) and **▶ Video** switches back to it. **Remove** (under “Video on this song”) deletes it. Everything else (transitions, cards, undo/redo, saving in the `.lmv`) works as before.

### Video settings
**Project settings…** (Edit menu, toolbar, Ctrl+Shift+G) gathers them in one window: how the visuals are chosen, size, frame rate, quality, blend, the cover card, using the file's own video, and the default transition. They are also in the side panel.

- **Visual blend**: how many seconds the visuals take to blend at each song change (the *Length* of a transition set to Automatic).
- **Default transition between songs**: one of the 20 transitions with all its controls (see [Video transitions](#video-transitions)). Select a song to give *its* transition different settings under **Transition into this song**.
- **Video files**: if the file you opened is a video, its own picture is shown, in sync with its sound (**Use the file's own video as the picture** turns it off). Pick a visual for a song to replace it, or **Video clip…** to show another video file (looped) for that song.
- **The app picks from**: Shadertoy and MilkDrop, Shadertoy only or MilkDrop only.
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
| Ctrl+Shift+E | Edit song info (cover, artist, title) |
| Ctrl+G | Generate mix |
| Ctrl+Shift+N | New mix (from every song you've added) |
| Ctrl+Shift+G | Project settings (mix window and Visualization Studio) |
| Space | Play / pause |
| Ctrl+E / Ctrl+Shift+E / Ctrl+Alt+E | Export audio / Export video / Export both |
| Ctrl+Z / Ctrl+Shift+Z | Undo / Redo |
| Delete | Remove the selected song |
| Ctrl+Shift+V | Visualization Studio |
| Ctrl+Shift+M | Mashup Studio |
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

**Mashup Studio**

| Keys | Action |
|---|---|
| Ctrl+N / Ctrl+O / Ctrl+S | New / Open / Save mashup |
| Space | Play / pause |
| Ctrl+E | Export |
| Delete | Delete the selected clip |
| Shift while dragging | Don't snap |
| Ctrl + mouse wheel | Zoom |
| Ctrl+Z / Ctrl+Shift+Z | Undo / Redo |

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

**Where is my data kept?** Imported visuals are saved in a folder called `shaders` inside the app's data folder (a shader that needs textures or clips gets its own sub-folder there, with its files) (an older `visuals` folder is renamed automatically). Preferences are stored in the app's data folder for your account on your computer. Sessions (`.lmm`) are saved in a project folder wherever you choose, with their stems. Visualization Studio projects (`.lmv`) are saved wherever you choose. An unsaved mix's stems sit in a working folder under `projects` in the app's data folder until it's saved.


## Troubleshooting: "OpenGL not available" (Linux and Steam Deck)

The visuals need OpenGL 3.3. The app tries the normal route, then EGL (also with the "surfaceless" and "gbm" platforms), X11, and finally Mesa's software renderer, which works almost anywhere but is slow. If none works, the message lists what each route said. To try one route first, start the app from a terminal with, for example, `LMM_GL_BACKEND=egl-surfaceless ./LazyMixtapeMaker` (other names: `egl`, `egl-gbm`, `x11`, `software`). On SteamOS use Desktop Mode. If it still fails, send the message shown so the right route can be added.

## About, donations and updates

**Help > About Lazy Mixtape Maker…** shows who made the program (*Coded by Claude & Emmanuel Hoachlander*), the open-source software it is built on with each one's licence, and a **Donate with PayPal** button. If you enjoy the program, please consider a donation; it goes to section9agent@hotmail.com. Lazy Mixtape Maker itself is free software under the GNU GPL v3.

**Updates.** The app can look at the project's GitHub releases and install the newest version for you:

- **Help > Check for updates…** checks right now.
- **Help > Check for updates automatically** (also a checkbox in the About window) is on by default. It looks a few seconds after the app starts, at most every six hours. **Untick it to turn updating off completely**: the app then never contacts GitHub on its own.
- When a newer version exists you are asked: **Install and restart** (downloads the build for your system, closes the app, swaps the files and starts the new version), **Later**, or **Skip this version**. You are asked to save first if you have unsaved changes. Your settings, saved visuals and sessions are not touched.
- Only releases that have been *published* count (drafts are invisible). Everything goes over HTTPS to github.com only.
- A copy run from source (`python -m lazy_mixtape_maker`) never checks on its own, and where the app folder isn't writable the button opens the download page instead.

In **Edit code** (Visuals tab or Shader Manager) the **Name** box at the top lets you rename a visual you added at the same time as you change its code; renaming alone saves instantly.


## Stems and stem transitions

The app can split a song into four **stems** (drums, bass, vocals and everything else) and use them for transitions that an ordinary blend can't do.

### The stem transitions

Pick them in the **Transition** tab under *Style*, like any other transition:

- **Stems: true bass swap** - a DJ blend where the real bass lines swap in the middle (not just the low frequencies, which also carry kick drums).
- **Stems: bass and singers swap** - the same, and only one singer is ever heard: the old singer until the middle, the new one after it. Use this when two vocals would clash.
- **Stems: drums first** - the next song's beat slides in under this song first; then the bass swaps, the singers change over and the rest of the next song follows.
- **Stems: drums last** - this song's beat keeps going while the next song's music and singer arrive over it; the beat and bass change over at the very end.
- **Stems: instrumental bridge** - both singers step out, so the middle of the blend is music only, with the bass swapping halfway.
- **Stems: breakdown and drop** - this song drops its beat and bass, leaving the music and singer to build, then the next song drops in all at once three-quarters of the way through.
- **Stems: a cappella out** - this song's music falls away under its singer, who carries on alone; then the next song comes in underneath and its singer takes over.
- **Stems: mashup** - this song's singer carries on over the *next* song's music, and hands over to the new singer at the end of the blend.
- **Stems: next singer arrives** - the next song's singer comes in over this song's music, then the music changes underneath.

Longer blends (16 to 32 beats or more) suit these best. For mashups it helps when the two songs are in matching keys.

To have the AI use stem blends wherever a proper blend fits, choose **Stem blends, varied** as the transition style in the settings window (or in Mix > Project settings). The AI then picks among the bass swap, bass and singers swap, drums first, drums last, instrumental bridge and breakdown; the a cappella and mashup styles depend on the singing, so they are left for you to choose.

### Splitting songs

A stem transition needs both of its songs split. The Transition tab tells you when they aren't and offers **Split these two songs into stems…**; **Mix > Split songs into stems…** does every song in the mix. Each song is split once and remembered, even if the file is later renamed or moved. Until its songs are split, a stem transition simply plays as a normal bass-swap blend, and the status bar says so.

Away from the blend the song is left exactly as it was: stems are only used inside the overlap.

### Deep analysis (All-In-One)

**Mix > Deep analysis (All-In-One)…** runs **All-In-One**, a neural network by Taejun Kim and Juhan Nam, on each song's stems. It finds the tempo, the beats and downbeats, and the song's parts (intro, verse, chorus, bridge, outro). It comes with the **-Stems** download.

The window lists the songs in your mix with both analyses side by side: tempo, the first downbeat and the song's parts. **Analyse the songs** splits songs into stems where needed and analyses each one (once per song; the result is kept). Then choose per song in **The mix uses**, or use one of the buttons for every song. The mix is worked out again straight away, so you can listen and compare. The app's own analysis is never thrown away: switch back any time, and Undo works too. Your choice is saved with the session.

How to judge: the better analysis is the one whose blends land on the beat and start and end at the right moments in the songs. On the command line, `LazyMixtapeMaker deep songs…` prints both analyses for each song.

### Getting the stem engine

The stem engine (the `audio-separator` package running Meta's Demucs model with PyTorch) is large, so there are **two downloads** of the app on the releases page:

- **LazyMixtapeMaker-Windows / -macOS / -Linux** - the normal app, without stems.
- **LazyMixtapeMaker-Windows-Stems / -macOS-Stems / -Linux-Stems** - the same app **with the stem engine and its model built in**. Nothing else to install, and it works offline. It is a much bigger download (several hundred MB).

Updates keep you on the kind of download you have. **Help > About** says "with stems" when the engine is built in.

Advanced: the normal download can also use the engine from a Python on your computer (`pip install "audio-separator[cpu]"`, then `LazyMixtapeMaker stems --python /path/to/python`, remembered from then on). You can split from the command line too: `LazyMixtapeMaker stems song.mp3 --out stems-folder` (`--best` for slightly cleaner stems at half the speed, `--force` to split again).

What to expect: without a graphics card, splitting takes about as long as the song plays on a small two-core computer and uses about 3 GB of memory. Each song is split once per project; its stems are kept in the project folder (about as much disk as the song as a WAV file). How clean the stems are depends on the music: the engine can leave a trace of a singer in the music or the other way round.

Note on licences: the engine's code is MIT, but the terms of the trained Demucs model are not clearly stated by its authors.

## Mashup Studio

**Mashup Studio** (toolbar button, Tools menu, Ctrl+Shift+M) takes two songs, splits them into stems and lets you build a mashup from them - by hand, by the AI, or the AI first and then by hand. It opens with the selected song of your mix and the one after it; the **Other file…** buttons take any song from your computer.

### The screen

- **Songs** - song A and song B, with their tempo and key (and what they become after matching). **Split into stems** splits whichever of the two isn't split yet (once per song).
- **Beat match** plays both songs at one tempo: song A's, song B's, or one you type in. Bars of the timeline then line up with bars of both songs.
- **Key match** shifts one song (at most 4 semitones) into a key that goes with the other; choose whose key is kept. The **Pitch** boxes override it with your own shift (*auto* = key matching decides).
- **Level vocals** runs the vocal stems through the voice leveler from **LUFS Lab**: it evens out quiet and loud lines (silence and breaths aren't boosted), then sets the vocals to the loudness you choose (default -18 LUFS; the music of a typical song is around -14 to -9 LUFS). *Gentle*, *Medium* and *Strong* set how hard it evens things out. Leave it *Off* to hear the vocals as they are.
- **Play both songs at the same loudness** (on by default) brings both songs to the same level, from each song's loudness measured when it was added. A quiet recording isn't drowned out by a loud one. Your clip gains still apply on top. Levelled vocals (above) are already set to their own loudness, so this leaves them alone.
- **The timeline** has eight lanes: vocals, drums, bass and other of song A, then of song B. Each coloured block is a **clip**: a stretch of one stem placed at a time, with that stem's own waveform drawn in it, so you can see where the singing, the beat or the bass is.

### Letting the AI do it

Pick a style and press **✨ Mash it up**. The AI replaces the clips there are; **Undo** brings them back.

- **Song B's vocals over song A's music** (or the other way round): the music song plays from its first downbeat and its intro runs alone. Then the other song's singer comes in on a downbeat, in whole 4-bar phrases, and the music plays out at the end.
- **Trade back and forth**: both songs run side by side, and every 16 bars the music swaps from one song to the other while the other song sings over it.
- **Let the AI choose**: the song that sings more lends its vocals.

### Editing clips

- **Drag** a clip to move it (it snaps to bars or beats - see *Snap to*; hold **Shift** to place it freely). Drag it up or down to another stem of the same song.
- **Drag its left or right edge** to trim it.
- **Double-click** an empty spot of a lane to add an 8-bar clip of that stem there; right-click an empty spot to add a stem or the whole song.
- **Right-click a clip** to split it at the playhead, duplicate, mute or delete it (or press **Delete**).
- The **Clip** panel sets exactly where it starts (in bars), where in the song it plays from, its length, volume, fade-in and fade-out (in beats), and mute.
- Click the ruler to move the playhead; **Ctrl + mouse wheel** or **＋ / －** zooms.

### Playing and saving

**Play** gets the mashup ready (the first time takes a moment while the songs are stretched and shifted) and plays from the playhead. **Save** keeps the mashup as a `.lmmash` file to come back to. **Export…** saves it as WAV, FLAC or MP3, and **Add to mix** saves it and adds it to your mixtape as a song.

---

## MilkDrop visuals

MilkDrop is the music visualizer that came with Winamp: swirling, pulsing, feedback-heavy pictures that move with the beat. Each look is a **preset**, a small `.milk` text file. The app draws them with **projectM**, the open-source MilkDrop engine, so they work offline on Windows, macOS and Linux (Steam Deck included).

MilkDrop presets are visuals like any other. The app can pick them for songs, you can give one to a song in the **Visual** tab or use one for the whole video, and they work in the Visualization Studio. They are kept apart from Shadertoy: the shader library can show just one kind, and **The app picks from** (Visuals tab, and the studio's Project settings) can limit the app's picks to **Shadertoy only** or **MilkDrop only**.

They always react to your music. In a video every frame is drawn with the exact music at that moment, so the beat lines up however long the export takes. Live previews before there's a mix use a made-up beat.

### What comes with the app
- **60 featured presets**, picked by hand: six from each category (Dancer, Drawing, Fractal, Geometric, Hypnotic, Particles, Reaction, Sparkle, Supernova and Waveform). They're in the library from the start, like the built-in Shadertoy visuals.
- **The full "Cream of the Crop" pack**: 9,795 presets compiled and sorted by Jason Fletcher (ISOSCELES), the pack projectM itself ships, plus the MilkDrop texture pack that many presets draw with.

### The MilkDrop browser
Open it with **Add MilkDrop…** (Shader library, or the Visuals tab).

- Pick a **category** on the left, or type in **Search** (it matches words in the preset's name, which includes its author).
- Click a preset to watch it live on the right.
- **Add to my visuals** adds the selected presets (Ctrl/Shift-click to pick several, or double-click one). How intense a preset is comes from its category: Supernova, Sparkle, Particles and Dancer are intense; Hypnotic, Waveform and Drawing are calm. Change it afterwards under **Suits**.
- **Import .milk files…** adds presets from your computer (any MilkDrop 1 or 2 preset). Picture files the preset uses that sit next to it are kept with it.

You can also paste a preset's text into **Add from Shadertoy…** (the Paste code tab): the app recognises it and adds it as MilkDrop.

### Editing, sharing, backing up
- **View/Edit Preset** shows the preset's text. For your own presets you can rename it and change the text (**Save changes** checks it's still a preset). The featured presets are view-only.
- **Remix** isn't offered for MilkDrop, because presets already react to the music.
- **Export…** saves a preset as a `.milk` file, with its own pictures beside it.
- Presets you added, and their pictures, travel inside saved sessions and in **Back up all…** like Shadertoy visuals.

### If a preset doesn't draw
A preset projectM can't read is replaced by a built-in visual, and the export tells you which one. If the browser says MilkDrop isn't available, the app couldn't load projectM. That only happens when running from source without it (see the README).

