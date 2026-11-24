# Lazy Mixtape Maker 6.2

## Project folders
Every mix now has its own **project folder**, and the stems split for its songs are kept in it.

- **Saving makes the project folder.** Choosing *Music/Sunday.lmm* saves *Music/Sunday/Sunday.lmm*, with a `stems` folder beside it holding each song's stems (and their deep analysis).
- **An unsaved mix uses a working folder** in the app's data folder. Saving moves its stems into the project folder and deletes the working folder, so nothing is left behind.
- **Opening a project finds its stems beside it.** Copy or move the whole folder (to another drive, or to a friend) and the stems go with it, so nothing needs splitting again.
- **Save session as…** from a saved project copies the stems into the new project, so the original stays complete.
- **Closing an unsaved mix that has stems asks first**, because choosing *Discard* deletes them. Working folders left behind by a crash are cleaned up after two weeks.
- **Older sessions open as before.** The next save turns them into a project folder (the old `.lmm` stays where it was). Stems split by earlier versions in the old shared folder are still used, and they're copied into the project when you save.

## Downloads
- **Windows, macOS, Linux:** the standard app.
- **-Stems** versions: the same, plus the stem engine (stem transitions, Mashup Studio, deep analysis) built in.
