"""Deep analysis: All-In-One (Taejun Kim & Juhan Nam, via the all-in-one-infer package) run on a song's stems.

It finds the tempo, beats, downbeats and the song's parts (intro, verse, chorus, bridge, outro ...) with a
neural network trained on the Harmonix Set. It needs the song's stems, so it comes with the stem engine (the
"with stems" download). The result is kept beside the stems, and the app's own analysis is never thrown
away: per song you choose which one the mix uses, and can switch back at any time."""
from __future__ import annotations

import importlib.util
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

from . import stems
from .analysis import Section, SongAnalysis
from .visuals import data_dir

FIELDS = ("bpm", "beat_period", "grid_origin", "sections")     # what deep analysis changes in a song's analysis
LABELS = {"intro": "intro", "outro": "outro", "verse": "verse", "chorus": "chorus", "bridge": "bridge",
          "inst": "bridge", "solo": "bridge", "break": "break"}
_AVAILABLE: dict[str, bool] = {}


class DeepError(RuntimeError):
    pass


# ------------------------------------------------------------------ the engine
def available() -> bool:
    """Can this computer run deep analysis (stem engine with all-in-one-infer)?"""
    py = stems.engine_python()
    if py is None:
        return False
    if py not in _AVAILABLE:
        if py == stems.BUILT_IN or py == sys.executable:
            try:
                ok = importlib.util.find_spec("allin1_infer") is not None
            except (ImportError, ValueError):
                ok = False
        else:
            try:
                ok = subprocess.run([py, "-c", "import allin1_infer"], capture_output=True, timeout=120).returncode == 0
            except (OSError, subprocess.SubprocessError):
                ok = False
        _AVAILABLE[py] = ok
    return _AVAILABLE[py]


def bundled_models() -> Path | None:
    base = getattr(sys, "_MEIPASS", None)
    p = Path(base) / "deep-models" if base else None
    return p if p and p.is_dir() else None


def models_dir() -> Path:
    """Where the model files are kept; the packaged ones are copied there the first time (no download needed)."""
    d = data_dir() / "deep-models"
    src = bundled_models()
    if src is not None and not (d / "models--taejunkim--allinone").exists():
        part = d.with_name(d.name + ".part")
        shutil.rmtree(part, ignore_errors=True)
        shutil.copytree(src, part, symlinks=False)
        if d.exists():
            for f in part.iterdir():
                shutil.move(str(f), str(d / f.name))
            shutil.rmtree(part, ignore_errors=True)
        else:
            part.rename(d)
    d.mkdir(parents=True, exist_ok=True)
    return d


# -------------------------------------------------------------------- results
def result_file(song_id: str) -> Path:
    return stems.song_dir(song_id) / "deep.json"


