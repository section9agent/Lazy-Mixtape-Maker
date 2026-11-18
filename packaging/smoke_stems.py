"""Check a packaged "with stems" app: split a short made-up song with the engine built into it.

    python packaging/smoke_stems.py <path to the packaged LazyMixtapeMaker program>

Runs the app's own command line (`LazyMixtapeMaker stems song.wav --out ...`), which starts the app again as
the stem worker, copies the packaged model into a fresh data folder and splits the song - all offline."""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import soundfile as sf


def main(app: str) -> int:
    work = Path(tempfile.mkdtemp(prefix="lmm_smoke_"))
    sr = 44100
    t = np.arange(int(12 * sr)) / sr
    beat = (np.sin(2 * np.pi * 55 * t) * (np.mod(t, 0.5) < 0.12)) * 0.5            # a thumping bass
    voice = np.sin(2 * np.pi * 440 * t + 3 * np.sin(2 * np.pi * 5 * t)) * 0.2       # a wavering "singer"
    hat = np.random.default_rng(1).standard_normal(len(t)) * (np.mod(t, 0.25) < 0.02) * 0.2
    song = work / "smoke song.wav"
    sf.write(str(song), np.stack([beat + voice + hat] * 2, axis=1), sr)
    env = dict(os.environ, LMM_DATA_DIR=str(work / "data"))
    for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
        env[k] = "http://127.0.0.1:9"                        # prove that no download is needed
    t0 = time.time()
    r = subprocess.run([app, "stems", str(song), "--out", str(work / "out")], env=env, timeout=1800,
                       capture_output=True, text=True)
    print("exit code", r.returncode, f"after {time.time() - t0:.0f} s")
    print(r.stdout[-2000:], r.stderr[-4000:])
    got = sorted(p.name for p in (work / "out" / "smoke song").glob("*.flac")) if (work / "out" / "smoke song").exists() else []
    print("stems:", got)
    for st in (work / "data" / "stems").glob("*/status.jsonl"):
        print(st.read_text()[-2000:])
    for st in (work / "data" / "stems").glob("*.part/status.jsonl"):
        print("worker said:", st.read_text()[-3000:])
    ok = got == ["bass.flac", "drums.flac", "other.flac", "vocals.flac"]
    if ok:
        y, _ = sf.read(str(work / "out" / "smoke song" / "vocals.flac"))
        print("vocals length", len(y) / sr, "s")
        ok = abs(len(y) / sr - 12) < 0.5
    if ok:
        # deep analysis (All-In-One) on the same song's stems, also offline
        t0 = time.time()
        r = subprocess.run([app, "deep", str(song)], env=env, timeout=1800, capture_output=True, text=True)
        print("deep: exit code", r.returncode, f"after {time.time() - t0:.0f} s")
        print(r.stdout[-2000:], r.stderr[-4000:])
        res = list((work / "data" / "stems").glob("*/deep.json"))
        for st in (work / "data" / "stems").glob("*/deep-status.jsonl"):
            print("deep worker said:", st.read_text()[-3000:])
        if not res:
            ok = False
            print("no deep analysis result")
        else:
            d = json.loads(res[0].read_text())
            print("deep result:", d.get("bpm"), "BPM,", len(d.get("beats", [])), "beats,",
                  [s["label"] for s in d.get("segments", [])])
            ok = r.returncode == 0 and len(d.get("beats", [])) > 4
    print("SMOKE TEST", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
