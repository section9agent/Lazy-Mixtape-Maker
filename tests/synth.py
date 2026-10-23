"""Generate structured fake songs (drums + bass + chords + lead) with a known
tempo and key, so analysis and mixing can be tested without any real music."""
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 44100
SEMI = lambda f0, n: f0 * 2 ** (n / 12)
C0 = 16.3516


def _env(n, a=0.005, d=0.2):
    t = np.arange(n) / SR
    return np.minimum(t / a, 1) * np.exp(-t / d)


def _rng_noise(n):
    return np.random.default_rng(7).standard_normal(n) * np.linspace(1, 0.3, n)


def kick(n=SR // 3):
    t = np.arange(n) / SR
    f = 50 + 120 * np.exp(-t * 30)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 11)


def hat(n=SR // 12):
    rng = np.random.default_rng(0)
    return rng.standard_normal(n) * np.exp(-np.arange(n) / SR * 90) * 0.25


def snare(n=SR // 5):
    rng = np.random.default_rng(1)
    t = np.arange(n) / SR
    return (rng.standard_normal(n) * 0.6 + np.sin(2 * np.pi * 190 * t) * 0.4) * np.exp(-t * 22)


def tone(freq, n, kind="saw"):
    t = np.arange(n) / SR
    if kind == "saw":
        return 2 * ((t * freq) % 1.0) - 1
    return np.sin(2 * np.pi * freq * t)


def make_song(path, bpm=120.0, root=0, minor=True, lead_in=0.0, structure=None, fmt="wav", tags=None):
    """root: pitch class 0-11. structure: list of (name, bars)."""
    structure = structure or [("intro", 8), ("verse", 16), ("chorus", 16), ("verse", 16), ("chorus", 16), ("outro", 8)]
    beat = 60.0 / bpm
    bar = 4 * beat
    total_bars = sum(b for _, b in structure)
    n_total = int((total_bars * bar + lead_in + 1.5) * SR)
    out = np.zeros(n_total)
    # chord progression (semitones from root): i - VI - III - VII  /  I - V - vi - IV
    prog = [0, 8, 3, 10] if minor else [0, 7, 9, 5]
    third = 3 if minor else 4
    pos_bar = 0
    for name, bars in structure:
        for b in range(bars):
            t0 = lead_in + (pos_bar + b) * bar
            i0 = int(t0 * SR)
            chord_root = (root + prog[(pos_bar + b) % 4]) % 12
            nbar = int(bar * SR)
            seg = np.zeros(nbar)
            level = {"intro": 0.5, "verse": 0.7, "chorus": 1.0, "outro": 0.5}[name]
            for iv in (0, third, 7):  # pad chord
                f = SEMI(C0 * 8, chord_root + iv)
                seg += tone(f, nbar, "saw") * 0.05 * level
            if name != "intro":
                for q in range(8):  # bass eighths
                    nn = int(beat / 2 * SR)
                    f = SEMI(C0 * 2, chord_root)
                    seg[q * nn:(q + 1) * nn] += tone(f, nn, "sine")[:nn] * _env(nn, 0.003, 0.25) * 0.35 * level
            if name == "chorus":
                for iv in (0, third, 7):  # octave-up pad layer + wider sound
                    seg += tone(SEMI(C0 * 16, chord_root + iv), nbar, "saw") * 0.07
                seg += _rng_noise(nbar) * 0.05  # crash-ish wash
                for q in range(4):  # lead arpeggio
                    nn = int(beat * SR)
                    f = SEMI(C0 * 16, chord_root + (0, third, 7, 12)[q])
                    seg[q * nn:(q + 1) * nn] += tone(f, nn, "saw")[:nn] * _env(nn, 0.01, 0.3) * 0.18
            if name in ("verse", "chorus") or (name == "outro" and b % 2 == 0):
                for q in range(4):
                    k = kick()
                    st = int(q * beat * SR)
                    seg[st:st + len(k)] += k[: nbar - st] * 0.9 * level
                    if q in (1, 3) and name != "outro":
                        s = snare()
                        st2 = st
                        seg[st2:st2 + len(s)] += s[: nbar - st2] * 0.5
                    for h in (0, 1):
                        hh = hat()
                        st3 = int((q + h * 0.5) * beat * SR)
                        seg[st3:st3 + len(hh)] += hh[: nbar - st3] * 0.7 * level
            out[i0:i0 + nbar] += seg[: n_total - i0]
        pos_bar += bars
    out *= 0.8 / (np.abs(out).max() + 1e-9)
    # gentle tail
    out[-SR // 2:] *= np.linspace(1, 0, SR // 2)
    stereo = np.stack([out, out * 0.97])
    path = Path(path)
    tmp = path.with_suffix(".tmp.wav")
    sf.write(str(tmp), stereo.T, SR, subtype="PCM_16")
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(tmp)]
    for k, v in (tags or {}).items():
        cmd += ["-metadata", f"{k}={v}"]
    if fmt == "mp3":
        cmd += ["-c:a", "libmp3lame", "-b:a", "192k"]
    elif fmt == "m4a":
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    elif fmt == "flac":
        cmd += ["-c:a", "flac"]
    else:
        cmd += ["-c:a", "pcm_s16le"]
    cmd.append(str(path))
    subprocess.run(cmd, check=True)
    tmp.unlink()
    return path


SPECS = [
    # name, bpm, root pc, minor, fmt, artist, title
    ("a", 100, 9, True, "mp3", "Test Band", "Slow Burner"),      # A minor
    ("b", 124, 0, True, "flac", "Test Band", "Midnight Drive"),  # C minor
    ("c", 128, 7, False, "m4a", "Synth Kid", "Sunrise"),         # G major
    ("d", 140, 2, True, "wav", "Synth Kid", "Overclock"),        # D minor
    ("e", 174, 5, True, "mp3", "Far Out", "Drum And Bass Thing"),  # F minor (half-time 87)
]


def make_all(folder, n=5):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for name, bpm, root, minor, fmt, artist, title in SPECS[:n]:
        p = folder / f"{artist} - {title}.{fmt}"
        make_song(p, bpm, root, minor, lead_in=0.37 if name == "b" else 0.0, fmt=fmt,
                  tags={"title": title, "artist": artist})
        out.append((p, bpm, root, minor))
    return out
