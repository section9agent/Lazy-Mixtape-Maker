"""Best-guess alignment of a video clip with the music it is being put on.

The sound of the clip and the sound of the stretch of music it is added to are compared (loudness-onset
envelopes, cross-correlated), and the shift that makes them agree best is returned. When the clip was cut from the
same recording this is accurate to a few milliseconds; otherwise it still finds the most rhythmic match."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import audio_io

SR = 8000
MAX_SEGMENT = 90.0      # seconds of the music / clip used for the comparison
MAX_CLIP = 150.0


@dataclass
class SyncResult:
    offset: float        # seconds from the start of the segment to where the clip's first frame belongs (+ = later)
    confidence: float    # 0..1
    note: str = ""
    found: bool = True


def _features(x: np.ndarray, hop: int, win: int, bands: int = 16) -> np.ndarray:
    """(frames, 2*bands) features: the level of each frequency band, and how fast it rises (onsets).
    Both are needed: onsets alone repeat bar after bar, the band levels tell the bars apart.
    Windows overlap (win > hop) so a sound landing between two frames still looks the same in both."""
    if len(x) < win + hop * 8:
        return np.zeros((8, 2 * bands))
    frames = np.lib.stride_tricks.sliding_window_view(x, win)[::hop]
    spec = np.abs(np.fft.rfft(frames * np.hanning(win), axis=1))
    edges = np.unique(np.geomspace(3, spec.shape[1], bands + 1).astype(int))
    cols = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        cols.append(np.log1p(30.0 * spec[:, lo:max(hi, lo + 1)].mean(axis=1) / (win / 64)))
    level = np.stack(cols, axis=1)
    flux = np.maximum(0.0, np.diff(level, axis=0, prepend=level[:1]))
    return np.concatenate([level, 1.5 * flux], axis=1)


def _norm(v: np.ndarray, smooth_frames: int) -> np.ndarray:
    """Remove each band's slow drift (so only the fine rhythm / note structure is compared) and scale it."""
    from scipy.ndimage import uniform_filter1d

    v = v - uniform_filter1d(v, size=max(3, smooth_frames), axis=0, mode="nearest")
    s = v.std(axis=0, keepdims=True)
    return np.where(s > 1e-9, v / np.maximum(s, 1e-9), 0.0)


def _xcorr(a: np.ndarray, b: np.ndarray):
    """Normalised correlation of a (music) against b (clip) for every shift d: a[u] ~ b[u - d].
    Returns (lags, scores in -1..1, overlap in frames)."""
    n = len(a) + len(b) - 1
    size = 1 << int(np.ceil(np.log2(max(2, n))))
    fa, fb = np.fft.rfft(a, size, axis=0), np.fft.rfft(b, size, axis=0)
    full = np.fft.irfft(fa * np.conj(fb), size, axis=0).sum(axis=1)
    lags = np.concatenate([np.arange(0, len(a)), np.arange(-(len(b) - 1), 0)])      # index k >= 0 -> d = k
    corr = np.concatenate([full[0:len(a)], full[size - (len(b) - 1):size]])
    lo = np.maximum(0, lags)
    hi = np.minimum(len(a), lags + len(b))
    ov = hi - lo
    ca = np.concatenate([[0.0], np.cumsum((a ** 2).sum(axis=1))])
    cb = np.concatenate([[0.0], np.cumsum((b ** 2).sum(axis=1))])
    pos = ov > 0
    ea = np.where(pos, ca[np.clip(hi, 0, len(a))] - ca[np.clip(lo, 0, len(a))], 0.0)
    eb = np.where(pos, cb[np.clip(hi - lags, 0, len(b))] - cb[np.clip(lo - lags, 0, len(b))], 0.0)
    return lags, corr / np.sqrt(ea * eb + 1e-9), ov


def estimate_offset(music_path, t0: float, t1: float, clip_path, progress=None) -> SyncResult:
    """Where (relative to t0) does the clip have to start so that its sound lines up with the music of t0..t1?"""
    say = progress or (lambda m, f: None)
    say("reading the music…", 0.05)
    dur = min(max(1.0, t1 - t0), MAX_SEGMENT)
    music = audio_io.decode(music_path, sr=SR, channels=1, start=max(0.0, t0), duration=dur)[0]
    say("reading the video's sound…", 0.25)
    try:
        clip = audio_io.decode(clip_path, sr=SR, channels=1, duration=MAX_CLIP)[0]
    except audio_io.AudioError:
        clip = np.zeros(0, np.float32)
    if len(clip) < SR or float(np.abs(clip).max()) < 1e-4:
        return SyncResult(0.0, 0.0, "The video has no usable sound, so it couldn't be lined up automatically. "
                                    "Move it on the timeline or type its start time.", False)
    if len(music) < SR or float(np.abs(music).max()) < 1e-4:
        return SyncResult(0.0, 0.0, "This part of the music is silent, so there is nothing to line the video up with.", False)

    say("comparing…", 0.5)
    hop, win = 128, 512                                   # 16 ms steps, 64 ms windows
    ea, eb = _norm(_features(music, hop, win), 32), _norm(_features(clip, hop, win), 32)
    lags, scores, ov = _xcorr(ea, eb)
    ok = ov >= max(8, int(3.0 * SR / hop))                # at least ~3 s have to overlap
    if not ok.any():
        ok = ov >= max(4, min(len(ea), len(eb)) // 2)
    sc = np.where(ok, scores, -1e9)
    k = int(np.argmax(sc))
    best = float(sc[k])
    coarse = lags[k] * hop / SR

    # fine pass: a 2 ms envelope, within +-60 ms of the coarse answer
    hop2, win2 = 16, 256
    fa2, fb2 = _norm(_features(music, hop2, win2), 128), _norm(_features(clip, hop2, win2), 128)
    lags2, scores2, ov2 = _xcorr(fa2, fb2)
    near = np.abs(lags2 * hop2 / SR - coarse) <= 0.06
    if near.any():
        s2 = np.where(near, scores2, -1e9)
        offset = float(lags2[int(np.argmax(s2))] * hop2 / SR)
    else:
        offset = float(coarse)

    valid = sc[ok]
    med, sd = float(np.median(valid)), float(valid.std()) + 1e-9
    z = (best - med) / sd
    # how much better than the best *different* spot (a different beat, 0.25 s away or more)
    far = ok & (np.abs(lags - lags[k]) * hop / SR > 0.25)
    second = float(sc[far].max()) if far.any() else med
    ratio = (best - med) / max(1e-9, (second - med))
    conf = float(np.clip((best - 0.2) / 0.4, 0.0, 1.0) * np.clip((ratio - 1.0) / 0.12, 0.0, 1.0))
    note = (f"Lined up by sound (confidence {conf:.0%}). Fine-tune it by dragging or with the millisecond buttons."
            if conf >= 0.3 else
            "Only a weak match, so this is a rough guess. Check it against the music and adjust.")
    say("done", 1.0)
    return SyncResult(offset, conf, note, True)