def cached(song_id: str) -> dict | None:
    try:
        return json.loads(result_file(song_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def run(path, song_id: str, progress=None, cancel=None, force: bool = False, runner=None) -> dict:
    """Deep-analyse a song that has been split into stems (or return the stored result)."""
    if not force:
        hit = cached(song_id)
        if hit:
            return hit
    if not stems.cached(song_id):
        raise DeepError("Split the song into stems first.")
    py = stems.engine_python()
    if py is None or not available():
        raise DeepError("Deep analysis needs the \"with stems\" download of the app.")
    out = result_file(song_id)
    status = stems.song_dir(song_id) / "deep-status.jsonl"
    cmd = stems.worker_command(py) + ["deep", str(stems.song_dir(song_id)), str(out), str(models_dir())]
    try:
        (runner or stems._run_worker)(cmd, progress, cancel, status)
    except stems.StemsError as e:
        raise DeepError(str(e)) from None
    finally:
        status.unlink(missing_ok=True)
    res = cached(song_id)
    if not res:
        raise DeepError("The deep analysis didn't finish.")
    return res


# -------------------------------------------------------- into the app's terms
def _fold(bpm: float) -> float:
    while bpm < 80.0:
        bpm *= 2.0
    while bpm >= 160.0:
        bpm /= 2.0
    return bpm


def to_fields(an: SongAnalysis, deep: dict) -> dict:
    """The deep result as values for the song's analysis: tempo, beat grid and parts."""
    beats = np.asarray(deep.get("beats") or [], float)
    downs = np.asarray(deep.get("downbeats") or [], float)
    if len(beats) >= 4:
        raw = 60.0 / float(np.median(np.diff(beats)))
    else:
        raw = float(deep.get("bpm") or an.bpm)
    bpm = _fold(raw)
    period = 60.0 / bpm
    bar = 4 * period
    ref = downs if len(downs) else beats[:1] if len(beats) else np.array([an.grid_origin])
    d0 = float(ref[0])
    resid = ref - (d0 + np.round((ref - d0) / bar) * bar)
    origin = (d0 + float(np.median(resid))) % bar
    secs = []
    for s in deep.get("segments") or []:
        lab = LABELS.get(str(s.get("label", "")).lower())
        if lab is None:                                  # "start" / "end": silence before and after the song
            continue
        a, b = max(0.0, float(s["start"])), min(an.duration or 1e9, float(s["end"]))
        if b - a < 0.5:
            continue
        if secs and secs[-1].label == lab and abs(secs[-1].end - a) < 0.5:
            secs[-1].end = b
        else:
            secs.append(Section(start=a, end=b, label=lab))
    be = np.asarray(an.bar_energy or [], float)
    for sec in secs:                                     # energy from the app's own measurement of the song
        if len(be) and an.bar_length > 0:
            i0 = int(max(0, (sec.start - an.bar_energy_origin) // an.bar_length))
            i1 = int(max(i0 + 1, math.ceil((sec.end - an.bar_energy_origin) / an.bar_length)))
            sec.energy = float(be[i0:i1].mean()) if be[i0:i1].size else 0.5
        else:
            sec.energy = 0.5
    if not secs:
        secs = [Section(start=an.audio_start, end=an.audio_end or an.duration, label="full", energy=0.5)]
    return {"bpm": bpm, "beat_period": period, "grid_origin": origin, "sections": secs}


def summary(an: SongAnalysis, sections=None, bpm=None, origin=None) -> str:
    """One line describing an analysis: tempo, first downbeat and parts."""
    bpm = an.bpm if bpm is None else bpm
    origin = an.grid_origin if origin is None else origin
    sections = an.sections if sections is None else sections
    first = origin
    bar = 240.0 / bpm
    while first - bar >= -0.01:
        first -= bar
    while first < -0.01:
        first += bar
    parts = " · ".join(f"{s.label} {int(s.start // 60)}:{int(s.start % 60):02d}" for s in sections[:12])
    return f"{bpm:.1f} BPM, first downbeat {first:.2f} s  |  {parts}"


# ----------------------------------------------------------- using / reverting
def in_use(extra: dict, song_id: str) -> bool:
    return song_id in extra.get("deep_orig", {})


def use(lib: dict, extra: dict, song_id: str, on: bool) -> bool:
    """Switch a song between the app's analysis and the deep one. Returns whether anything changed."""
    an = lib[song_id]
    orig = extra.setdefault("deep_orig", {})
    if on:
        if song_id in orig:
            return False
        deep = cached(song_id)
        if not deep:
            raise DeepError("This song hasn't had a deep analysis yet.")
        orig[song_id] = {"bpm": an.bpm, "beat_period": an.beat_period, "grid_origin": an.grid_origin,
                         "sections": [{"start": s.start, "end": s.end, "label": s.label, "energy": s.energy} for s in an.sections]}
        for k, v in to_fields(an, deep).items():
            setattr(an, k, v)
        return True
    if song_id not in orig:
        return False
    o = orig.pop(song_id)
    an.bpm, an.beat_period, an.grid_origin = o["bpm"], o["beat_period"], o["grid_origin"]
    an.sections = [Section(**s) for s in o["sections"]]
    if not orig:
        extra.pop("deep_orig", None)
    return True
