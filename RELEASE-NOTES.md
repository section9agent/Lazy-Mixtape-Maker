# Lazy Mixtape Maker 6.2

## Project folders
Every mix now has its own **project folder** holding everything it needs, so you can back it up or move it and never hunt for files again:

```
Sunday/
  Sunday.lmm    the session
  songs/        copies of the mix's songs, with their analysis
  stems/        each song's stems and deep analysis
  exports/      where audio, video and cue sheets save by default
  mashups/      where the Mashup Studio saves by default
```

- **Saving makes the project folder.** Choosing *Music/Sunday.lmm* saves *Music/Sunday/Sunday.lmm*.
- **Songs are copied in when you save**, with a progress bar you can cancel. Songs added later are copied in at the next save, and the originals are left alone. If you'd rather keep projects small, switch off **Settings → Copy songs into the project folder**.
- **Exports go into the project's exports folder by default**, and the Mashup Studio saves into its mashups folder.
- **Move or back up the whole folder** and it opens complete, even if the original songs have moved or been deleted.
- **An unsaved mix uses a working folder** in the app's data folder. Saving moves its stems into the project folder and deletes the working folder, so nothing is left behind.
- **Save session as…** from a saved project copies the stems into the new project, so the original stays complete.
- **Closing an unsaved mix that has stems asks first**, because choosing *Discard* deletes them. Working folders left behind by a crash are cleaned up after two weeks.
- **Older sessions open as before.** The next save turns them into a project folder (the old `.lmm` stays where it was). Stems split by earlier versions in the old shared folder are still used, and they're copied into the project when you save.

## Clear the old stem cache
- **Settings → Clear the old stem cache…** deletes the stems that earlier versions kept in one shared folder and shows how much space it frees. Saved projects keep their own copies.

## Also new
- **Every song is levelled to the same loudness**, from its loudness measured when it's added. A quiet recording and a loud master now sit at the same volume in mixes (the range is now +15 to -20 dB, up from ±12) and in the **Mashup Studio** (new: **Play both songs at the same loudness**, on by default). Your files are never changed.

## Fixed
- **Stems for video files:** splitting a video file (mp4, mkv, mov…) failed with "not a recognized format". The app now takes the sound out and gives that to the stem engine. Other formats it can't open itself, like m4a, work too.
- **Video preview stuck on an old picture:** closing the video preview and opening it again showed a still frame from the first time. It now starts afresh from wherever the playhead is.

## Downloads
- **Windows, macOS, Linux:** the standard app.
- **-Stems** versions: the same, plus the stem engine (stem transitions, Mashup Studio, deep analysis) built in.
