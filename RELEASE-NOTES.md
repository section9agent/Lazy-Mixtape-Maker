## What's new

### Playlists
- Add a playlist (`.m3u`, `.m3u8`, `.pls`, `.xspf`) with **Add playlist**, or drag it onto the window.
- The mix keeps the playlist's order. The AI never reorders it, but it still beat-matches, blends and adds effects.
- Songs a playlist lists that can't be found are reported and skipped.
- The command line `mix` keeps a playlist's order too.

### Edit song info
- Change a song's **cover art, artist and title**. The dialog starts with what the song has now, which is the file's own tags until you change it, and has a **Reset** button.
- Open it from the **Song** tab, the **Song info…** button, a double-click on a song, or **Ctrl+Shift+E**.
- Edits show in the song list, cue sheet, track list, live preview and the exported video's card.
- A chosen cover is saved inside the session file. Edits can be undone.
- The **Visualization Studio** has the same dialog.

### Shaders that need textures or videos
- When a Shadertoy shader uses textures or video clips, the app now downloads them and saves them with the shader, in `shaders/<shader name>/`.
- If a file can't be downloaded, you get the file name, a link to get it, and the folder to put it in. The same steps are saved in that folder as `HOW-TO-ADD-MISSING-FILES.txt`.
- New **Download missing files** and **Open its folder** buttons in the Shader library.

### Video on the Visualization Studio timeline
- Put your own video on a song's section instead of a shader.
- **Line up by sound** guesses where the video belongs by comparing its sound with the music.
- Drag the video in its own lane, nudge it in **millisecond** steps, and change its **speed**.
- The video's own sound is muted and never used in the mix.

### Look and feel
- All buttons now have a raised **3D look**.
- The up and down arrows under the songs in the mix are now **bold**.

### Changes
- Imported shaders are now stored in a folder called `shaders` (an older `visuals` folder is renamed automatically).
- The user manual is now also available as a **PDF**.

### Fixes
- Fixed the macOS build failing in the live video preview test.

Everything still runs offline. Windows (.zip), macOS (.zip) and Linux (.tar.gz) builds are attached.
