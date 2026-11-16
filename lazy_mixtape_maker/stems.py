"""Optional add-on: split a song into stems (drums, bass, vocals, other).

The splitting itself is done by the `audio-separator` package (which runs Meta's Demucs model with PyTorch).
That is far too big to ship inside the app, so it is optional: this module looks for a Python that has it
installed, runs stems_worker.py with it as a separate process, and keeps the result in a per-song cache so a
song is only ever split once. Nothing here is imported by the rest of the app unless stems are asked for."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import prefs
from .audio_io import file_id
from .visuals import data_dir

STEMS = ("drums", "bass", "vocals", "other")
MODEL = "htdemucs.yaml"            # Demucs v4, four stems; ~80 MB, downloaded the first time
SHIFTS = 1                         # 1 = fastest; 2 is slightly cleaner and takes twice as long
INSTALL_HINT = ("Stem splitting is an optional add-on. Install it into a Python on this computer with\n"
                "    pip install \"audio-separator[cpu]\"\n"
                "then tell the app which Python that is:\n"
                "    python -m lazy_mixtape_maker stems --python /path/to/python\n"
                "(or set the LMM_STEMS_PYTHON environment variable).")


class StemsUnavailable(RuntimeError):
    pass


class StemsError(RuntimeError):
    pass


# ------------------------------------------------------------------ the engine
def engine_python() -> str | None:
    """The Python that has the stem engine: LMM_STEMS_PYTHON, the saved choice, or this one."""
    for cand in (os.environ.get("LMM_STEMS_PYTHON"), prefs.get("stems_python")):
        if cand and Path(cand).exists():
            return str(cand)
    if not getattr(sys, "frozen", False) and importlib.util.find_spec("audio_separator") is not None:
        return sys.executable
    return None


def set_engine_python(path: str) -> None:
    if not Path(path).exists():
        raise StemsError(f"{path} doesn't exist.")
    r = subprocess.run([path, "-c", "import audio_separator"], capture_output=True, text=True)
    if r.returncode != 0:
        raise StemsError(f"That Python doesn't have audio-separator installed.\n{INSTALL_HINT}")
    prefs.set("stems_python", str(path))


def available() -> bool:
    return engine_python() is not None


# -------------------------------------------------------------------- the cache
def cache_root() -> Path:
    return data_dir() / "stems"


def models_dir() -> Path:
    return data_dir() / "stems-models"


def song_dir(song_id: str) -> Path:
    return cache_root() / song_id


def cached(song_id: str) -> dict[str, Path] | None:
    """The stems of a song that has already been split, or None."""
    d = song_dir(song_id)
    try:
        meta = json.loads((d / "stems.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    out = {s: d / f"{s}.flac" for s in meta.get("stems", [])}
    return out if out and all(p.exists() for p in out.values()) else None


def forget(song_id: str) -> None:
    shutil.rmtree(song_dir(song_id), ignore_errors=True)


def cache_size() -> int:
    return sum(f.stat().st_size for f in cache_root().rglob("*") if f.is_file()) if cache_root().exists() else 0


# ------------------------------------------------------------------- splitting
def _run_worker(cmd, progress, cancel):
    """Run the worker, passing its progress on. Returns the final "done" message."""
    kw = {"creationflags": 0x08000000} if sys.platform == "win32" else {}           # no console window
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", **kw)
    done = None
    try:
        for line in p.stdout:
            if cancel and cancel():
                p.kill()
                raise StemsError("Cancelled")
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("event") == "progress" and progress:
                progress(float(msg.get("fraction", 0.0)))
            elif msg.get("event") == "error":
                raise StemsError(msg.get("message", "The stem engine failed."))
            elif msg.get("event") == "done":
                done = msg
        p.wait()
    finally:
        if p.poll() is None:
            p.kill()
    if done is None:
        raise StemsError("The stem engine stopped without finishing.")
    return done


def split(path, song_id: str | None = None, progress=None, cancel=None, force: bool = False, runner=_run_worker,
          shifts: int = SHIFTS) -> dict[str, Path]:
    """Split `path` into stems (or return the cached ones). progress(fraction 0..1), cancel() -> bool."""
    path = Path(path)
    song_id = song_id or file_id(path)
    if not force:
        hit = cached(song_id)
        if hit:
            return hit
    py = engine_python()
    if py is None:
        raise StemsUnavailable(INSTALL_HINT)
    final = song_dir(song_id)
    work = final.with_name(final.name + ".part")              # an interrupted split never looks finished
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    worker = Path(__file__).with_name("stems_worker.py")
    try:
        done = runner([py, str(worker), str(path), str(work), str(models_dir()), MODEL, str(shifts)], progress, cancel)
        got = sorted(s for s in done.get("stems", {}) if (work / f"{s}.flac").exists())
        if not got:
            raise StemsError("The stem engine produced no stems.")
        (work / "stems.json").write_text(json.dumps({"stems": got, "model": MODEL, "shifts": shifts, "source": path.name,
                                                     "seconds": done.get("seconds")}), encoding="utf-8")
        shutil.rmtree(final, ignore_errors=True)
        work.rename(final)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    return cached(song_id) or {}


def load(song_id: str, stem: str, sr: int | None = None):
    """A stem as float32 audio (frames, channels) at `sr` (default: as stored)."""
    import numpy as np
    import soundfile as sf

    hit = cached(song_id)
    if not hit or stem not in hit:
        raise StemsError(f"No '{stem}' stem for this song yet.")
    y, file_sr = sf.read(str(hit[stem]), dtype="float32", always_2d=True)
    if sr and sr != file_sr:
        from scipy.signal import resample_poly
        from math import gcd
        g = gcd(int(sr), int(file_sr))
        y = resample_poly(y, sr // g, file_sr // g, axis=0).astype(np.float32)
    return y
