"""The mix plan: an editable, JSON-serialisable description of the whole mix,
plus the "AI" planner that builds it and the edit operations the UI will call.

Design rules
- The plan only references songs by id; analysis lives in the library dict.
- Anything the user edits is flagged (auto=False / auto_bounds=False) so a
  re-plan (after reordering, removing, adding) never overwrites it.
- Effects are anchored to a track's start or end, so they follow the song."""
from __future__ import annotations

import math
import random
import uuid
from dataclasses import asdict, dataclass, field

import numpy as np

from . import effects as fxmod
from .analysis import SongAnalysis, key_cost, NOTE_NAMES
from .audio_io import SR
from .tempo import RateCurve, build_curve


def _uid() -> str:
    return uuid.uuid4().hex[:8]


# ------------------------------------------------------------------- data model
@dataclass
class Effect:
    type: str
    anchor: str = "end"          # "start" or "end" of the track's slot in the mix
    offset: float = 0.0          # seconds from the anchor (negative for "end")
    duration: float = 2.0        # seconds
    params: dict = field(default_factory=dict)
    auto: bool = True            # True = chosen by the AI mixer
    id: str = field(default_factory=_uid)


@dataclass
class TrackPlan:
    song_id: str
    src_start: float = 0.0       # source seconds where this track starts playing
    src_end: float = 0.0         # source seconds where it stops
    rate: float = 1.0            # playback speed through the body of the song (1.0 = natural)
    rate_in: float = 0.0         # speed while blending in from the previous song (0 = same as rate)
    rate_out: float = 0.0        # speed while blending out into the next song (0 = same as rate)
    bpm: float = 0.0             # the tempo the body plays at (after octave choice and speed)
    pitch: int = 0               # semitones, for key matching
    gain_db: float = 0.0
    matched: bool = True         # tempo within stretch limits of the master tempo
    auto_bounds: bool = True
    effects: list[Effect] = field(default_factory=list)
    uid: str = field(default_factory=_uid)


@dataclass
class Transition:
    from_uid: str
    to_uid: str
    type: str = "eq_swap"        # eq_swap | crossfade | cut_fx | cut
    overlap_beats: int = 32      # beats at this transition's tempo
    auto: bool = True
    tempo: float = 0.0           # BPM both songs play at during the blend (0 = the mix tempo)
    matched: bool = True         # False: the two tempos were too far apart to beat-match


@dataclass
class MixSettings:
    mode: str = "full"                 # "full" (whole songs) or "clips" (rave.dj style)
    clip_seconds: float = 30.0
    overlap_bars: int = 32             # longest blend allowed, in bars (it uses the whole outro/intro up to this)
    master_bpm: float | None = None    # a fixed mix tempo (implies tempo_mode "locked"); None = automatic
    tempo_mode: str = "drift"          # "drift" = tempo glides from song to song, "locked" = one tempo throughout
    max_tempo_stretch: float = 0.12    # most a song is sped up / slowed down to meet its neighbour
    max_pitch_shift: int = 2           # semitones the mixer may shift to match keys
    key_match: bool = True
    order: str = "auto"                # "auto" or "given"
    transition_style: str = "auto"     # auto | eq_swap | crossfade | cut
    use_effects: bool = True
    track_lufs: float = -16.0          # per-song loudness target before the master limiter
    seed: int = 0
    cue_point: str = "start"           # where the cue sheet marks each track: start | middle | end


@dataclass
class MixPlan:
    settings: MixSettings = field(default_factory=MixSettings)
    master_bpm: float = 120.0
    tracks: list[TrackPlan] = field(default_factory=list)
    transitions: list[Transition] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MixPlan":
        s = MixSettings(**{k: v for k, v in d.get("settings", {}).items() if k in MixSettings.__dataclass_fields__})
        tracks = []
        for t in d.get("tracks", []):
            t = dict(t)
            t["effects"] = [Effect(**e) for e in t.get("effects", [])]
            tracks.append(TrackPlan(**t))
        trans = [Transition(**t) for t in d.get("transitions", [])]
        return cls(settings=s, master_bpm=d.get("master_bpm", 120.0), tracks=tracks, transitions=trans)

    def track(self, uid: str) -> TrackPlan:
        for t in self.tracks:
            if t.uid == uid:
                return t
        raise KeyError(uid)

    def transition_after(self, index: int) -> Transition | None:
        if index < 0 or index >= len(self.tracks) - 1:
            return None
        a, b = self.tracks[index].uid, self.tracks[index + 1].uid
        for tr in self.transitions:
            if tr.from_uid == a and tr.to_uid == b:
                return tr
        return None


