# Lazy Mixtape Maker

An offline auto-DJ for your own music. Point it at a folder of songs and it works out each song's
**tempo, key and parts** (intro / verse / chorus / bridge / outro), puts the songs in a smooth order,
**beat-matches and key-matches** them, and blends the lot into one seamless mixtape, with a
**cue sheet** marking where each song begins. Then you can fix anything you don't like, save the
session, and export audio (WAV / MP3 320 / FLAC) and an **MP4 video** with Shadertoy visuals.

Everything runs on your computer. Nothing is uploaded and no internet is needed (the only optional
online feature is fetching a shader by its Shadertoy link; pasting its code works offline).

Runs on **Windows, macOS and Linux**. Reads **mp3, wav, flac and m4a**.

## Run it

From source (Python 3.10+):

```
pip install -r requirements.txt
python -m lazy_mixtape_maker          # opens the app
```

Standalone builds (no Python needed) come from `pyinstaller packaging/lmm.spec`; the GitHub workflow in
`.github/workflows/build.yml` builds the Windows, macOS and Linux versions for you (run it from the
Actions tab, or push a `v*` tag).

## Using the app

1. **Add songs**: drag files or folders onto the window (or *Add songs…* / *Add folder…*). Each is analysed once and cached.
2. **Generate mix** (Ctrl+G) to choose how it's built, or just press **Play**. The first mix is made automatically.
   * *Whole songs* (default) uses as much of every song as possible. *Short clips* gives rave.dj-style highlights of ~30 s each (length adjustable).
   * *Tempo*: let it glide from song to song (best sound; each song only speeds up or slows down around the blend), or hold one tempo for the whole mix.
   * The AI picks the order, how long each blend is (it uses each song's whole outro and the next song's whole intro, up to *Longest blend*, default 32 bars), bass-swap or crossfade, small key shifts (up to 2 semitones) and effects. Each of these can be switched off.
3. **Edit** anything:
   * *Order*: drag songs in the list, or ↑ ↓. *Remove* deletes a song and the neighbours are re-blended.
   * *Timing*: drag a song left/right on the timeline to change how much it overlaps the previous one; drag its right edge to end it earlier; or use the **Song** and **Transition** tabs (start/end points, blend length and style).
   * *Effects*: **Effects** tab (echo, delay, reverb, filter sweep, flanger, backspin, **cut**: the crossfader chopping the sound or EQ-killing bass/highs in time, and **stutter**: a rolling beat repeat). Add at the start or end of a song, then drag the coloured block to retime it or edit its length and settings. The AI uses the same effects, and its choices are editable too.
   * *Visuals*: **Visual** tab picks a visual per song.
   * *Preview this transition* (Ctrl+T) plays just the blend. Undo/redo with Ctrl+Z / Ctrl+Shift+Z.
4. **Save session** (Ctrl+S) writes a `.lmm` file. Reopen it any time. To share: give a friend the `.lmm` file and your songs; they open it, point at their folder if asked (songs are found by content, so renamed or moved files are fine), and get the same mix to play or adjust. Imported Shadertoy visuals travel inside the session.
5. **Export audio**: WAV (24-bit), MP3 (320 kbps) or FLAC (24-bit, maximum compression). A `.cue` file and a text track list are written next to it with a track break at each song's entry. (*Generate mix → Cue sheet marks* can mark the middle or end of the blend instead.)
6. **Export video** (MP4, H.264 + AAC): the **Visuals** tab chooses between
   *the app chooses* (calm/medium/intense visuals to suit each song), *random visual for each song*,
   *I choose per song*, or *one visual for the whole video*. Visuals cross-fade exactly like the audio, and
   the current song's cover art, artist and title sit in the lower-left corner.

7. **Shader library** tab: every visual with a live animated preview, rename, “suits calm / medium / intense songs”, code viewer, import, export and remove.
   Per-song choices in *random* and *the app chooses* modes draw from the whole library (no immediate repeats, every visual gets a turn); **Pick different random visuals** reshuffles.

### Visualization Studio (videos for a mixtape you already made)

*Tools → Visualization Studio* (Ctrl+Shift+V). Open any mp3 / wav / flac / m4a, then:

* **Mark where the songs change**: import a `.cue` sheet or a plain text track list (`0:00 Artist - Title` per line, including the list this app writes), or add markers by hand (double-click the waveform, **M**, right-click). Drag markers to move them; edit time, artist, title, cover image and visual per song.
* **Choose the visuals**: one for the whole video, one per song (the *Visual* box), or let the app / random mix them per song. Visuals blend at each marker (*Visual blend* sets how long).
* **Preview** live while the music plays, then **Export video** (MP4, your original audio as the soundtrack). Undo/redo, save/open `.lmv` projects (imported visuals travel inside).
* From the command line: `lmm studio mixtape.mp3 --cue mix.cue -o mix.mp4 --mode random` (`--visual NAME`, `--blend 6`, `--no-overlay`, `--save-project x.lmv`).

**Cover art, artist and title** (lower left) is on by default everywhere. Turn it off for every video with *Settings → Show cover art, artist and title* (or `lmm config --overlay off`), or per video with its own checkbox.

### Adding visuals from Shadertoy

Open a shader on shadertoy.com, copy its code from the editor (or *Download → JSON*), then
**Visuals → Add from Shadertoy…** and paste it. It is stored on your computer for good. Single-pass and
multi-pass (Buffer A–D) shaders work, and music-reactive ones react to your mix. Inputs that need the
internet, a webcam or video are replaced with noise. Eight original visuals are built in.

## Command line

```
lmm mix  songs/ -o mix.flac --session mix.lmm       # analyse + mix + cue sheet
lmm mix  songs/ -o clips.mp3 --mode clips --clip-seconds 30
lmm show mix.lmm                                    # tracklist, transitions, effects
lmm edit mix.lmm move 3 1 | remove 2 | transition 1 --type crossfade --beats 16 | fx-add 2 echo ...
lmm render mix.lmm -o again.wav --library "D:/Music"
lmm video  mix.lmm -o mix.mp4 --mode random         # or --visual "Aurora", --add-shader file.glsl
```

## How it works (and its limits)

* Analysis is classic signal processing (onset detection, beat tracking, chroma + key profiles, similarity-based structure), not a neural network, so it works fully offline with no model files. It does well on beat-driven music with steady tempo. Key detection on dense or atonal music, and section labels, are best-effort guesses. Songs with a drifting live tempo won't hold a beat grid as tightly.
* Beat matching places every song on a grid fitted to its actual drum hits (a few ms accurate), blends on bar lines, and stretches only the overlapping parts, so most of each song plays untouched.
* Songs more than ~25 % apart in tempo (after trying half/double time) can't be beat-matched; the mixer uses a cut with an effect (backspin, echo-out, filter sweep) instead. The tempo limit is adjustable.
* It blends whole songs; it doesn't separate vocals/instruments, so there are no mashups.

## Tests

`pip install -r requirements-dev.txt && python -m pytest` (synthetic songs in all four formats; video tests need OpenGL 3.3 and skip themselves without it).
