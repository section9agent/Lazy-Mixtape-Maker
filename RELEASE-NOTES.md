## What's new

### Deep analysis (All-In-One)
- **Mix → Deep analysis (All-In-One)…** runs the All-In-One neural network (Taejun Kim & Juhan Nam) on each song's stems to find the tempo, beats, downbeats and song parts (intro, verse, chorus, bridge, outro).
- See the app's analysis and All-In-One's side by side and choose **per song** which one the mix uses. The app's own analysis is always kept, Undo works, and the choice is saved with the session.
- Included in the **-Stems** downloads (models built in, works offline).

### More for mixes
- **New mix** (toolbar, Ctrl+Shift+N): a whole new mix from every song you've added (even ones you took out) - a different order, different transitions and effects each time.
- **Five more stem transitions:** drums first, drums last, instrumental bridge, breakdown and drop, and a cappella out (nine in all). "Stem blends, varied" now lets the AI pick among them.

### Mashup Studio
- **Mashup Studio** (toolbar button, Tools menu, Ctrl+Shift+M): take two songs, split them into stems (vocals, drums, bass, other) and mash them up.
- **Let the AI do it:** *Song B's vocals over song A's music* (or the other way round), *Trade back and forth* (the music and the singer swap songs every 16 bars), or let the AI choose.
- **Or do it yourself, with full control:** eight lanes (each stem of each song), clips you drag, trim, split, duplicate, mute and fade, snapping to bars or beats. A clip panel sets exact positions, source times, lengths, volume and fades.
- **Beat match** (song A's tempo, song B's, or your own) and **key match** (keep either song's key, or set the pitch shift yourself).
- Each clip shows its **stem's waveform**, so you can see where the singing, the beat and the bass are.
- **Level vocals** with LUFS Lab's voice leveler: evens out quiet and loud lines and sets the vocals to the loudness you choose.
- Play from the playhead, undo / redo, save as `.lmmash`, export WAV / FLAC / MP3, or **Add to mix** to drop the mashup into your mixtape.

### Two downloads: with or without stems
- New **-Stems** downloads (Windows, macOS, Linux) have the stem engine and its model **built in**: nothing to install, works offline. They are much bigger, so the normal downloads stay as they were.
- Updates keep you on the kind of download you have.

### Shader Remix Studio: make visuals react to the music
- Select any visual in the Shader library and click **♪ Remix…**. Many Shadertoy visuals ignore the music; a remix makes them move with it.
- Pick effects: **beat zoom, flash, colour shift, shake, RGB split, wobble, kaleidoscope, time push, contrast pump**. Set how much of each, and whether it listens to the **bass, mids, treble** or the whole sound. Gentle / Club / Wild presets give a quick start.
- The **original and the remix play side by side**, fed by a beat loop, so you can see the difference as you tune.
- **Save as new visual** keeps the original untouched. Re-open a remix any time to re-tune it. Works with multi-pass shaders too.
- The library now shows which visuals are **♪ reacts to music** and which are **static**.

### Shader or video, your choice (and back again)
- For a video song, or a video clip, pick any visual to show **instead of the video**, then switch back with **▶ This song's own video / ▶ Video clip**. Nothing is lost when you try a visual.
- Works in the mix window's Visual tab and in the Visualization Studio. In the studio the placed video, its sync and its speed are kept while a visual is shown.

### Project settings
- **Mix window:** *Mix → Project settings…* (Ctrl+Shift+G) opens the same options as when you drop a folder, any time. By default it **keeps your song order and hand edits** and only refreshes tempos, blends, key matching and AI effects. Tick *Rebuild the whole mix* to start over. Undoable.
- **Visualization Studio:** a **Project settings…** window (Ctrl+Shift+G) with visual mode, size, frame rate, quality, blend, cover card, source video and the default transition.

### Also new
- **Stem transitions:** transition styles that mix a song's drums, bass, vocals and other parts separately: true bass swap, bass and singers swap (one singer at a time), mashup (this singer over the next song's music) and next singer arrives. Songs are split once and remembered (**Mix > Split songs into stems…**, or the button in the Transition tab). Needs the **-Stems** download; without it, or until the songs are split, these styles play as a normal blend.
- The shader editor now has a **Name** box, so a visual can be renamed while you edit it.
- **Help > About:** credits for the open-source software used (with licences), "Coded by Claude & Emmanuel Hoachlander", and a **Donate with PayPal** button.
- **Automatic updates:** the app can check GitHub releases and download and install the newest version for you (Install and restart / Later / Skip this version). Turn it off any time under **Help > Check for updates automatically**.

### Fixes
- The stem engine no longer needs ffmpeg installed on the computer: it uses the copy that comes with the app.
- **Linux / Steam Deck (SteamOS):** the Linux build no longer bundles its own graphics and C++ libraries, so it uses the computer's own (newer) graphics drivers. If the normal OpenGL route isn't available (for example no GLX), the app tries EGL (surfaceless and gbm), X11 and finally software rendering, and lists what each one said if none works. To try one first: `LMM_GL_BACKEND=egl-surfaceless` (or `egl`, `egl-gbm`, `x11`, `software`).
- Fixes a crash on start-up on the Steam Deck introduced by the previous build's last-resort OpenGL route (it has been removed).
- Linux: the window lays itself out again after it is maximized, made full screen or resized, which cures widgets piling up on the right and bottom.
- Windows and macOS builds: tests that don't need OpenGL no longer try to use it, and the live preview test is more patient on machines without a GPU.
- The **Size** box in the Visuals tab and in the Visualization Studio now stays on the size you pick (it was snapping back to 1280 × 720).

Everything still runs offline. Windows (.zip), macOS (.zip) and Linux (.tar.gz) builds are attached.
