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


def _decode_stem(path, dec_start: float, dec_dur: float, lag: float, af, sr: int, r: float, length: int) -> np.ndarray:
    """A stem decoded exactly like its song (same window, same pitch filter), shifted by the stems' offset."""
    start = dec_start + lag
    y = audio_io.decode(path, sr=sr, channels=2, start=max(0.0, start), duration=dec_dur + min(0.0, start), af=af)
    if start < 0:                                # the stems begin a moment later than the song does
        y = np.pad(y, ((0, 0), (int(round(-start * sr / r)), 0)))
    if y.shape[1] < length:
        y = np.pad(y, ((0, 0), (0, length - y.shape[1])))
    return y[:, :length]


def render_track_audio(path, t, curve, an=None, sr: int = SR, stems: dict | None = None, lag: float = 0.0):
    """One song, cut to its bounds, moved to the speed profile `curve` and shifted
    `t.pitch` semitones. Returns exactly curve.total seconds of audio, shape (2, n).

    stems: {name: file} to render alongside, stretched in perfect step with the song (so a stem can be
    subtracted from it); the result is then (audio, {name: audio})."""
    n = max(1, int(round(curve.total * sr)))
    r = 2.0 ** (t.pitch / 12.0)
    margin = (tempo.WIN + tempo.SEEK + 64) / sr * r + 0.05
    dec_start = max(0.0, t.src_start - margin)
    dec_dur = (t.src_end - dec_start) + margin
    af = _pitch_filter(t.pitch, sr)
    x = audio_io.decode(path, sr=sr, channels=2, start=dec_start, duration=dec_dur, af=af)
    names = sorted(stems) if stems else []
    if names:
        x = np.concatenate([x] + [_decode_stem(stems[k], dec_start, dec_dur, lag, af, sr, r, x.shape[1]) for k in names])

    def result(y):
        if stems is None:
            return y
        return np.ascontiguousarray(y[:2]), {k: np.ascontiguousarray(y[2 + 2 * i: 4 + 2 * i]) for i, k in enumerate(names)}

    flat = t.pitch == 0 and np.allclose(curve.r, 1.0, atol=1e-6)
    if flat:                                   # natural speed: no stretching at all
        off = int(round((t.src_start - dec_start) * sr / r))
        y = x[:, off:off + n]
        if y.shape[1] < n:
            y = np.pad(y, ((0, 0), (0, n - y.shape[1])))
        return result(np.ascontiguousarray(y))
    anchors = None
    if an is not None:   # make every beat land exactly where the speed curve says
        k0 = int(math.ceil((t.src_start - an.grid_origin) / an.beat_period))
        k1 = int(math.floor((t.src_end - an.grid_origin) / an.beat_period))
        beats = an.grid_origin + an.beat_period * np.arange(k0, k1 + 1)
        anchors = curve.mix_time(beats) * sr

    def tau(u):   # which sample of the decoded audio should be playing at output sample u
        return (curve.src_time(np.asarray(u) / sr) - dec_start) * sr / r

    return result(tempo.time_warp(x, tau, n, anchors, guide=2))


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


# Transitions that work on a song's stems (drums, bass, vocals, other) instead of on bass / treble bands.
STEM_KINDS = ("stem_bass", "stem_blend", "stem_mashup", "stem_vocal_in")
STEM_NAMES = ("drums", "bass", "vocals", "other")


def _down(u, a, b):
    """1 until a, an equal-power fade to 0 by b."""
    return np.cos(np.clip((u - a) / max(b - a, 1e-9), 0, 1) * math.pi / 2)


def _up(u, a, b):
    return np.sin(np.clip((u - a) / max(b - a, 1e-9), 0, 1) * math.pi / 2)


