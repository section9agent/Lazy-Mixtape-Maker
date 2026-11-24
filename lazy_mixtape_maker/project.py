"""Project folders.

Every mix lives in a project folder that holds the files made for it (its song stems, and their deep analysis):

    My Mix/
        My Mix.lmm        the session
        stems/<song>/     each song's stems

A new mix that hasn't been saved yet gets a *working* folder in the app's data folder (projects/). When it's
saved, a project folder named after the mix is made where the user chose, the stems move into it, and the
working folder is deleted. "Save as" from a saved project copies the stems, so the original stays whole.

Stems split by earlier versions sat in one shared folder (data/stems); they're still found, and copied into a
project when it's saved."""
from __future__ import annotations

import re
import shutil
import threading
import time
import uuid
from pathlib import Path

from .visuals import data_dir

STEMS = "stems"
LOCK = threading.RLock()            # held while stems are moved, so a finishing split never lands mid-move
_current: Path | None = None


def working_root() -> Path:
    """Where the working folders of unsaved mixes live."""
    return data_dir() / "projects"


def legacy_stems() -> Path:
    """The shared stems folder of versions before 6.2."""
    return data_dir() / "stems"


def _slug(name: str) -> str:
    s = re.sub(r"[^\w\- ]+", "", name or "").strip()[:40].strip()
    return s or "mix"


def new_working(name: str = "Untitled mixtape") -> Path:
    """A fresh working folder for a mix that hasn't been saved yet (and makes it the current project)."""
    d = working_root() / f"{_slug(name)}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    (d / STEMS).mkdir(parents=True, exist_ok=True)
    set_current(d)
    return d


def current() -> Path | None:
    return _current


def set_current(folder) -> None:
    global _current
    with LOCK:
        _current = Path(folder) if folder else None


def is_working(folder) -> bool:
    """True for a working folder the app made (as opposed to a project the user saved)."""
    if folder is None:
        return False
    try:
        Path(folder).resolve().relative_to(working_root().resolve())
        return True
    except ValueError:
        return False


def stems_root(folder=None) -> Path:
    """The stems folder of a project (the current one by default; the old shared folder when there's none)."""
    f = Path(folder) if folder else _current
    return f / STEMS if f is not None else legacy_stems()


def folder_for(lmm: Path) -> tuple[Path, Path]:
    """Where saving to `lmm` really puts things: (session file, project folder).

    A file chosen inside a folder of the same name, or inside an existing project folder (one with stems/),
    stays put;
    otherwise a project folder named after it is made beside it: Music/My Mix.lmm -> Music/My Mix/My Mix.lmm"""
    lmm = Path(lmm)
    parent = lmm.parent
    if parent.name == lmm.stem or (parent / STEMS).is_dir():
        return lmm, parent
    folder = parent / lmm.stem
    return folder / lmm.name, folder


def _merge_move(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if target.exists():
            continue                     # already there (the destination's copy wins)
        shutil.move(str(item), str(target))


def _merge_copy(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if target.exists() or item.name.endswith(".part"):
            continue
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def move_to(new_folder, song_ids=None) -> Path:
    """Make `new_folder` the current project, taking the stems along.

    From a working folder they're moved and the working folder is deleted; from a saved project they're copied
    (that project keeps its own). Stems in the old shared folder for `song_ids` are copied in too."""
    new_folder = Path(new_folder)
    with LOCK:
        old = _current
        (new_folder / STEMS).mkdir(parents=True, exist_ok=True)
        if old is not None and old.resolve() != new_folder.resolve() and (old / STEMS).is_dir():
            if is_working(old):
                _merge_move(old / STEMS, new_folder / STEMS)
            else:
                _merge_copy(old / STEMS, new_folder / STEMS)
        if song_ids:
            adopt_legacy(song_ids, new_folder)
        if old is not None and old.resolve() != new_folder.resolve() and is_working(old):
            shutil.rmtree(old, ignore_errors=True)
        set_current(new_folder)
    return new_folder


def adopt_legacy(song_ids, folder) -> int:
    """Copy stems from the old shared folder into a project. Returns how many songs were copied."""
    n = 0
    dst = Path(folder) / STEMS
    for sid in song_ids:
        src = legacy_stems() / sid
        if (src / "stems.json").exists() and not (dst / sid / "stems.json").exists():
            shutil.rmtree(dst / sid, ignore_errors=True)
            shutil.copytree(src, dst / sid, ignore=shutil.ignore_patterns("*.part"))
            n += 1
    return n


def discard_working() -> None:
    """Forget the current mix's working folder (its mix was closed without saving)."""
    with LOCK:
        if _current is not None and is_working(_current):
            shutil.rmtree(_current, ignore_errors=True)
        set_current(None)


def clean_old_working(keep=None, days: float = 14.0) -> int:
    """Delete working folders left behind (by a crash, say) that haven't been touched for `days` days."""
    root = working_root()
    if not root.is_dir():
        return 0
    keep = Path(keep).resolve() if keep else None
    cutoff = time.time() - days * 86400
    n = 0
    for d in root.iterdir():
        if not d.is_dir() or (keep and d.resolve() == keep):
            continue
        try:
            newest = max([d.stat().st_mtime] + [f.stat().st_mtime for f in d.rglob("*")])
        except OSError:
            continue
        if newest < cutoff:
            shutil.rmtree(d, ignore_errors=True)
            n += 1
    return n


def size(folder=None) -> int:
    root = stems_root(folder)
    return sum(f.stat().st_size for f in root.rglob("*") if f.is_file()) if root.exists() else 0
