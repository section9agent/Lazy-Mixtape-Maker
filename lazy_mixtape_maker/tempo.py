"""Tempo maths: playback-speed curves and a time-varying time-stretcher.

A DJ doesn't force every record to one tempo for the whole night; the tempo
glides from one song to the next. To do that each song gets a *rate curve*
(playback speed as a function of source time): it enters at the tempo of the
song before it, eases back to its own natural speed, and eases towards the
tempo of the next song before the next blend starts.

`time_warp` is a WSOLA time-stretcher (pitch stays put) that follows such a curve.
"""
from __future__ import annotations

import math

import numpy as np

WIN = 2048                 # analysis window (samples at 44.1 kHz, ~46 ms)
HOP = WIN // 2             # synthesis hop (50 % overlap, Hann windows sum to 1)
SEEK = 700                 # +-samples the next window may slide to find a good join (~16 ms)
DECIM = 4                  # the coarse search runs on a 4x decimated mono copy


# ------------------------------------------------------------------ the rate curve
class RateCurve:
    """Piecewise-linear playback speed over source time. speed 1.1 = 10 % faster."""

    def __init__(self, src_points, rates):
        s = np.asarray(src_points, dtype=np.float64)
        r = np.asarray(rates, dtype=np.float64)
        if len(s) < 2 or len(s) != len(r):
            raise ValueError("need at least two knots")
        keep = np.concatenate([[True], np.diff(s) > 1e-9])   # drop zero-length segments
        self.s, self.r = s[keep], np.clip(r[keep], 0.25, 4.0)
        if len(self.s) < 2:
            self.s = np.array([s[0], s[0] + 1e-6])
            self.r = np.array([r[0], r[0]])
        ds = np.diff(self.s)
        r0, r1 = self.r[:-1], self.r[1:]
        with np.errstate(divide="ignore", invalid="ignore"):
            seg = np.where(np.abs(r1 - r0) < 1e-9, ds / r0, ds * np.log(r1 / r0) / (r1 - r0))
        self.cum = np.concatenate([[0.0], np.cumsum(seg)])    # mix seconds at each knot
        self._tab_s = self._tab_u = None

    @property
    def total(self) -> float:
        """Mix seconds taken by the whole curve."""
        return float(self.cum[-1])

    def rate_at(self, s):
        return np.interp(s, self.s, self.r)

    def mix_time(self, s):
        """Mix time (seconds from the curve's start) at which source time `s` plays."""
        s = np.asarray(s, dtype=np.float64)
        sc = np.clip(s, self.s[0], self.s[-1])
        i = np.clip(np.searchsorted(self.s, sc, side="right") - 1, 0, len(self.s) - 2)
        s0, r0, r1 = self.s[i], self.r[i], self.r[i + 1]
        ds = self.s[i + 1] - s0
        b = (r1 - r0) / ds
        x = sc - s0
        with np.errstate(divide="ignore", invalid="ignore"):
            part = np.where(np.abs(b) < 1e-12, x / r0, np.log1p(b * x / r0) / b)
        u = self.cum[i] + part
        # beyond the ends the speed is constant
        u = np.where(s < self.s[0], (s - self.s[0]) / self.r[0], u)
        u = np.where(s > self.s[-1], self.cum[-1] + (s - self.s[-1]) / self.r[-1], u)
        return u

    def src_time(self, u):
        """Inverse of mix_time (vectorised, sample-accurate for our purposes)."""
        if self._tab_s is None:
            n = max(2, int(math.ceil((self.s[-1] - self.s[0]) / 0.005)) + 1)
            self._tab_s = np.linspace(self.s[0], self.s[-1], n)
            self._tab_u = self.mix_time(self._tab_s)
        u = np.asarray(u, dtype=np.float64)
        out = np.interp(u, self._tab_u, self._tab_s)
        out = np.where(u < 0, self.s[0] + u * self.r[0], out)
        out = np.where(u > self._tab_u[-1], self.s[-1] + (u - self._tab_u[-1]) * self.r[-1], out)
        return out


def build_curve(src_start: float, src_end: float, r_in: float, r_body: float, r_out: float,
                hold_in: float, hold_out: float, ramp: float) -> RateCurve:
    """The speed profile of one song.

    r_in / r_out : speed while it overlaps the previous / next song
    r_body       : speed in between
    hold_in/out  : source seconds spent at r_in / r_out (the length of the overlap; 0 = none)
    ramp         : source seconds the speed takes to glide between r_in/r_out and r_body
    """
    L = max(1e-3, src_end - src_start)
    hold_in = max(0.0, min(hold_in, 0.8 * L)) if abs(r_in - r_body) > 1e-6 or hold_in > 0 else 0.0
    hold_out = max(0.0, min(hold_out, 0.8 * L - hold_in))
    head = r_in if hold_in > 0 else r_body
    tail = r_out if hold_out > 0 else r_body
    s1 = src_start + hold_in
    s4 = src_end - hold_out
    avail = max(0.0, s4 - s1)
    need_in = ramp if abs(head - r_body) > 1e-6 else 0.0
    need_out = ramp if abs(tail - r_body) > 1e-6 else 0.0
    tot = need_in + need_out
    if tot > 0.9 * avail:                      # not enough room: shrink both glides
        k = 0.9 * avail / tot if tot > 0 else 0.0
        need_in, need_out = need_in * k, need_out * k
    s2, s3 = s1 + need_in, s4 - need_out
    pts = [(src_start, head), (s1, head), (s2, r_body), (s3, r_body), (s4, tail), (src_end, tail)]
    return RateCurve([p[0] for p in pts], [p[1] for p in pts])