def stem_curves(kind: str, L: int):
    """Gain of each stem over the overlap: ({stem: curve} for the song leaving, {stem: curve} for the one arriving)."""
    u = np.linspace(0.0, 1.0, L, dtype=np.float64)
    if kind == "stem_mashup":             # the old song's singer carries on over the new song's music
        out = {"drums": _down(u, 0.0, 0.3), "other": _down(u, 0.0, 0.3), "bass": _down(u, 0.11, 0.19), "vocals": _down(u, 0.85, 1.0)}
        inn = {"drums": _up(u, 0.0, 0.3), "other": _up(u, 0.0, 0.3), "bass": _up(u, 0.11, 0.19), "vocals": _up(u, 0.85, 1.0)}
    elif kind == "stem_vocal_in":         # the new song's singer arrives over the old song's music
        out = {"drums": _down(u, 0.7, 1.0), "other": _down(u, 0.7, 1.0), "bass": _down(u, 0.81, 0.89), "vocals": _down(u, 0.0, 0.15)}
        inn = {"drums": _up(u, 0.7, 1.0), "other": _up(u, 0.7, 1.0), "bass": _up(u, 0.81, 0.89), "vocals": _up(u, 0.05, 0.2)}
    else:                                 # a DJ blend: the bass (and, for stem_blend, the singers) swap in the middle
        out = {"drums": _down(u, 0.5, 1.0), "other": _down(u, 0.5, 1.0), "bass": _down(u, 0.46, 0.54)}
        inn = {"drums": _up(u, 0.0, 0.5), "other": _up(u, 0.0, 0.5), "bass": _up(u, 0.46, 0.54)}
        if kind == "stem_blend":          # only one singer at a time
            out["vocals"], inn["vocals"] = _down(u, 0.42, 0.58), _up(u, 0.42, 0.58)
        else:
            out["vocals"], inn["vocals"] = out["other"], inn["other"]
    return out, inn


def stems_needed(kind: str) -> tuple[str, ...]:
    """The stems a transition handles differently from the rest of the song (only these are loaded)."""
    return {"stem_bass": ("bass",), "stem_blend": ("bass", "vocals")}.get(kind, ("bass", "drums", "vocals"))


def _linkwitz_riley(x: np.ndarray, sr: int):
    lp = signal.butter(2, LR_CROSSOVER_HZ, "low", fs=sr, output="sos")
    hp = signal.butter(2, LR_CROSSOVER_HZ, "high", fs=sr, output="sos")
    lp, hp = np.vstack([lp, lp]), np.vstack([hp, hp])
    return signal.sosfilt(lp, x, axis=-1), signal.sosfilt(hp, x, axis=-1)


def _shape_track(x: np.ndarray, slot: Slot, sr: int, t_in: str | None = None, t_out: str | None = None,
                 stems: dict | None = None) -> np.ndarray:
    """Apply the fades of the transitions on both sides of a song. t_in / t_out are the transition types to
    use (after any fall-back); `stems` holds the song's stems, already stretched in step with `x`."""
    n = x.shape[1]
    L_in, L_out = slot.overlap_in, slot.overlap_out
    if L_in <= 0:
        t_in = None
    if L_out <= 0:
        t_out = None
    lo = np.ones(n)
    hi = np.ones(n)
    g = None                                         # per-stem gains, when a stem transition is involved
    if t_in in STEM_KINDS or t_out in STEM_KINDS:
        g = {s: np.ones(n) for s in STEM_NAMES}
    if t_in in STEM_KINDS:
        for s, c in stem_curves(t_in, L_in)[1].items():
            g[s][:L_in] *= c
    elif t_in:
        _, _, il, ih = transition_curves(t_in, L_in)
        lo[:L_in] *= il
        hi[:L_in] *= ih
    if t_out in STEM_KINDS:
        for s, c in stem_curves(t_out, L_out)[0].items():
            g[s][n - L_out:] *= c
    elif t_out:
        ol, oh, _, _ = transition_curves(t_out, L_out)
        lo[n - L_out:] *= ol
        hi[n - L_out:] *= oh
    # tiny edge fades against clicks (longer at the very start/end of the mix)
    f_in = int(0.004 * sr) if slot.start > 0 else int(0.02 * sr)
    f_out = int(0.004 * sr)
    edge = np.ones(n)
    edge[:f_in] *= np.linspace(0, 1, f_in)
    edge[n - f_out:] *= np.linspace(1, 0, f_out)
    swap = "eq_swap" in (t_in, t_out)
    if swap:
        low, high = _linkwitz_riley(x, sr)
        y = low * lo + high * hi
    else:
        y = x * lo
    if g is not None:
        # The stems of a song never add up to it exactly, so the song itself stays the base: everything follows
        # the "other" gain, and each stem that should be louder or quieter than that is added or taken away.
        rest = g["other"]
        y = y * rest
        for s, audio in (stems or {}).items():
            d = g[s] - rest
            if s == "other" or not np.any(d):
                continue
            if swap:                                 # the band split shifts phase; the stem must follow suit
                sl, sh = _linkwitz_riley(audio, sr)
                audio = sl + sh
            y = y + audio * d
    return (y * edge).astype(np.float32)


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


