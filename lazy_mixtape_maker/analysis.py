"""Song analysis: BPM + beat grid, downbeats, musical key (Camelot), sections,
loudness. Pure DSP / clustering (librosa), no network, results cached on disk."""
from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from . import audio_io

ANALYSIS_VERSION = 4
ASR = 22050
HOP = 512
BPM_LOW, BPM_HIGH = 80.0, 160.0  # tempo is folded into this range

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


# ----------------------------------------------------------------- key helpers
def camelot_number(tonic: int, mode: str) -> int:
    t = tonic if mode == "major" else (tonic + 3) % 12  # relative major
    return (7 + (t * 7) % 12) % 12 + 1


def camelot(tonic: int, mode: str) -> str:
    return f"{camelot_number(tonic, mode)}{'B' if mode == 'major' else 'A'}"


def key_name(tonic: int, mode: str) -> str:
    return f"{NOTE_NAMES[tonic % 12]} {mode}"


def key_cost(t1: int, m1: str, t2: int, m2: str) -> float:
    """0 = identical/relative, 1 = adjacent on the Camelot wheel, larger = clashes."""
    n1, n2 = camelot_number(t1, m1), camelot_number(t2, m2)
    d = abs(n1 - n2)
    d = min(d, 12 - d)
    if m1 == m2:
        return float(d)
    return 0.5 if d == 0 else d + 1.0


# ------------------------------------------------------------------ data model
@dataclass
class Section:
    start: float
    end: float
    label: str
    energy: float = 0.0  # 0..1 relative to the song


@dataclass
class SongAnalysis:
    id: str
    path: str = ""
    title: str = ""
    artist: str = ""
    album: str = ""
    duration: float = 0.0
    bpm: float = 120.0               # folded into 80-160, refined from the beat grid
    beat_period: float = 0.5         # seconds per beat (60 / bpm)
    grid_origin: float = 0.0         # time of a downbeat (any downbeat; grid extends both ways)
    key_tonic: int = 0
    key_mode: str = "major"
    key_name: str = "C major"
    camelot: str = "8B"
    key_confidence: float = 0.0
    audio_start: float = 0.0         # first/last audible moment (silence trimmed)
    audio_end: float = 0.0
    loudness_lufs: float = -18.0
    sections: list[Section] = field(default_factory=list)
    bar_energy: list[float] = field(default_factory=list)
    bar_energy_origin: float = 0.0   # time of first entry in bar_energy
    wave: list[int] = field(default_factory=list)   # loudness envelope for drawing, 0-100, one value per wave_step seconds
    wave_step: float = 0.1
    version: int = ANALYSIS_VERSION

    # --- grid helpers (bars are 4 beats; 4/4 assumed)
    @property
    def bar_length(self) -> float:
        return 4.0 * self.beat_period

    def bar_time(self, j: int) -> float:
        return self.grid_origin + j * self.bar_length

    def bar_index_at_or_before(self, t: float, tol: float = 0.0) -> int:
        return int(math.floor((t + tol - self.grid_origin) / self.bar_length))

    def bar_index_at_or_after(self, t: float, tol: float = 0.0) -> int:
        return int(math.ceil((t - tol - self.grid_origin) / self.bar_length))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["bpm"] = round(float(self.bpm), 4)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "SongAnalysis":
        d = dict(d)
        d["sections"] = [Section(**s) for s in d.get("sections", [])]
        valid = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in valid})


# ----------------------------------------------------------------------- cache
def default_cache_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "LazyMixtapeMaker" / "analysis"


def _cache_load(cache_dir, fid):
    if not cache_dir:
        return None
    f = Path(cache_dir) / f"{fid}.json"
    try:
        d = json.loads(f.read_text())
        if d.get("version") == ANALYSIS_VERSION:
            return SongAnalysis.from_dict(d)
    except Exception:
        pass
    return None


def _cache_save(cache_dir, an: SongAnalysis):
    if not cache_dir:
        return
    try:
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        (Path(cache_dir) / f"{an.id}.json").write_text(json.dumps(an.to_dict()))
    except Exception:
        pass


