"""DJ effects: echo, delay, reverb, filter, flange, backspin.

Every effect is described by a small dict-like spec (see plan.Effect) so the AI
mixer and the editor use exactly the same thing. Times are relative to the
track being processed, so effects follow a song when the order changes."""
from __future__ import annotations

import math

import numpy as np
from scipy import signal

TAIL_SECONDS = 6.0  # room reserved after each track for echo / reverb tails

EFFECT_TYPES = {
    "echo": {"label": "Echo", "send": True,
             "defaults": {"beats": 0.5, "feedback": 0.45, "level": 0.6, "damp_hz": 5000.0}},
    "delay": {"label": "Delay (ping-pong)", "send": True,
              "defaults": {"beats": 0.75, "feedback": 0.5, "level": 0.5, "damp_hz": 7000.0}},
    "reverb": {"label": "Reverb", "send": True,
               "defaults": {"decay": 2.4, "level": 0.35, "damp_hz": 6500.0}},
    "filter": {"label": "Filter sweep", "send": False,
               "defaults": {"mode": "lowpass", "start_hz": 18000.0, "end_hz": 350.0, "q": 1.2}},
    "flange": {"label": "Flanger", "send": False,
               "defaults": {"rate_hz": 0.35, "depth_ms": 3.5, "base_ms": 0.6}},
    "backspin": {"label": "Backspin", "send": False, "defaults": {"speed": 2.2}},
}


def default_params(kind: str) -> dict:
    return dict(EFFECT_TYPES[kind]["defaults"])


def _lowpass(x: np.ndarray, hz: float, sr: int) -> np.ndarray:
    hz = min(hz, sr * 0.45)
    sos = signal.butter(2, hz, "low", fs=sr, output="sos")
    return signal.sosfilt(sos, x, axis=-1)


# ---------------------------------------------------------------- send effects
def fx_echo(x, sr, bpm, p):
    D = max(1, int(round(p["beats"] * 60.0 / bpm * sr)))
    fb = float(np.clip(p["feedback"], 0.05, 0.92))
    K = int(min(16, max(2, math.ceil(math.log(0.03) / math.log(fb)))))
    xl = _lowpass(x, p["damp_hz"], sr)
    n = x.shape[1]
    wet = np.zeros((2, n + K * D), dtype=np.float32)
    for k in range(1, K + 1):
        wet[:, k * D:k * D + n] += xl * (fb ** (k - 1))
    return wet * p["level"]


def fx_delay(x, sr, bpm, p):
    D = max(1, int(round(p["beats"] * 60.0 / bpm * sr)))
    fb = float(np.clip(p["feedback"], 0.05, 0.92))
    K = int(min(16, max(2, math.ceil(math.log(0.03) / math.log(fb)))))
    m = _lowpass(x.mean(axis=0, keepdims=True), p["damp_hz"], sr)[0]
    n = x.shape[1]
    wet = np.zeros((2, n + K * D), dtype=np.float32)
    for k in range(1, K + 1):
        wet[(k - 1) % 2, k * D:k * D + n] += m * (fb ** (k - 1))
    return wet * p["level"]


_IR_CACHE: dict = {}


def _impulse(decay: float, damp_hz: float, sr: int) -> np.ndarray:
    key = (round(decay, 2), round(damp_hz), sr)
    if key not in _IR_CACHE:
        rng = np.random.default_rng(1234)
        m = int(decay * 1.3 * sr)
        t = np.arange(m) / sr
        env = np.exp(-6.9078 * t / decay)
        ir = rng.standard_normal((2, m)).astype(np.float32)
        ir = _lowpass(ir, damp_hz, sr) * env
        pre = int(0.015 * sr)
        ir = np.concatenate([np.zeros((2, pre), np.float32), ir], axis=1)
        ir /= np.sqrt((ir ** 2).sum(axis=1, keepdims=True)) + 1e-9
        _IR_CACHE[key] = ir.astype(np.float32)
    return _IR_CACHE[key]


def fx_reverb(x, sr, bpm, p):
    ir = _impulse(min(float(p["decay"]), 4.5), p["damp_hz"], sr)
    wet = signal.fftconvolve(x, ir, mode="full", axes=1).astype(np.float32)
    return wet * p["level"]


