"""LUFS loudness measuring and the voice leveler, ported from LUFS Lab (same authors, GPL v3).

* Loudness is measured per ITU-R BS.1770-4 / EBU R128 (K-weighted, gated, integrated LUFS).
* The voice leveler rides the volume of quiet and loud passages toward a common level - slowly, and gated so
  breaths, silence and the gaps between sung lines are not boosted - then one gain sets the overall loudness."""
from __future__ import annotations

import math

import numpy as np
from scipy import signal
from scipy.ndimage import uniform_filter1d

SUB_SECONDS = 0.1                      # BS.1770 400 ms blocks are built from 100 ms sub-blocks
# name -> (strength 0..1, max boost dB, max cut dB), as in LUFS Lab
STRENGTHS = {
    "gentle": (0.50, 6.0, 9.0),
    "medium": (0.75, 9.0, 12.0),
    "strong": (1.00, 12.0, 15.0),
}


def k_weighting_sos(sr: int) -> np.ndarray:
    """K-weighting (pre-filter shelf + RLB high-pass) for any sample rate (the libebur128 / ffmpeg design)."""
    f0, G, Q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    K = math.tan(math.pi * f0 / sr)
    Vh = 10.0 ** (G / 20.0)
    Vb = Vh ** 0.4996667741545416
    a0 = 1.0 + K / Q + K * K
    s1 = [(Vh + Vb * K / Q + K * K) / a0, 2.0 * (K * K - Vh) / a0, (Vh - Vb * K / Q + K * K) / a0,
          1.0, 2.0 * (K * K - 1.0) / a0, (1.0 - K / Q + K * K) / a0]
    f0, Q = 38.13547087602444, 0.5003270373238773
    K = math.tan(math.pi * f0 / sr)
    a0 = 1.0 + K / Q + K * K
    s2 = [1.0, -2.0, 1.0, 1.0, 2.0 * (K * K - 1.0) / a0, (1.0 - K / Q + K * K) / a0]
    return np.array([s1, s2])


def subblocks(x: np.ndarray, sr: int) -> tuple[np.ndarray, int]:
    """K-weighted energy of each 100 ms piece of `x` (channels, samples): ((pieces, channels), hop)."""
    hop = int(round(SUB_SECONDS * sr))
    y = signal.sosfilt(k_weighting_sos(sr), np.asarray(x, np.float64), axis=-1)
    m = (y.shape[-1] // hop) * hop
    return (y[:, :m] ** 2).reshape(y.shape[0], -1, hop).sum(axis=2).T, hop


def block_powers(sub: np.ndarray, hop: int) -> np.ndarray:
    """400 ms blocks, 75 % overlap, channel-summed power."""
    if sub.shape[0] < 4:
        raise ValueError("Audio is shorter than 0.4 seconds - too short to measure.")
    c = np.cumsum(np.vstack([np.zeros((1, sub.shape[1])), sub]), axis=0)
    return ((c[4:] - c[:-4]) / (4.0 * hop)).sum(axis=1)


def integrated_lufs(pw: np.ndarray) -> float:
    lv = -0.691 + 10 * np.log10(pw + 1e-20)
    keep = lv > -70.0
    if not keep.any():
        return -math.inf
    rel = -0.691 + 10 * math.log10(pw[keep].mean()) - 10.0
    keep2 = keep & (lv > rel)
    if not keep2.any():
        return -math.inf
    return float(-0.691 + 10 * math.log10(pw[keep2].mean()))


def lufs(x: np.ndarray, sr: int) -> float:
    """Integrated loudness of `x` (channels, samples) in LUFS (-inf for silence)."""
    sub, hop = subblocks(x, sr)
    if sub.shape[0] < 4:
        return -math.inf
    return integrated_lufs(block_powers(sub, hop))


def leveler_curve_db(sub: np.ndarray, hop: int, strength: float, max_boost: float, max_cut: float) -> np.ndarray:
    """Slow gain-riding curve in dB, one value per 100 ms sub-block (LUFS Lab's voice mode)."""
    k = sub.shape[0]
    p_sub = sub.sum(axis=1) / hop
    l_int = integrated_lufs(block_powers(sub, hop))
    p_st = uniform_filter1d(p_sub, size=10, mode="nearest")          # ~1 s window
    l_st = -0.691 + 10 * np.log10(p_st + 1e-12)
    d = np.clip(l_int - l_st, -max_cut, max_boost) * strength
    valid = l_st > (l_int - 12.0)          # don't chase silence, breaths, noise floor
    if not valid.any():
        return np.zeros(k)
    d = np.interp(np.arange(k), np.flatnonzero(valid), d[valid])      # hold across gaps
    for _ in range(2):                                                # ~1.2 s triangular smoothing
        d = uniform_filter1d(d, size=6, mode="nearest")
    return d


def level_voice(x: np.ndarray, sr: int, strength: str = "medium", target: float | None = -18.0) -> np.ndarray:
    """A vocal (channels, samples) with LUFS Lab's voice leveler applied, then set to `target` LUFS
    (None: keep its loudness). Silent audio comes back unchanged."""
    sub, hop = subblocks(x, sr)
    if sub.shape[0] < 4 or not math.isfinite(integrated_lufs(block_powers(sub, hop))):
        return x
    s, boost, cut = STRENGTHS.get(strength, STRENGTHS["medium"])
    curve = leveler_curve_db(sub, hop, s, boost, cut)
    centers = (np.arange(len(curve)) + 0.5) * hop
    g_db = np.interp(np.arange(x.shape[-1]), centers, curve)
    leveled = sub * (10.0 ** (curve / 10.0))[:, None]
    gain = 0.0
    if target is not None:
        now = integrated_lufs(block_powers(leveled, hop))
        if math.isfinite(now):
            gain = target - now
    return (x * (10.0 ** ((g_db + gain) / 20.0))).astype(np.float32)