# ------------------------------------------------------------------- tempo logic
def octave_bpm(bpm: float, master: float) -> float:
    """Pick bpm, 2*bpm or bpm/2, whichever sits closest to the master tempo."""
    return min((bpm / 2, bpm, bpm * 2), key=lambda c: abs(math.log(master / c)))


def choose_master_bpm(songs: list[SongAnalysis], s: MixSettings) -> float:
    if not songs:
        return 120.0
    best = None
    for cand in {round(a.bpm, 2) for a in songs}:
        rates = [cand / octave_bpm(a.bpm, cand) for a in songs]
        ok = sum(abs(r - 1) <= s.max_tempo_stretch for r in rates)
        cost = sum(abs(math.log(r)) for r in rates)
        key = (-ok, cost)
        if best is None or key < best[0]:
            best = (key, cand)
    return float(best[1])


def _pair_cost(a: SongAnalysis, b: SongAnalysis) -> float:
    """How awkward it is to play b after a: tempo distance (octave-aware) plus key clash."""
    bc = min(abs(math.log2(a.bpm * f / b.bpm)) for f in (0.5, 1, 2))
    return 10 * bc + 0.6 * key_cost(a.key_tonic, a.key_mode, b.key_tonic, b.key_mode)


def order_songs(songs: list[SongAnalysis], s: MixSettings) -> list[SongAnalysis]:
    """The smoothest path through the songs: nearest-neighbour chains from every start,
    polished with 2-opt, best total cost wins (ties go to the slower start, so a mix
    tends to build up)."""
    if s.order == "given" or len(songs) < 3:
        return list(songs)
    songs = sorted(songs, key=lambda a: (a.bpm, a.id))
    n = len(songs)
    C = np.array([[0.0 if i == j else _pair_cost(songs[i], songs[j]) for j in range(n)] for i in range(n)])

    def total(path):
        return float(sum(C[a, b] for a, b in zip(path, path[1:])))

    best, best_cost = None, math.inf
    starts = range(n) if n <= 40 else sorted({int(i * n / 40) for i in range(40)})
    for start in starts:
        path, left = [start], set(range(n)) - {start}
        while left:
            nxt = min(left, key=lambda j: (C[path[-1], j], j))
            path.append(nxt)
            left.remove(nxt)
        improved = True
        while improved and n <= 60:
            improved = False
            for i in range(0, n - 1):
                for j in range(i + 1, n):
                    # reverse path[i..j]; open path, so the edges at the ends may not exist
                    old = (C[path[i - 1], path[i]] if i > 0 else 0.0) + (C[path[j], path[j + 1]] if j < n - 1 else 0.0)
                    new = (C[path[i - 1], path[j]] if i > 0 else 0.0) + (C[path[i], path[j + 1]] if j < n - 1 else 0.0)
                    if new < old - 1e-9:
                        path[i:j + 1] = reversed(path[i:j + 1])
                        improved = True
        c = total(path)
        if c < best_cost - 1e-9:
            best, best_cost = path, c
    return [songs[i] for i in best]


# ----------------------------------------------------------------- bounds / clips
def default_bounds(an: SongAnalysis, s: MixSettings, rate: float) -> tuple[float, float]:
    bar = an.bar_length
    j0 = an.bar_index_at_or_before(an.audio_start, tol=0.1)
    while an.bar_time(j0) < 0:
        j0 += 1
    # end on the last bar line that is at most a quarter bar past the audible end,
    # so we never pad a long stretch of silence before the next song
    j1 = max(j0 + 4, int(math.floor((an.audio_end + 0.25 * bar - an.grid_origin) / bar)))
    start, end = an.bar_time(j0), an.bar_time(j1)
    if s.mode != "clips":
        return start, end
    secs = [x for x in an.sections if x.label not in ("intro", "outro")] or an.sections
    choruses = [x for x in secs if x.label == "chorus"]
    best = max(choruses or secs, key=lambda x: (x.energy, x.end - x.start))
    nbars = max(4, int(round(s.clip_seconds * rate / bar)))
    nbars -= nbars % 2
    jstart = an.bar_index_at_or_after(best.start, tol=0.05)
    jend = jstart + nbars
    if an.bar_time(jend) > end:
        jend = j1
        jstart = max(j0, jend - nbars)
    return an.bar_time(jstart), an.bar_time(jend)


