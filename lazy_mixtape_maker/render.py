"""Render a MixPlan to audio: time-stretch + pitch-shift each song, blend the
transitions (EQ bass-swap, crossfade, or cut + effect), run effects, master."""
from __future__ import annotations

import math

import numpy as np
from scipy import signal
from scipy.ndimage import maximum_filter1d, uniform_filter1d

from . import audio_io, effects as fxmod, tempo
from .analysis import SongAnalysis
from .audio_io import SR
from .plan import MixPlan, Slot, timeline

LR_CROSSOVER_HZ = 200.0


class MissingSongsError(RuntimeError):
    pass


def _pitch_filter(pitch: int, sr: int) -> str | None:
    """Varispeed by `pitch` semitones (the stretcher later brings the tempo back)."""
    if pitch == 0:
        return None
    return f"asetrate={sr * 2.0 ** (pitch / 12.0):.3f},aresample={sr}"


def render_track_audio(path, t, curve, an=None, sr: int = SR) -> np.ndarray:
    """One song, cut to its bounds, moved to the speed profile `curve` and shifted
    `t.pitch` semitones. Returns exactly curve.total seconds of audio, shape (2, n)."""
    n = max(1, int(round(curve.total * sr)))
    r = 2.0 ** (t.pitch / 12.0)
    margin = (tempo.WIN + tempo.SEEK + 64) / sr * r + 0.05
    dec_start = max(0.0, t.src_start - margin)
    dec_dur = (t.src_end - dec_start) + margin
    x = audio_io.decode(path, sr=sr, channels=2, start=dec_start, duration=dec_dur, af=_pitch_filter(t.pitch, sr))
    flat = t.pitch == 0 and np.allclose(curve.r, 1.0, atol=1e-6)
    if flat:                                   # natural speed: no stretching at all
        off = int(round((t.src_start - dec_start) * sr / r))
        y = x[:, off:off + n]
        if y.shape[1] < n:
            y = np.pad(y, ((0, 0), (0, n - y.shape[1])))
        return np.ascontiguousarray(y)
    anchors = None
    if an is not None:   # make every beat land exactly where the speed curve says
        k0 = int(math.ceil((t.src_start - an.grid_origin) / an.beat_period))
        k1 = int(math.floor((t.src_end - an.grid_origin) / an.beat_period))
        beats = an.grid_origin + an.beat_period * np.arange(k0, k1 + 1)
        anchors = curve.mix_time(beats) * sr

    def tau(u):   # which sample of the decoded audio should be playing at output sample u
        return (curve.src_time(np.asarray(u) / sr) - dec_start) * sr / r

    return tempo.time_warp(x, tau, n, anchors)


# ------------------------------------------------------------------ transitions
def transition_curves(kind: str, L: int):
    """Gain curves over the overlap: (out_low, out_high, in_low, in_high)."""
    u = np.linspace(0.0, 1.0, L, dtype=np.float64)
    if kind == "eq_swap":
        swap, w = 0.5, 0.04
        ramp = np.clip((u - (swap - w)) / (2 * w), 0, 1)
        in_low = np.sin(ramp * math.pi / 2)
        out_low = np.cos(ramp * math.pi / 2)
        in_high = np.sin(np.clip(u / 0.5, 0, 1) * math.pi / 2)
        out_high = np.cos(np.clip((u - 0.5) / 0.5, 0, 1) * math.pi / 2)
        return out_low, out_high, in_low, in_high
    out = np.cos(u * math.pi / 2)
    inn = np.sin(u * math.pi / 2)
    return out, out, inn, inn


def _linkwitz_riley(x: np.ndarray, sr: int):
    lp = signal.butter(2, LR_CROSSOVER_HZ, "low", fs=sr, output="sos")
    hp = signal.butter(2, LR_CROSSOVER_HZ, "high", fs=sr, output="sos")
    lp, hp = np.vstack([lp, lp]), np.vstack([hp, hp])
    return signal.sosfilt(lp, x, axis=-1), signal.sosfilt(hp, x, axis=-1)


