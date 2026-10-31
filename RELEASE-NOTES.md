## What's new

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

### Fixes
- Windows and macOS builds: tests that don't need OpenGL no longer try to use it, and the live preview test is more patient on machines without a GPU.

Everything still runs offline. Windows (.zip), macOS (.zip) and Linux (.tar.gz) builds are attached.