# ------------------------------------------------------------------- algorithms
def _fold_bpm(bpm: float) -> float:
    while bpm < BPM_LOW:
        bpm *= 2
    while bpm >= BPM_HIGH:
        bpm /= 2
    return bpm


def _refine_tempo(y: np.ndarray, bpm0: float) -> tuple[float, float]:
    """Fine search (+-6%) for the constant-tempo grid that best lines up with
    onsets. Returns (bpm, time_of_a_beat_in_seconds)."""
    import librosa

    hop = 256
    env = librosa.onset.onset_strength(y=y, sr=ASR, hop_length=hop)
    env = env / (env.max() + 1e-9)
    env = np.convolve(env, [0.25, 0.5, 0.25], mode="same")
    fr = ASR / hop
    n = len(env)
    grid = np.arange(n)
    best = (-1.0, bpm0, 0.0)
    for bpm in np.arange(bpm0 * 0.94, bpm0 * 1.0601, bpm0 * 0.0004):
        pf = fr * 60.0 / bpm
        ks = np.arange(int(n / pf) - 1)
        phases = np.linspace(0, pf, 48, endpoint=False)
        pos = phases[:, None] + ks[None, :] * pf
        score = np.interp(pos, grid, env).mean(axis=1)
        j = int(np.argmax(score))
        if score[j] > best[0]:
            best = (float(score[j]), float(bpm), float(phases[j] / fr))
    return best[1], best[2]