def _shape_track(x: np.ndarray, slot: Slot, sr: int) -> np.ndarray:
    n = x.shape[1]
    L_in, L_out = slot.overlap_in, slot.overlap_out
    t_in = slot.trans_in.type if (slot.trans_in and L_in > 0) else None
    t_out = slot.trans_out.type if (slot.trans_out and L_out > 0) else None
    lo = np.ones(n)
    hi = np.ones(n)
    if t_in:
        _, _, il, ih = transition_curves(t_in, L_in)
        lo[:L_in] *= il
        hi[:L_in] *= ih
    if t_out:
        ol, oh, _, _ = transition_curves(t_out, L_out)
        lo[n - L_out:] *= ol
        hi[n - L_out:] *= oh
    # tiny edge fades against clicks (longer at the very start/end of the mix)
    f_in = int(0.004 * sr) if slot.start > 0 else int(0.02 * sr)
    f_out = int(0.004 * sr)
    for env in (lo, hi):
        env[:f_in] *= np.linspace(0, 1, f_in)
        env[n - f_out:] *= np.linspace(1, 0, f_out)
    if "eq_swap" in (t_in, t_out):
        low, high = _linkwitz_riley(x, sr)
        return (low * lo + high * hi).astype(np.float32)
    return (x * lo).astype(np.float32)


def _apply_effects(buf: np.ndarray, track, n: int, bpm: float, sr: int, mute_start: bool = False,
                   mute_end: bool = False) -> np.ndarray:
    # backspin last because it silences everything after it
    effs = [e for e in track.effects if not (mute_start if e.anchor == "start" else mute_end)]
    effs.sort(key=lambda e: (e.type == "backspin", e.offset))
    for e in effs:
        a = int(round(e.offset * sr)) if e.anchor == "start" else n + int(round(e.offset * sr))
        a = max(0, a)
        length = int(round(e.duration * sr))
        buf = fxmod.apply_effect(buf, a, length, {"type": e.type, "params": e.params}, sr, bpm)
    return buf


# ----------------------------------------------------------------------- master
def master_limit(mix: np.ndarray, ceiling_db: float = -1.0, sr: int = SR) -> np.ndarray:
    thr = 10 ** (ceiling_db / 20)
    peak = np.abs(mix).max(axis=0)
    if peak.max() <= thr:
        return mix
    win = int(0.004 * sr) | 1
    env = maximum_filter1d(peak, size=win * 4)
    gain = np.minimum(1.0, thr / (env + 1e-9))
    # same window as the max filter, so the smoothed gain never lets a peak through
    gain = uniform_filter1d(gain, size=win * 4)
    return (mix * gain[None, :]).astype(np.float32)


def render_mix(plan: MixPlan, lib: dict[str, SongAnalysis], paths: dict[str, str],
               sr: int = SR, progress=None) -> np.ndarray:
    missing = sorted({lib[t.song_id].title or t.song_id for t in plan.tracks if t.song_id not in paths})
    if missing:
        raise MissingSongsError("Cannot find these songs: " + ", ".join(missing))
    if not plan.tracks:
        raise ValueError("The mix has no tracks")
    slots = timeline(plan, sr)
    tail = int(fxmod.TAIL_SECONDS * sr)
    total = slots[-1].end + tail
    mix = np.zeros((2, total), dtype=np.float32)
    for i, (t, slot) in enumerate(zip(plan.tracks, slots)):
        if progress:
            progress(f"rendering {i + 1}/{len(slots)}", i / len(slots))
        x = render_track_audio(paths[t.song_id], t, slot.curve, lib[t.song_id], sr)
        n = x.shape[1]
        if n != slot.length:  # keep slot and audio in lockstep
            x = np.pad(x, ((0, 0), (0, max(0, slot.length - n))))[:, : slot.length]
            n = slot.length
        x = x * np.float32(10 ** (t.gain_db / 20))
        x = _shape_track(x, slot, sr)
        buf = np.concatenate([x, np.zeros((2, tail), dtype=np.float32)], axis=1)
        buf = _apply_effects(buf, t, n, t.bpm or plan.master_bpm, sr,
                             mute_start=bool(slot.trans_in and not slot.trans_in.fx),
                             mute_end=bool(slot.trans_out and not slot.trans_out.fx))
        end = min(total, slot.start + buf.shape[1])
        mix[:, slot.start:end] += buf[:, : end - slot.start]
    if progress:
        progress("mastering", 0.97)
    # trim silent tail
    nz = np.where(np.abs(mix).max(axis=0) > 1e-4)[0]
    if len(nz):
        mix = mix[:, : min(total, nz[-1] + int(0.25 * sr))]
    return master_limit(mix, -1.0, sr)
