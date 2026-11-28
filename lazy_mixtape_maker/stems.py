"""Split a song into stems (drums, bass, vocals, other).

The splitting itself is done by the `audio-separator` package (which runs Meta's Demucs model with PyTorch).
The "with stems" download of the app has it built in (with the model, so it works offline); the normal
download doesn't, but can use a Python on the computer that has it installed. Either way it runs as a
separate process (the built-in engine is the app itself, started with --stems-worker), and the results are
kept in a per-song cache so a song is only ever split once."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import prefs
from .audio_io import file_id
from .visuals import data_dir

STEMS = ("drums", "bass", "vocals", "other")
MODEL = "htdemucs.yaml"            # Demucs v4, four stems; ~80 MB, downloaded the first time
SHIFTS = 1                         # 1 = fastest; 2 is slightly cleaner and takes twice as long
INSTALL_HINT = ("This copy of the app doesn't include the stem engine. The easiest way to get it is the\n"
                "\"with stems\" download (LazyMixtapeMaker-...-Stems) from the releases page.\n\n"
                "Or install it into a Python on this computer with\n"
                "    pip install \"audio-separator[cpu]\"\n"
                "then tell the app which Python that is:\n"
                "    python -m lazy_mixtape_maker stems --python /path/to/python\n"
                "(or set the LMM_STEMS_PYTHON environment variable).")


class StemsUnavailable(RuntimeError):
    pass


class StemsError(RuntimeError):
    pass


# ------------------------------------------------------------------ the engine
BUILT_IN = "built-in"


def built_in() -> bool:
    """Is the stem engine packaged inside this copy of the app (the "with stems" download)?"""
    if not getattr(sys, "frozen", False):
        return False
    try:
        return importlib.util.find_spec("audio_separator") is not None
    except (ImportError, ValueError):
        return False


def engine_python() -> str | None:
    """Where the stem engine is: LMM_STEMS_PYTHON, the saved choice, built into the app ("built-in"),
    or this Python when it has the package."""
    for cand in (os.environ.get("LMM_STEMS_PYTHON"), prefs.get("stems_python")):
        if cand and Path(cand).exists():
            return str(cand)
    if built_in():
        return BUILT_IN
    if not getattr(sys, "frozen", False) and importlib.util.find_spec("audio_separator") is not None:
        return sys.executable
    return None


def worker_command(py: str) -> list[str]:
    """The start of the command that runs the worker with the engine `py`."""
    if py == BUILT_IN:
        return [sys.executable, "--stems-worker"]
    return [py, str(Path(__file__).with_name("stems_worker.py"))]


def set_engine_python(path: str) -> None:
    """Use the stem engine installed in the Python at `path` (remembered)."""
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
    """Where new stems go: the current project's stems folder (see project.py)."""
    from . import project
    return project.stems_root()


def bundled_models() -> Path | None:
    """The model files packaged with the "with stems" download, if any."""
    base = getattr(sys, "_MEIPASS", None)
    p = Path(base) / "stems-models" if base else None
    return p if p and (p / MODEL).exists() else None


def models_dir() -> Path:
    """Where the engine keeps its model. The packaged model is copied there the first time (the engine wants
    a folder it can write to), so splitting never needs the internet."""
    d = data_dir() / "stems-models"
    src = bundled_models()
    if src is not None and not (d / MODEL).exists():
        d.mkdir(parents=True, exist_ok=True)
        for f in src.iterdir():
            if f.is_file() and not (d / f.name).exists():
                shutil.copyfile(f, d / (f.name + ".part"))
                os.replace(d / (f.name + ".part"), d / f.name)
    return d


def song_dir(song_id: str) -> Path:
    """A song's stems folder: in the current project, or (stems split by versions before 6.2) the old shared
    folder when only that has them."""
    from . import project
    d = cache_root() / song_id
    if not (d / "stems.json").exists():
        old = project.legacy_stems() / song_id
        if old != d and (old / "stems.json").exists():
            return old
    return d


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
def _run_worker(cmd, progress, cancel, status: Path | None = None):
    """Run the worker, passing its progress on. Returns the final "done" message.

    The worker writes its messages (one JSON object per line) to a status file rather than to a pipe: the
    packaged app is a windowed program, and on Windows such a program may have no usable standard output."""
    import time

    status = Path(status or Path(cmd[-4]) / "status.jsonl")      # cmd[-4] is the output folder
    status.parent.mkdir(parents=True, exist_ok=True)
    status.write_text("", encoding="utf-8")
    kw = {"creationflags": 0x08000000} if sys.platform == "win32" else {}           # no console window
    env = dict(os.environ, LMM_STEMS_STATUS=str(status))
    try:
        from .audio_io import ffmpeg
        env["LMM_FFMPEG"] = ffmpeg()                     # the engine needs ffmpeg; the app has its own copy
    except Exception:  # noqa: BLE001
        pass
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, **kw)
    done, pos, buf = None, 0, ""
    try:
        while True:
            finished = p.poll() is not None
            if cancel and cancel():
                p.kill()
                raise StemsError("Cancelled")
            with open(status, "r", encoding="utf-8") as f:
                f.seek(pos)
                buf += f.read()
                pos = f.tell()
            *lines, buf = buf.split("\n")
            for line in lines:
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
            if finished:
                break
            time.sleep(0.2)
    finally:
        if p.poll() is None:
            p.kill()
    if done is None:
        raise StemsError(f"The stem engine stopped without finishing (exit code {p.returncode}).")
    return done