def effective_types(plan: MixPlan, notes: list | None = None) -> dict:
    """The transition type actually used for each transition (keyed by id(transition)): a stem transition
    needs both songs to have been split into stems, otherwise it is played as a normal bass-swap blend."""
    out = {}
    have = {}
    for i, tr in enumerate(plan.transitions):
        kind = tr.type
        if kind in STEM_KINDS:
            from . import stems as stemmod
            for uid in (tr.from_uid, tr.to_uid):
                sid = plan.track(uid).song_id
                if sid not in have:
                    have[sid] = set(stemmod.cached(sid) or {})
            need = set(stems_needed(kind))
            if not all(need <= have[plan.track(uid).song_id] for uid in (tr.from_uid, tr.to_uid)):
                kind = "eq_swap"
                if notes is not None:
                    notes.append(f"Transition {i + 1}: the songs haven't been split into stems, so a normal bass-swap blend was used.")
        out[id(tr)] = kind
    return out


def render_mix(plan: MixPlan, lib: dict[str, SongAnalysis], paths: dict[str, str],
               sr: int = SR, progress=None, notes: list | None = None) -> np.ndarray:
    missing = sorted({lib[t.song_id].title or t.song_id for t in plan.tracks if t.song_id not in paths})
    if missing:
        raise MissingSongsError("Cannot find these songs: " + ", ".join(missing))
    if not plan.tracks:
        raise ValueError("The mix has no tracks")
    slots = timeline(plan, sr)
    tail = int(fxmod.TAIL_SECONDS * sr)
    total = slots[-1].end + tail
    mix = np.zeros((2, total), dtype=np.float32)
    kinds = effective_types(plan, notes)
    for i, (t, slot) in enumerate(zip(plan.tracks, slots)):
        if progress:
            progress(f"rendering {i + 1}/{len(slots)}", i / len(slots))
        t_in = kinds.get(id(slot.trans_in)) if slot.trans_in else None
        t_out = kinds.get(id(slot.trans_out)) if slot.trans_out else None
        want = sorted({s for k in (t_in, t_out) if k in STEM_KINDS for s in stems_needed(k)})
        st = {}
        if want:
            from . import stems as stemmod
            files = stemmod.cached(t.song_id) or {}
            x, st = render_track_audio(paths[t.song_id], t, slot.curve, lib[t.song_id], sr,
                                       stems={s: files[s] for s in want if s in files},
                                       lag=stemmod.lag(t.song_id, paths[t.song_id]))
        else:
            x = render_track_audio(paths[t.song_id], t, slot.curve, lib[t.song_id], sr)
        n = x.shape[1]
        if n != slot.length:  # keep slot and audio in lockstep
            x = np.pad(x, ((0, 0), (0, max(0, slot.length - n))))[:, : slot.length]
            st = {k: np.pad(v, ((0, 0), (0, max(0, slot.length - v.shape[1]))))[:, : slot.length] for k, v in st.items()}
            n = slot.length
        gain = np.float32(10 ** (t.gain_db / 20))
        x = x * gain
        st = {k: v * gain for k, v in st.items()}
        x = _shape_track(x, slot, sr, t_in, t_out, st)
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