# --------------------------------------------------------------- the time-stretcher
def _hann(n: int) -> np.ndarray:
    return (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(n) / n)).astype(np.float32)


def time_warp(x: np.ndarray, tau, n_out: int, anchors=None) -> np.ndarray:
    """Stretch/compress `x` (channels, samples) without changing its pitch.

    tau(u) -> position in `x` (in samples, may be fractional) that should be playing
    at output sample `u` (vectorised). Returns (channels, n_out) float32.

    anchors: output sample positions (the beats) where timing must be exact. The two
    windows covering such a position are placed exactly where the speed curve says
    instead of being nudged, so every kick lands on the grid to the sample; the small
    join glitch that causes is hidden under the kick itself.

    WSOLA: windows of the input are overlap-added at a fixed hop; each window is
    allowed to slide a little so its start continues the waveform of the one before
    (that keeps bass notes and drum hits in phase, so there is no 'phasiness')."""
    x = np.ascontiguousarray(x, dtype=np.float32)
    C, N = x.shape
    pad = WIN + SEEK + 8
    xp = np.pad(x, ((0, 0), (pad, pad + WIN * 2)))
    mono = xp.mean(axis=0)
    D = DECIM
    nd = len(mono) // D
    mono_d = mono[: nd * D].reshape(nd, D).mean(axis=1)
    w = _hann(WIN)
    n_hops = n_out // HOP + 2
    centres = np.arange(n_hops, dtype=np.float64) * HOP
    a = np.round(np.asarray(tau(centres), dtype=np.float64)).astype(np.int64) - WIN // 2 + pad
    out = np.zeros((C, (n_hops + 2) * HOP + WIN), dtype=np.float32)
    fixed = np.zeros(n_hops + 2, dtype=bool)
    if anchors is not None and len(anchors):
        k0 = np.floor(np.asarray(anchors, dtype=np.float64) / HOP).astype(np.int64)
        for kk in (k0, k0 + 1):
            kk = kk[(kk >= 0) & (kk < len(fixed))]
            fixed[kk] = True
    seek_d = SEEK // D
    hd = HOP // D
    p_prev = None
    for k in range(n_hops):
        ak = int(a[k])
        ak = min(max(ak, SEEK), len(mono) - WIN - SEEK - 1)
        if p_prev is None or fixed[k]:
            p = ak
        else:
            nat = p_prev + HOP
            if abs(nat - ak) <= 1:       # speed is 1.0 here: just keep playing
                p = nat
            else:
                tmpl = mono_d[(nat // D): (nat // D) + hd]
                c0 = ak // D - seek_d
                cand = mono_d[c0: c0 + 2 * seek_d + hd]
                if len(tmpl) < hd or len(cand) < 2 * seek_d + hd:
                    p = ak
                else:
                    num = np.correlate(cand, tmpl, mode="valid")
                    en = np.concatenate([[0.0], np.cumsum(cand * cand)])
                    den = np.sqrt(np.maximum(en[hd:hd + len(num)] - en[:len(num)], 1e-9))
                    sc = num / den
                    best = float(sc.max())
                    ok = np.nonzero(sc >= best - 0.06 * abs(best) - 1e-9)[0]
                    j = int(ok[np.argmin(np.abs(ok - seek_d))])      # nearest to where the curve says
                    p = (c0 + j) * D
                    # refine at full resolution
                    t_full = mono[nat: nat + HOP]
                    lo = p - D
                    seg = mono[lo: lo + HOP + 2 * D]
                    if len(t_full) == HOP and len(seg) == HOP + 2 * D:
                        num2 = np.correlate(seg, t_full, mode="valid")
                        en2 = np.concatenate([[0.0], np.cumsum(seg * seg)])
                        den2 = np.sqrt(np.maximum(en2[HOP:HOP + len(num2)] - en2[:len(num2)], 1e-9))
                        p = lo + int(np.argmax(num2 / den2))
                    p = min(max(p, SEEK), len(mono) - WIN - 2)
        p_prev = p
        o = k * HOP
        out[:, o:o + WIN] += xp[:, p:p + WIN] * w
    res = out[:, HOP: HOP + n_out]       # window 0 is centred on output sample 0
    if res.shape[1] < n_out:
        res = np.pad(res, ((0, 0), (0, n_out - res.shape[1])))
    return np.ascontiguousarray(res)