ENGINE_READS = {".wav", ".flac", ".mp3", ".ogg"}     # what the stem engine opens by itself


def engine_input(path: Path, work: Path, cancel=None) -> Path:
    """The file to give the stem engine: the song itself when the engine can read it; otherwise (a video file,
    .m4a, ...) its sound, taken out with the app's own ffmpeg as a WAV file in `work`."""
    if path.suffix.lower() in ENGINE_READS:
        return path
    import subprocess
    from .audio_io import ffmpeg
    out = work / "source.wav"
    cmd = [ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(path),
           "-map", "0:a:0", "-vn", "-sn", "-dn", "-ac", "2", "-ar", "44100", "-c:a", "pcm_f32le", str(out)]
    kw = {"creationflags": 0x08000000} if sys.platform == "win32" else {}      # (no console window on Windows)
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **kw)
    while proc.poll() is None:
        if cancel and cancel():
            proc.kill()
            raise StemsError("Cancelled")
        time.sleep(0.1)
    err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
    if proc.returncode != 0 or not out.exists() or out.stat().st_size < 1024:
        raise StemsError(f"Couldn't take the sound out of {path.name} for the stem engine: "
                         f"{err.strip()[-300:] or 'it has no audio track'}")
    return out


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
    # (made outside the project folder, which may be saved elsewhere - and moved - while this runs)
    work = data_dir() / "stems-work" / (song_id + ".part")    # an interrupted split never looks finished
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        src = engine_input(path, work, cancel)
        done = runner(worker_command(py) + [str(src), str(work), str(models_dir()), MODEL, str(shifts)], progress, cancel)
        (work / "status.jsonl").unlink(missing_ok=True)
        if src != path:
            src.unlink(missing_ok=True)
        got = sorted(s for s in done.get("stems", {}) if (work / f"{s}.flac").exists())
        if not got:
            raise StemsError("The stem engine produced no stems.")
        (work / "stems.json").write_text(json.dumps({"stems": got, "model": MODEL, "shifts": shifts, "source": path.name,
                                                     "seconds": done.get("seconds")}), encoding="utf-8")
        from . import project
        with project.LOCK:                                    # into whichever project is open now
            final = cache_root() / song_id
            final.parent.mkdir(parents=True, exist_ok=True)
            shutil.rmtree(final, ignore_errors=True)
            shutil.move(str(work), str(final))
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    return cached(song_id) or {}


def measure_lag(path, stem_paths, sr: int = 44100) -> float:
    """Seconds the stems run behind (+) or ahead of (-) the app's own decoding of the song.

    The engine and the app read compressed files with different decoders, which can disagree by a few
    hundredths of a second (MP3 encoder delay). Stem transitions subtract a stem from the song, so the two
    must line up to the sample; this finds the offset by comparing a stretch of the song with its stems."""
    import numpy as np

    from .audio_io import decode
    try:
        from .studio import probe_duration
        dur = probe_duration(path)
    except Exception:  # noqa: BLE001
        dur = 60.0
    start = max(0.0, min(30.0, dur * 0.25))
    span = max(2.0, min(30.0, dur - start - 0.5))
    x = decode(path, sr=sr, channels=1, start=start, duration=span)[0]
    s = None
    for p in stem_paths:
        y = decode(p, sr=sr, channels=1, start=start, duration=span)[0]
        n = min(len(x), len(y)) if s is None else min(len(s), len(y))
        s = y[:n] if s is None else s[:n] + y[:n]
    n = min(len(x), len(s))
    if n < sr // 2:
        return 0.0
    x, s = x[:n], s[:n]
    size = 1 << int(np.ceil(np.log2(2 * n)))
    c = np.fft.irfft(np.conj(np.fft.rfft(x, size)) * np.fft.rfft(s, size), size)      # c[k] = sum x[n] * s[n + k]
    reach = int(0.25 * sr)
    cand = np.concatenate([c[-reach:], c[:reach + 1]])
    k = int(np.argmax(cand)) - reach
    if cand.max() <= 0:
        return 0.0
    return k / sr


def lag(song_id: str, path) -> float:
    """The stored offset of a song's stems (measured and remembered the first time it is needed)."""
    d = song_dir(song_id)
    try:
        meta = json.loads((d / "stems.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0.0
    if "lag" not in meta:
        hit = cached(song_id) or {}
        try:
            meta["lag"] = measure_lag(path, list(hit.values())) if hit else 0.0
            (d / "stems.json").write_text(json.dumps(meta), encoding="utf-8")
        except Exception:  # noqa: BLE001
            return 0.0
    return float(meta.get("lag") or 0.0)


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
