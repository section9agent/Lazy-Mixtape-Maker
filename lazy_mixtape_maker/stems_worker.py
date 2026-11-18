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


if __name__ == "__main__":
    sys.exit(main(sys.argv))