# ------------------------------------------------------------- insert effects
def _biquad(kind: str, fc: float, q: float, sr: int) -> np.ndarray:
    w0 = 2 * math.pi * fc / sr
    alpha = math.sin(w0) / (2 * q)
    c = math.cos(w0)
    if kind == "highpass":
        b = [(1 + c) / 2, -(1 + c), (1 + c) / 2]
    else:
        b = [(1 - c) / 2, 1 - c, (1 - c) / 2]
    a0 = 1 + alpha
    return np.array([b[0] / a0, b[1] / a0, b[2] / a0, 1.0, -2 * c / a0, (1 - alpha) / a0])


def fx_filter(x, sr, bpm, p):
    n = x.shape[1]
    kind = "highpass" if p.get("mode") == "highpass" else "lowpass"
    f0, f1 = float(p["start_hz"]), float(p["end_hz"])
    q = float(p["q"])
    block = 512
    nblocks = max(1, math.ceil(n / block))
    out = np.empty_like(x)
    zi = np.zeros((2, x.shape[0], 2))
    for bi in range(nblocks):
        a, b = bi * block, min(n, (bi + 1) * block)
        frac = bi / max(1, nblocks - 1)
        fc = float(np.clip(f0 * (f1 / f0) ** frac, 20.0, sr * 0.45))
        row = _biquad(kind, fc, q, sr)
        sos = np.vstack([row, row])
        out[:, a:b], zi = signal.sosfilt(sos, x[:, a:b], axis=-1, zi=zi)
    return out


def fx_flange(x, sr, bpm, p):
    n = x.shape[1]
    t = np.arange(n) / sr
    idx = np.arange(n, dtype=np.float64)
    out = np.empty_like(x)
    for c in range(x.shape[0]):
        lfo = 0.5 * (1 + np.sin(2 * math.pi * p["rate_hz"] * t + c * math.pi / 2))
        d = (p["base_ms"] + p["depth_ms"] * lfo) * 1e-3 * sr
        x1 = np.interp(idx - d, idx, x[c], left=0.0)
        x2 = np.interp(idx - 2 * d, idx, x[c], left=0.0)
        out[c] = 0.55 * x[c] + 0.55 * x1 + 0.25 * x2
    return out


def fx_backspin(buf, a, n_region, sr, speed=2.2):
    """Rewind the audio just before `a` with a decelerating reverse playhead,
    then silence the rest of the track (the record has been stopped)."""
    n_region = int(min(n_region, buf.shape[1] - a))
    if n_region < 64 or a < 64:
        return buf
    v0 = min(speed, 2.0 * a / n_region)
    k = np.arange(n_region, dtype=np.float64)
    pos = a - v0 * (k - k * k / (2.0 * n_region))
    idx = np.arange(buf.shape[1], dtype=np.float64)
    out = np.empty((buf.shape[0], n_region), dtype=np.float32)
    for c in range(buf.shape[0]):
        out[c] = np.interp(pos, idx, buf[c])
    env = (1.0 - (k / n_region) ** 2) ** 0.8
    fade_in = np.minimum(1.0, k / (0.01 * sr))
    out *= (env * fade_in).astype(np.float32)
    buf[:, a:a + n_region] = out
    buf[:, a + n_region:] = 0.0
    return buf


# ---------------------------------------------------------------------- driver
def apply_effect(buf: np.ndarray, a: int, length: int, spec: dict, sr: int, bpm: float) -> np.ndarray:
    """Apply one effect to `buf` (2, N) in place over [a, a+length). `buf`
    already includes TAIL_SECONDS of spare room at the end."""
    kind = spec["type"]
    if kind not in EFFECT_TYPES:
        raise ValueError(f"Unknown effect '{kind}'")
    params = default_params(kind)
    params.update(spec.get("params") or {})
    N = buf.shape[1]
    a = int(max(0, min(a, N)))
    b = int(max(a, min(a + length, N)))
    if b - a < 32:
        return buf
    if kind == "backspin":
        return fx_backspin(buf, a, b - a, sr, params["speed"])
    seg = buf[:, a:b].copy()
    if kind in ("echo", "delay", "reverb"):
        wet = {"echo": fx_echo, "delay": fx_delay, "reverb": fx_reverb}[kind](seg, sr, bpm, params)
        end = min(N, a + wet.shape[1])
        buf[:, a:end] += wet[:, : end - a]
        return buf
    proc = {"filter": fx_filter, "flange": fx_flange}[kind](seg, sr, bpm, params)
    ramp = min(int(0.02 * sr), (b - a) // 2)
    w = np.ones(b - a, dtype=np.float32)
    if ramp > 0:
        w[:ramp] = np.linspace(0, 1, ramp)
        w[-ramp:] = np.linspace(1, 0, ramp)
    buf[:, a:b] = seg * (1 - w) + proc * w
    return buf