def _refine_fine(y: np.ndarray, bpm: float, b: float) -> tuple[float, float]:
    """Millisecond-accurate beat grid. The coarse search only sees ~12 ms frames and the
    onset detector lags the real hit, which is not good enough to line two songs up.
    Here the grid is fitted to the actual transients in the waveform: the best phase is
    found in several slices of the song, then a robust straight line through those
    gives the true period and phase."""
    from scipy.ndimage import uniform_filter1d

    sr = ASR
    e = uniform_filter1d(np.abs(y).astype(np.float32), size=max(3, int(0.002 * sr)))
    lag = max(2, int(0.003 * sr))
    d = np.maximum(0.0, e[lag:] - e[:-lag])
    d = np.concatenate([d, np.zeros(lag, dtype=d.dtype)])
    d = uniform_filter1d(d, size=max(3, int(0.003 * sr)))
    p = 60.0 / bpm
    n_beats = int((len(y) / sr - b) / p)
    if n_beats < 24:
        return bpm, b
    for it in range(3):
        pts = []
        chunk = max(16, n_beats // 8)
        for c0 in range(0, n_beats - chunk + 1, chunk):
            ks = np.arange(c0, c0 + chunk)
            base = b + p * ks
            wnd = 0.06 if it == 0 else 0.03
            offs = np.arange(-wnd, wnd + 1e-6, 0.001)
            sc = np.empty(len(offs))
            for i, o in enumerate(offs):
                idx = np.clip(((base + o) * sr).astype(int), 0, len(d) - 1)
                sc[i] = d[idx].sum()
            j = int(np.argmax(sc))
            if sc[j] <= 0 or sc[j] < 1.3 * np.median(sc) or j in (0, len(offs) - 1):
                continue
            o = offs[j]
            if 0 < j < len(offs) - 1:   # parabolic refinement
                a_, b_, c_ = sc[j - 1], sc[j], sc[j + 1]
                den = a_ - 2 * b_ + c_
                if den < 0:
                    o += 0.001 * 0.5 * (a_ - c_) / den
            pts.append((float(np.mean(ks)), o, float(sc[j])))
        if len(pts) < 3:
            break
        k = np.array([q[0] for q in pts]); o = np.array([q[1] for q in pts]); w = np.array([q[2] for q in pts])
        m, c = np.polyfit(k, o, 1, w=np.sqrt(w))
        res = o - (m * k + c)
        keep = np.abs(res) <= max(0.006, 2.5 * np.median(np.abs(res)))
        if keep.sum() >= 3:
            m, c = np.polyfit(k[keep], o[keep], 1, w=np.sqrt(w[keep]))
        p, b = p + m, b + c
        if b > p:
            b -= p * int(b / p)
    return 60.0 / p, b


def _detect_key(chroma_mean: np.ndarray) -> tuple[int, str, float]:
    best, scores = (-2.0, 0, "major"), []
    for mode, prof in (("major", MAJOR_PROFILE), ("minor", MINOR_PROFILE)):
        for t in range(12):
            c = np.corrcoef(chroma_mean, np.roll(prof, t))[0, 1]
            scores.append(c)
            if c > best[0]:
                best = (c, t, mode)
    scores = sorted(scores, reverse=True)
    conf = float(np.clip((scores[0] - scores[1]) * 8 + max(scores[0], 0) * 0.5, 0, 1))
    return best[1], best[2], conf


def _cos(a, b):
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def _segment(feat_bars: np.ndarray, energy: np.ndarray) -> list[tuple[int, int]]:
    """Foote-style novelty segmentation on bar features.
    Returns [(start_bar, end_bar_exclusive)]."""
    nb = feat_bars.shape[1]
    if nb < 8:
        return [(0, nb)]
    from scipy.ndimage import uniform_filter1d

    Fz = (feat_bars - feat_bars.mean(axis=1, keepdims=True)) / (feat_bars.std(axis=1, keepdims=True) + 1e-9)
    Fz[:12] *= 0.35  # chords repeat every few bars; timbre/energy say more about song sections
    raw = Fz.copy()
    Fz = uniform_filter1d(Fz, size=4 if nb >= 24 else 2, axis=1, mode="nearest")
    Fn = Fz / (np.linalg.norm(Fz, axis=0, keepdims=True) + 1e-9)
    S = Fn.T @ Fn
    w = 4 if nb >= 24 else 2
    nov = np.zeros(nb)
    for i in range(w, nb - w + 1):
        a, b, c = S[i - w:i, i - w:i], S[i:i + w, i:i + w], S[i - w:i, i:i + w]
        nov[i] = a.mean() + b.mean() - 2 * c.mean()
    nov[:w] = 0
    # pick peaks: local maxima above threshold, at least 4 bars apart, strongest first
    thr = max(0.05, 0.12 * nov.max())
    cand = [i for i in range(w, nb - w + 1)
            if nov[i] >= thr and nov[i] >= nov[max(0, i - 3):i + 4].max() - 1e-12]
    chosen: list[int] = []
    for i in sorted(cand, key=lambda i: -nov[i]):
        if all(abs(i - j) >= 4 for j in chosen) and nb - i >= 3:
            chosen.append(i)
        if len(chosen) >= 10:
            break
    def refine(i: int) -> int:  # re-localise on unsmoothed features
        best, bi = -1.0, i
        for j in range(max(2, i - 3), min(nb - 2, i + 4)):
            d = np.linalg.norm(raw[:, max(0, j - 4):j].mean(axis=1) - raw[:, j:j + 4].mean(axis=1))
            if d > best:
                best, bi = d, j
        return bi

    refined: list[int] = []
    for i in sorted(chosen):
        j = refine(i)
        if all(abs(j - k) >= 3 for k in refined) and j >= 3 and nb - j >= 3:
            refined.append(j)
    starts = [0] + sorted(refined)
    return list(zip(starts, starts[1:] + [nb]))


def _label(segs, feat_bars, energy) -> list[str]:
    n = len(segs)
    if n == 1:
        return ["full"]
    e = np.array([energy[s:e_].mean() for s, e_ in segs])
    en = (e - e.min()) / (e.max() - e.min() + 1e-9)
    if n == 2:
        return ["verse", "chorus"] if en[1] >= en[0] else ["chorus", "verse"]
    labels = ["verse"] * n
    mid = list(range(1, n - 1))
    body = float(np.median(e[mid]))
    labels[0] = "intro" if e[0] < 0.85 * body else "verse"
    labels[-1] = "outro" if e[-1] < 0.85 * body else "chorus"
    em = e[mid]
    spread = em.max() - em.min()
    for i in mid:
        high = spread > 0.06 * max(e.max(), 1e-9) and (e[i] - em.min()) / spread >= 0.5
        labels[i] = "chorus" if high else "verse"
    choruses = [i for i in mid if labels[i] == "chorus"]
    if len(choruses) >= 2:
        means = [feat_bars[:, s:e_].mean(axis=1) for s, e_ in segs]
        cands = [i for i in mid if labels[i] == "verse" and choruses[0] < i < choruses[-1] + 2]
        if cands:
            uniq = {i: np.mean([_cos(means[i], means[j]) for j in range(n) if j != i]) for i in cands}
            i = min(uniq, key=uniq.get)
            if uniq[i] < 0.5:
                labels[i] = "bridge"
    return labels


def analyze_file(path, cache_dir=None, force: bool = False, progress=None) -> SongAnalysis:
    import librosa

    path = Path(path)
    fid = audio_io.file_id(path)
    if cache_dir is None:
        cache_dir = default_cache_dir()
    if not force:
        hit = _cache_load(cache_dir, fid)
        if hit:
            hit.path = str(path)
            return hit

    def tick(stage, frac):
        if progress:
            progress(stage, frac)

    tick("decoding", 0.02)
    y = audio_io.decode(path, sr=ASR, channels=1)[0]
    dur = len(y) / ASR
    if dur < 8:
        raise ValueError(f"{path.name} is too short to analyse ({dur:.1f}s)")
    tags = audio_io.read_tags(path)

    # audible region
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=HOP)[0]
    db = librosa.amplitude_to_db(rms, ref=1.0, amin=1e-5)
    active = np.where(db > -50)[0]
    if len(active):
        audio_start = float(active[0] * HOP / ASR)
        audio_end = float(min(dur, (active[-1] + 1) * HOP / ASR + 0.05))
    else:
        audio_start, audio_end = 0.0, dur

    # tempo + beat grid
    tick("tempo", 0.15)
    oenv = librosa.onset.onset_strength(y=y, sr=ASR, hop_length=HOP)
    tempo = float(np.atleast_1d(librosa.feature.tempo(onset_envelope=oenv, sr=ASR, hop_length=HOP,
                                                       start_bpm=120, aggregate=np.median))[0])
    bpm, b = _refine_tempo(y, _fold_bpm(tempo))
    bpm, b = _refine_fine(y, bpm, b)
    bpm = _fold_bpm(bpm)
    p = 60.0 / bpm

    # key
    tick("key", 0.5)
    yh = librosa.effects.harmonic(y, margin=3.0)
    tuning = float(librosa.estimate_tuning(y=yh, sr=ASR))
    chroma = librosa.feature.chroma_cqt(y=yh, sr=ASR, hop_length=HOP, tuning=tuning, norm=None,
                                        fmin=float(librosa.note_to_hz("A2")), n_octaves=5)
    a, z = int(audio_start * ASR / HOP), max(int(audio_end * ASR / HOP), int(audio_start * ASR / HOP) + 2)
    tonic, mode, conf = _detect_key(chroma[:, a:z].mean(axis=1))
    chroma = chroma / (chroma.max(axis=0, keepdims=True) + 1e-9)

    # downbeat phase (4/4): kick/bass flux + overall onsets at each candidate phase
    tick("downbeats", 0.35)
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=HOP))
    freqs = librosa.fft_frequencies(sr=ASR, n_fft=2048)
    low = S[(freqs >= 30) & (freqs <= 150)].sum(axis=0)
    low_flux = np.maximum(0, np.diff(low, prepend=low[0]))
    m = min(len(low_flux), len(oenv))
    strength = 0.6 * low_flux[:m] / (low_flux.max() + 1e-9) + 0.4 * oenv[:m] / (oenv.max() + 1e-9)
    kmin = int(math.ceil(-b / p))
    kmax = int(math.floor((dur - b) / p))
    ks = np.arange(kmin, kmax + 1)
    times = b + p * ks
    fr = np.clip(np.round(times * ASR / HOP).astype(int), 0, m - 1)
    st = strength[fr]
    # chord/harmony changes usually land on the downbeat: compare chroma before vs after each beat
    half = max(2, int(round(0.5 * p * ASR / HOP)))
    T_c = chroma.shape[1]
    cc = np.zeros(len(fr))
    for i, f in enumerate(fr):
        lo_, mid_, hi_ = max(0, f - half), min(f, T_c), min(T_c, f + half)
        if mid_ - lo_ >= 2 and hi_ - mid_ >= 2:
            cc[i] = np.linalg.norm(chroma[:, mid_:hi_].mean(axis=1) - chroma[:, lo_:mid_].mean(axis=1))
    st = 0.45 * st / (st.max() + 1e-9) + 0.55 * cc / (cc.max() + 1e-9)
    inside = (times >= audio_start - 0.2) & (times <= audio_end)
    scores = []
    for ph in range(4):
        sel = inside & ((ks - kmin - ph) % 4 == 0)
        scores.append(float(st[sel].mean()) if sel.any() else 0.0)
    phase = int(np.argmax(scores))
    origin = float(times[phase])

    # sections, bar-synchronous
    tick("structure", 0.75)
    bar_len = 4 * p
    jmin = int(math.floor((audio_start + 0.1 - origin) / bar_len))
    while origin + jmin * bar_len < 0:
        jmin += 1
    jmax = int(math.ceil((audio_end - 0.1 - origin) / bar_len))
    bar_lines = origin + bar_len * np.arange(jmin, jmax + 1)
    sections: list[Section] = []
    bar_energy_list: list[float] = []
    if len(bar_lines) >= 3:
        T = chroma.shape[1]
        bf = np.clip(librosa.time_to_frames(bar_lines, sr=ASR, hop_length=HOP), 0, T)
        bf = np.maximum.accumulate(bf)
        mfcc = librosa.feature.mfcc(y=y, sr=ASR, n_mfcc=13, hop_length=HOP)[1:]
        rms_db = librosa.amplitude_to_db(rms[:T] if len(rms) >= T else np.pad(rms, (0, T - len(rms))), ref=1.0, amin=1e-5)
        F = np.vstack([chroma, mfcc[:, :T], rms_db[None, :T]])
        keep = np.where(np.diff(bf) > 0)[0]
        if len(keep) >= 1:
            fb = librosa.util.sync(F, bf, aggregate=np.mean, pad=False)
            fb = fb[:, : len(bf) - 1]
            e_raw = fb[-1]
            lo, hi = float(e_raw.min()), float(e_raw.max())
            energy = (e_raw - lo) / (hi - lo + 1e-9)
            segs = _segment(fb[:-1], energy)
            labels = _label(segs, fb[:-1], energy)
            for (s, e_), lab in zip(segs, labels):
                sections.append(Section(start=float(bar_lines[s]), end=float(bar_lines[min(e_, len(bar_lines) - 1)]),
                                        label=lab, energy=float(energy[s:e_].mean())))
            bar_energy_list = [round(float(x), 3) for x in energy]
    if not sections:
        sections = [Section(start=audio_start, end=audio_end, label="full", energy=0.5)]

    # loudness
    tick("loudness", 0.92)
    seg = y[int(audio_start * ASR): int(audio_end * ASR)]
    try:
        import pyloudnorm as pyln

        lufs = float(pyln.Meter(ASR).integrated_loudness(seg.astype(np.float64)))
        if not np.isfinite(lufs):
            raise ValueError
    except Exception:
        lufs = float(20 * np.log10(np.sqrt(np.mean(seg ** 2)) + 1e-9) - 0.7)

    nb = int(len(y) / (ASR * 0.1))
    wave: list[int] = []
    if nb > 0:
        pk = np.abs(y[: nb * int(ASR * 0.1)]).reshape(nb, -1).max(axis=1) if len(y) >= nb * int(ASR * 0.1) else np.zeros(nb)
        wave = [int(v) for v in np.round(100 * np.sqrt(pk / (pk.max() + 1e-9)))]
    an = SongAnalysis(
        id=fid, path=str(path), title=tags["title"], artist=tags["artist"], album=tags["album"],
        duration=float(dur), bpm=float(bpm), beat_period=float(p), grid_origin=origin,
        key_tonic=int(tonic), key_mode=mode, key_name=key_name(tonic, mode), camelot=camelot(tonic, mode),
        key_confidence=conf, audio_start=audio_start, audio_end=audio_end, loudness_lufs=lufs,
        sections=sections, bar_energy=bar_energy_list,
        bar_energy_origin=float(bar_lines[0]) if len(bar_lines) else 0.0, wave=wave,
    )
    _cache_save(cache_dir, an)
    tick("done", 1.0)
    return an
