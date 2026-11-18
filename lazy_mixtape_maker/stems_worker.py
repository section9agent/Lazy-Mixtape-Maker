"""Runs the stem splitter. Started as a separate process by stems.py, with the Python that has the
`audio-separator` package installed - so this file must not import anything from the app itself.

    python stems_worker.py <song> <output folder> <models folder> <model> <shifts>

The packaged "with stems" app runs it as itself:  LazyMixtapeMaker --stems-worker <song> ...

Writes one JSON object per line - {"event": "start"|"progress"|"done"|"error", ...} - to the file named by
the LMM_STEMS_STATUS environment variable (or to standard output when that isn't set)."""
import json
import logging
import os
import sys
import time


def say(**kw):
    line = json.dumps(kw)
    status = os.environ.get("LMM_STEMS_STATUS")
    if status:
        with open(status, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    elif sys.stdout is not None:
        print(line, flush=True)


def ensure_ffmpeg(bin_dir):
    """The engine insists on a program called "ffmpeg" on the PATH. When there isn't one, put the copy of
    ffmpeg that comes with the app (or with imageio-ffmpeg) there under that name."""
    import shutil
    if shutil.which("ffmpeg"):
        return
    src = os.environ.get("LMM_FFMPEG")
    if not src or not os.path.exists(src):
        try:
            import imageio_ffmpeg
            src = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:  # noqa: BLE001
            return
    os.makedirs(bin_dir, exist_ok=True)
    dst = os.path.join(bin_dir, "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(src):
        tmp = dst + ".part"
        try:
            if sys.platform == "win32":
                shutil.copyfile(src, tmp)
            else:
                if os.path.lexists(tmp):
                    os.remove(tmp)
                os.symlink(src, tmp)
            os.replace(tmp, dst)
        except OSError:
            shutil.copyfile(src, tmp)
            os.replace(tmp, dst)
        if sys.platform != "win32":
            try:
                os.chmod(src, os.stat(src).st_mode | 0o111)
            except OSError:
                pass
    os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")


def main(argv):
    if len(argv) < 6:
        say(event="error", message="usage: stems_worker <song> <output folder> <models folder> <model> <shifts>")
        return 2
    song, out, models, model, shifts = argv[1], argv[2], argv[3], argv[4], int(argv[5])
    for name in ("stdout", "stderr"):                        # a windowed program may have neither
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w"))
    try:
        from audio_separator.separator import Separator
    except Exception as e:  # noqa: BLE001
        say(event="error", message=f"The stem engine isn't installed in this Python ({e}).")
        return 2
    os.makedirs(out, exist_ok=True)
    os.makedirs(models, exist_ok=True)
    ensure_ffmpeg(os.path.join(os.path.dirname(os.path.abspath(models)), "stems-bin"))
    try:
        import tqdm as _tqdm                                    # report the engine's own progress bar as JSON lines

        class Bar(_tqdm.tqdm):
            passes = [0]

            def __init__(self, *a, **k):
                k["disable"] = False
                k["file"] = open(os.devnull, "w")
                super().__init__(*a, **k)
                Bar.passes[0] += 1
                self._pass = Bar.passes[0]

            def update(self, n=1):
                r = super().update(n)
                if self.total:
                    say(event="progress", fraction=min(1.0, ((self._pass - 1) + self.n / self.total) / max(1, shifts)))
                return r
        _tqdm.tqdm = Bar
        try:
            import tqdm.auto as _auto
            _auto.tqdm = Bar
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        pass
    t0 = time.time()
    say(event="start", model=model)
    try:
        sep = Separator(model_file_dir=models, output_dir=out, output_format="FLAC", log_level=logging.ERROR,
                        demucs_params={"segment_size": "Default", "shifts": shifts, "overlap": 0.25, "segments_enabled": True})
        sep.load_model(model)
        files = sep.separate(song)
    except Exception as e:  # noqa: BLE001
        say(event="error", message=str(e)[:500])
        return 1
    stems = {}
    for f in files:
        name = os.path.basename(f)
        if "(" in name and ")" in name:
            stem = name.split("(")[-1].split(")")[0].strip().lower()
            dst = os.path.join(out, stem + ".flac")
            src = f if os.path.isabs(f) else os.path.join(out, name)
            os.replace(src, dst)
            stems[stem] = dst
    say(event="done", stems=stems, seconds=round(time.time() - t0, 1))
    return 0


def deep_main(argv):
    """Deep analysis with All-In-One (allin1_infer) on a song's stems:

        stems_worker deep <stems folder> <result .json> <models folder>

    Finds the tempo, beats, downbeats and the song's parts (intro, verse, chorus, ...)."""
    if len(argv) < 4:
        say(event="error", message="usage: stems_worker deep <stems folder> <result .json> <models folder>")
        return 2
    stems_dir, out_json, models = argv[1], argv[2], argv[3]
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w"))
    os.makedirs(models, exist_ok=True)
    os.environ["HF_HUB_CACHE"] = models                       # where the model files are kept
    if os.path.isdir(os.path.join(models, "models--taejunkim--allinone")):
        os.environ["HF_HUB_OFFLINE"] = "1"                    # they're here: never go online
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("MPLBACKEND", "Agg")                 # its (unused) plotting must not look for a screen
    t0 = time.time()
    say(event="start")
    try:
        import types
        try:
            import torchaudio  # noqa: F401
        except Exception:  # noqa: BLE001 - only needed for MP3 input and Demucs, which aren't used here
            sys.modules["torchaudio"] = types.ModuleType("torchaudio")
        from allin1_infer import analyze
        from allin1_infer.stems_input import StemsInput
    except Exception as e:  # noqa: BLE001
        say(event="error", message=f"The deep analysis engine isn't installed in this Python ({e}).")
        return 2
    import tempfile
    import soundfile as sf
    say(event="progress", fraction=0.05)
    try:
        with tempfile.TemporaryDirectory(prefix="lmm_deep_") as tmp:
            files = {}
            for s in ("bass", "drums", "other", "vocals"):
                y, sr = sf.read(os.path.join(stems_dir, s + ".flac"), dtype="float32")
                files[s] = os.path.join(tmp, s + ".wav")
                sf.write(files[s], y, sr)
            say(event="progress", fraction=0.2)
            r = analyze(stems_input=StemsInput(**files, identifier="song"), model="harmonix-all", device="cpu",
                        demix_dir=os.path.join(tmp, "demix"), spec_dir=os.path.join(tmp, "spec"), multiprocess=False)
            r = r[0] if isinstance(r, list) else r
    except Exception as e:  # noqa: BLE001
        say(event="error", message=str(e)[:500])
        return 1
    res = {"bpm": float(r.bpm), "beats": [float(x) for x in r.beats], "downbeats": [float(x) for x in r.downbeats],
           "beat_positions": [int(x) for x in r.beat_positions],
           "segments": [{"start": float(s.start), "end": float(s.end), "label": str(s.label)} for s in r.segments],
           "model": "harmonix-all", "seconds": round(time.time() - t0, 1)}
    tmp_out = out_json + ".part"
    with open(tmp_out, "w", encoding="utf-8") as f:
        json.dump(res, f)
    os.replace(tmp_out, out_json)
    say(event="done", stems={}, seconds=res["seconds"])
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "deep":
        sys.exit(deep_main(sys.argv[1:]))
    sys.exit(main(sys.argv))