# --------------------------------------------------------------------- recompute
def tr_tempo(plan: MixPlan, tr: Transition | None) -> float:
    """BPM during a blend."""
    return tr.tempo if tr is not None and tr.tempo > 0 else plan.master_bpm


def overlap_seconds(plan: MixPlan, tr: Transition | None) -> float:
    return 0.0 if tr is None or tr.type == "cut" else tr.overlap_beats * 60.0 / tr_tempo(plan, tr)


def track_curve(t: TrackPlan, ov_in: float, ov_out: float) -> RateCurve:
    """Speed profile of a track given how long (mix seconds) it overlaps its neighbours:
    held at the neighbour's tempo during the blend, gliding to its own pace in between."""
    r_body = t.rate
    r_in = t.rate_in or r_body
    r_out = t.rate_out or r_body
    hold_in = ov_in * r_in if ov_in > 0 else 0.0
    hold_out = ov_out * r_out if ov_out > 0 else 0.0
    d = max(abs(r_in - r_body) if hold_in > 0 else 0.0, abs(r_out - r_body) if hold_out > 0 else 0.0)
    ramp = float(np.clip(d / 0.004, 8.0, 40.0))     # about 0.4 % speed change per second
    return build_curve(t.src_start, t.src_end, r_in, r_body, r_out, hold_in, hold_out, ramp)


def _mix_len(t: TrackPlan) -> float:
    return max(0.1, (t.src_end - t.src_start) / t.rate)


def _bars(an: SongAnalysis, sec) -> float:
    return (sec.end - sec.start) / an.bar_length


def _quiet_bars(an: SongAnalysis, from_end: bool) -> float:
    """Bars at the very end (or start) of the song that are clearly quieter than the body."""
    be = an.bar_energy
    if len(be) < 8:
        return 0.0
    thr = 0.62 * float(np.mean(be))
    run = 0
    for x in (reversed(be) if from_end else be):
        if x < thr:
            run += 1
        else:
            break
    return float(run)


def _edge_room(an: SongAnalysis, end: bool) -> float:
    """Bars of usable outro (end=True) or intro (end=False): the labelled section, or the quiet
    run of bars at that edge, whichever is longer."""
    if not an.sections:
        return 0.0
    sec = an.sections[-1] if end else an.sections[0]
    lab = _bars(an, sec) if sec.label == ("outro" if end else "intro") else 0.0
    return max(lab, _quiet_bars(an, end))


def _blend_bars(a_an: SongAnalysis, b_an: SongAnalysis, want: int) -> int:
    """How many bars to blend. Uses the *whole* outro of the outgoing song and intro of the
    incoming one when both have one (up to `want` bars), otherwise a medium blend."""
    a_out, b_in = _edge_room(a_an, True), _edge_room(b_an, False)
    if a_out >= 3 and b_in >= 3:
        room = min(a_out, b_in)
    elif a_out >= 3 or b_in >= 3:
        room = min(max(a_out, b_in), 16.0)      # one side is already in full flow: keep it shorter
    else:
        room = 4.0
    bars = int(min(float(want), room) + 0.5)
    if bars >= 8:
        bars = bars // 4 * 4                     # keep to whole phrases
    elif bars >= 3:
        bars = bars // 2 * 2
    return max(1, bars)


def _auto_transition(a: TrackPlan, b: TrackPlan, tr_matched: bool, plan: MixPlan, lib, rng: random.Random) -> tuple[str, int]:
    s = plan.settings
    style = s.transition_style
    if style == "cut" or not tr_matched:
        return "cut_fx", 0
    tempo = max(1.0, a.bpm or plan.master_bpm)
    bar_m = 4 * 60.0 / tempo
    cap = 0.45 * min(_mix_len(a), _mix_len(b))
    max_bars = int(cap // bar_m)
    bars = min(_blend_bars(lib[a.song_id], lib[b.song_id], max(1, s.overlap_bars)), max_bars)
    if bars < 1:
        return "cut_fx", 0
    ttype = "eq_swap" if bars >= 4 else "crossfade"
    if style in ("eq_swap", "crossfade"):
        ttype = style
    elif ttype == "eq_swap" and rng.random() < 0.2:
        ttype = "crossfade"
    return ttype, bars * 4


def _auto_effects(a: TrackPlan, b: TrackPlan, tr: Transition, plan: MixPlan, rng: random.Random):
    """Give the AI mixer some flavour: one effect per transition, sometimes none."""
    s = plan.settings
    if not s.use_effects:
        return
    beat = 60.0 / tr_tempo(plan, tr)
    L = tr.overlap_beats * beat
    if tr.type == "cut_fx":
        beat = 60.0 / max(1.0, a.bpm or plan.master_bpm)
        r = rng.random()
        if r < 0.30:
            d = 1.6
            a.effects.append(Effect("backspin", "end", -d, d, {}, True))
        elif r < 0.58:
            a.effects.append(Effect("filter", "end", -4 * beat, 4 * beat,
                                    {"mode": "lowpass", "start_hz": 16000.0, "end_hz": 500.0}, True))
            a.effects.append(Effect("echo", "end", -2 * beat, 2 * beat, {"beats": 0.5, "feedback": 0.55}, True))
        elif r < 0.72:
            a.effects.append(Effect("reverb", "end", -2 * beat, 2 * beat, {"decay": 3.0, "level": 0.5}, True))
        elif r < 0.86:
            a.effects.append(Effect("stutter", "end", -2 * beat, 2 * beat,
                                    {"beats": 0.5, "roll": "yes", "level": 1.0}, True))
        else:
            a.effects.append(Effect("cut", "end", -4 * beat, 4 * beat,
                                    {"mode": "gate", "division": 0.5, "duty": 0.5, "floor": 0.0}, True))
        return
    if L <= 0:
        return
    r = rng.random()
    cut_len = min(L * 0.5, 8 * beat)
    if r < 0.20:
        a.effects.append(Effect("filter", "end", -L * 0.5, L * 0.5,
                                {"mode": "lowpass", "start_hz": 18000.0, "end_hz": 300.0}, True))
    elif r < 0.34:
        a.effects.append(Effect("echo", "end", -4 * beat, 4 * beat, {"beats": 0.75, "feedback": 0.5}, True))
    elif r < 0.44:
        b.effects.append(Effect("flange", "start", 0.0, L * 0.5, {"rate_hz": 0.25}, True))
    elif r < 0.52:
        a.effects.append(Effect("delay", "end", -8 * beat, 8 * beat, {"beats": 0.75, "feedback": 0.45}, True))
    elif r < 0.68 and cut_len >= 2 * beat:      # chop the outgoing song with the crossfader while it leaves
        mode = rng.choice(["gate", "bass_kill", "highs_kill"])
        a.effects.append(Effect("cut", "end", -cut_len, cut_len,
                                {"mode": mode, "division": rng.choice([0.5, 0.5, 0.25, 1.0]),
                                 "duty": 0.5, "floor": 0.0}, True))
    elif r < 0.76 and L >= 4 * beat:
        a.effects.append(Effect("stutter", "end", -2 * beat, 2 * beat,
                                {"beats": 0.5, "roll": "yes", "level": 1.0}, True))


def _plan_tempos(plan: MixPlan, songs: list[SongAnalysis]) -> list[bool]:
    """Fill in every track's speeds and every transition's tempo. Returns, per
    boundary, whether the two songs could be beat-matched."""
    s = plan.settings
    n = len(songs)
    ms = s.max_tempo_stretch
    for t in plan.tracks:
        t.rate_in = t.rate_out = 0.0
    locked = bool(s.master_bpm) or s.tempo_mode == "locked"
    if locked:
        master = float(s.master_bpm or choose_master_bpm(songs, s))
        plan.master_bpm = master
        ok = []
        for t, an in zip(plan.tracks, songs):
            eff = octave_bpm(an.bpm, master)
            want = master / eff
            t.matched = abs(want - 1) <= ms + 1e-9
            t.rate = float(want if t.matched else np.clip(want, 1 - ms, 1 + ms))
            t.bpm = eff * t.rate
            ok.append(t.matched)
        return [ok[i] and ok[i + 1] for i in range(n - 1)]
    # drift: every song keeps its own tempo; it only speeds up / slows down to meet its neighbour
    eff: list[float] = []
    for i, an in enumerate(songs):
        if i == 0:
            eff.append(float(an.bpm))
        else:
            eff.append(float(min((an.bpm / 2, an.bpm, an.bpm * 2), key=lambda c: abs(math.log(c / eff[-1])))))
    for t, e in zip(plan.tracks, eff):
        t.matched, t.rate, t.bpm = True, 1.0, e
    plan.master_bpm = float(np.median(eff)) if eff else 120.0
    out = []
    for i in range(n - 1):
        ratio = eff[i + 1] / eff[i]
        meet = math.sqrt(eff[i] * eff[i + 1])
        ok = abs(math.sqrt(ratio) - 1) <= ms + 1e-9 or abs(1 / math.sqrt(ratio) - 1) <= ms + 1e-9
        out.append(ok)
        if ok:
            plan.tracks[i].rate_out = meet / eff[i]
            plan.tracks[i + 1].rate_in = meet / eff[i + 1]
    return out


def recompute(plan: MixPlan, lib: dict[str, SongAnalysis], regen_effects: bool = True) -> MixPlan:
    """Refresh everything derived from the track order: tempos, per-track
    speed/pitch/gain, default bounds, transitions and AI effects. User edits are kept."""
    s = plan.settings
    songs = [lib[t.song_id] for t in plan.tracks]
    pair_ok = _plan_tempos(plan, songs)
    prev = None
    for t, an in zip(plan.tracks, songs):
        # key matching against the previous track as it will actually sound
        t.pitch = 0
        if s.key_match and prev is not None:
            best = None
            for p in range(-s.max_pitch_shift, s.max_pitch_shift + 1):
                tonic = (an.key_tonic + p) % 12
                c = key_cost(prev[0], prev[1], tonic, an.key_mode) + 0.45 * abs(p)
                if best is None or c < best[0] - 1e-9:
                    best = (c, p)
            t.pitch = best[1]
        prev = ((an.key_tonic + t.pitch) % 12, an.key_mode)
        t.gain_db = float(np.clip(s.track_lufs - an.loudness_lufs, -12, 12))
        if t.auto_bounds:
            t.src_start, t.src_end = default_bounds(an, s, t.rate)

    old = {(x.from_uid, x.to_uid): x for x in plan.transitions}
    new = []
    if regen_effects:
        for t in plan.tracks:
            t.effects = [e for e in t.effects if not e.auto]
    for i, (a, b) in enumerate(zip(plan.tracks, plan.tracks[1:])):
        rng = random.Random(f"{s.seed}:{a.song_id}:{b.song_id}")
        tr = old.get((a.uid, b.uid))
        meet = math.sqrt(a.bpm * b.bpm) if (a.rate_out or b.rate_in) and not (s.master_bpm or s.tempo_mode == "locked") else 0.0
        if tr is None or tr.auto:
            ttype, beats = _auto_transition(a, b, pair_ok[i], plan, lib, rng)
            tr = Transition(a.uid, b.uid, ttype, beats, True)
        tr.matched = bool(pair_ok[i])
        tr.tempo = float(meet)
        new.append(tr)
        if regen_effects and tr.auto:
            _auto_effects(a, b, tr, plan, rng)
    plan.transitions = new
    return plan


def plan_mix(lib: dict[str, SongAnalysis], song_ids: list[str], settings: MixSettings | None = None) -> MixPlan:
    settings = settings or MixSettings()
    songs = order_songs([lib[i] for i in song_ids], settings)
    plan = MixPlan(settings=settings, tracks=[TrackPlan(song_id=a.id) for a in songs])
    return recompute(plan, lib)


# ----------------------------------------------------------------------- timeline
@dataclass
class Slot:
    uid: str
    song_id: str
    start: int        # samples in the mix
    length: int       # samples
    overlap_in: int   # samples shared with the previous track
    overlap_out: int  # samples shared with the next track
    trans_in: Transition | None
    trans_out: Transition | None
    curve: RateCurve | None = None   # speed profile: curve.mix_time(source_seconds) -> seconds into the slot

    @property
    def end(self) -> int:
        return self.start + self.length

    def mix_seconds(self, src_seconds: float) -> float:
        """Seconds from the start of the whole mix at which a point of the source plays."""
        return self.start / SR + float(self.curve.mix_time(src_seconds))


def timeline(plan: MixPlan, sr: int = SR) -> list[Slot]:
    n = len(plan.tracks)
    nominal = [_mix_len(t) for t in plan.tracks]
    ov = []
    for i in range(n - 1):
        tr = plan.transition_after(i)
        sec = overlap_seconds(plan, tr)
        ov.append(int(round(min(sec, 0.45 * nominal[i], 0.45 * nominal[i + 1]) * sr)) if sec > 0 else 0)
    slots: list[Slot] = []
    pos = 0
    for i, t in enumerate(plan.tracks):
        ov_in = ov[i - 1] if i > 0 else 0
        ov_out = ov[i] if i < n - 1 else 0
        curve = track_curve(t, ov_in / sr, ov_out / sr)
        length = max(int(0.1 * sr), int(round(curve.total * sr)))
        tr_out = plan.transition_after(i)
        tr_in = plan.transition_after(i - 1) if i > 0 else None
        slots.append(Slot(t.uid, t.song_id, pos, length, ov_in, ov_out, tr_in, tr_out, curve))
        pos = pos + length - ov_out
    return slots


# ------------------------------------------------------------------- edit operations
def _find(plan: MixPlan, uid_or_index) -> int:
    if isinstance(uid_or_index, int):
        if not 0 <= uid_or_index < len(plan.tracks):
            raise IndexError(f"No track at position {uid_or_index + 1}")
        return uid_or_index
    for i, t in enumerate(plan.tracks):
        if t.uid == uid_or_index:
            return i
    raise KeyError(uid_or_index)


def move_track(plan, lib, src, dst):
    i = _find(plan, src)
    t = plan.tracks.pop(i)
    plan.tracks.insert(max(0, min(dst, len(plan.tracks))), t)
    return recompute(plan, lib)


def remove_track(plan, lib, which):
    plan.tracks.pop(_find(plan, which))
    return recompute(plan, lib)


def add_track(plan, lib, song_id, position=None):
    t = TrackPlan(song_id=song_id)
    plan.tracks.insert(len(plan.tracks) if position is None else position, t)
    recompute(plan, lib)
    return t


def set_track_bounds(plan, lib, which, src_start=None, src_end=None):
    t = plan.tracks[_find(plan, which)]
    if src_start is not None:
        t.src_start = float(src_start)
    if src_end is not None:
        t.src_end = float(src_end)
    if t.src_end - t.src_start < 2.0:
        raise ValueError("A track must play for at least 2 seconds")
    t.auto_bounds = False
    return recompute(plan, lib, regen_effects=False)


def set_transition(plan, lib, after_index, type=None, overlap_beats=None):
    tr = plan.transition_after(_find(plan, after_index))
    if tr is None:
        raise IndexError("There is no transition after the last track")
    if type is not None:
        if type not in ("eq_swap", "crossfade", "cut_fx", "cut"):
            raise ValueError(f"Unknown transition type '{type}'")
        tr.type = type
    if overlap_beats is not None:
        tr.overlap_beats = max(0, int(overlap_beats))
    tr.auto = False
    return plan


def add_effect(plan, which, kind, anchor="end", offset=None, duration=2.0, params=None) -> Effect:
    if kind not in fxmod.EFFECT_TYPES:
        raise ValueError(f"Unknown effect '{kind}'. Choose from: {', '.join(fxmod.EFFECT_TYPES)}")
    t = plan.tracks[_find(plan, which)]
    if offset is None:
        offset = -duration if anchor == "end" else 0.0
    e = Effect(kind, anchor, float(offset), float(duration), dict(params or {}), auto=False)
    t.effects.append(e)
    return e


def update_effect(plan, which, effect_id, **changes):
    t = plan.tracks[_find(plan, which)]
    for e in t.effects:
        if e.id == effect_id:
            for k, v in changes.items():
                if k == "params":
                    e.params.update(v)
                else:
                    setattr(e, k, v)
            e.auto = False
            return e
    raise KeyError(effect_id)


def remove_effect(plan, which, effect_id):
    t = plan.tracks[_find(plan, which)]
    before = len(t.effects)
    t.effects = [e for e in t.effects if e.id != effect_id]
    if len(t.effects) == before:
        raise KeyError(effect_id)
