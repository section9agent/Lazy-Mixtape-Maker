"""Mashups: two songs split into stems, laid out by hand or by the AI on a shared beat grid.

A Mashup holds two songs and a list of clips. A clip is a stretch of one stem of one song (its source times,
in the song's own seconds) placed at a time on the mashup's timeline. With beat matching on, both songs are
played at the mashup's tempo, so bars of the timeline and bars of each song line up; with key matching on,
one song is pitch-shifted to suit the other's key.

The timeline's time 0 is a downbeat, and timeline bars are 4 beats of the mashup's tempo."""
from __future__ import annotations

import json
import math
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from .analysis import SongAnalysis, key_cost, key_name
from .audio_io import SR

STEMS = ("vocals", "drums", "bass", "other")          # the order of the lanes of one song
MUSIC = ("drums", "bass", "other")
LANES = [(s, st) for s in (0, 1) for st in STEMS]      # 8 lanes: song A's four stems, then song B's
MAX_PITCH = 4                                         # semitones key matching may shift a song
STYLES = {
    "auto": "Let the AI choose",
    "b_over_a": "Song B's vocals over song A's music",
    "a_over_b": "Song A's vocals over song B's music",
    "trade": "Trade back and forth",
}
FORMAT = "lazy-mixtape-maker/mashup"
VOCAL_LEVELS = {"off": "Off", "gentle": "Gentle", "medium": "Medium", "strong": "Strong"}


class MashupError(RuntimeError):
    pass


def _uid() -> str:
    return uuid.uuid4().hex[:10]


@dataclass
class Clip:
    song: int                    # 0 = song A, 1 = song B
    stem: str                    # vocals | drums | bass | other
    src_start: float             # seconds in the song
    src_end: float
    start: float                 # seconds on the mashup's timeline
    gain_db: float = 0.0
    fade_in: float = 0.0         # seconds (on the timeline)
    fade_out: float = 0.0
    muted: bool = False
    id: str = field(default_factory=_uid)


@dataclass
class MashupSong:
    path: str = ""
    song_id: str = ""
    pitch: int | None = None     # semitones set by hand; None = automatic (key matching)


@dataclass
class Mashup:
    songs: list = field(default_factory=lambda: [MashupSong(), MashupSong()])
    clips: list = field(default_factory=list)
    beat_match: bool = True
    tempo_from: str = "a"        # a | b | custom
    custom_bpm: float = 120.0
    key_match: bool = True
    key_from: str = "a"          # the song whose key is kept (the other one moves)
    name: str = "Untitled mashup"
    vocal_level: str = "off"     # off | gentle | medium | strong: LUFS Lab's voice leveler on the vocal stems
    vocal_lufs: float = -18.0    # loudness the leveled vocals are set to
    level_songs: bool = True     # play both songs at the same loudness (each measured when it was imported)

    # ---------------------------------------------------------------- saving
    def to_dict(self) -> dict:
        return {"format": FORMAT, "version": 1, "name": self.name, "beat_match": self.beat_match,
                "tempo_from": self.tempo_from, "custom_bpm": self.custom_bpm, "key_match": self.key_match,
                "key_from": self.key_from, "vocal_level": self.vocal_level, "vocal_lufs": self.vocal_lufs,
                "level_songs": self.level_songs, "songs": [asdict(s) for s in self.songs], "clips": [asdict(c) for c in self.clips]}

    @classmethod
    def from_dict(cls, d: dict) -> "Mashup":
        if d.get("format") not in (None, FORMAT):
            raise MashupError("This isn't a mashup file.")
        songs = [MashupSong(**{k: v for k, v in s.items() if k in MashupSong.__dataclass_fields__}) for s in d.get("songs", [])]
        while len(songs) < 2:
            songs.append(MashupSong())
        clips = [Clip(**{k: v for k, v in c.items() if k in Clip.__dataclass_fields__}) for c in d.get("clips", [])]
        clips = [c for c in clips if c.song in (0, 1) and c.stem in STEMS and c.src_end > c.src_start]
        return cls(songs=songs[:2], clips=clips, beat_match=bool(d.get("beat_match", True)),
                   tempo_from=d.get("tempo_from", "a") if d.get("tempo_from") in ("a", "b", "custom") else "a",
                   custom_bpm=float(d.get("custom_bpm", 120.0)), key_match=bool(d.get("key_match", True)),
                   key_from=d.get("key_from", "a") if d.get("key_from") in ("a", "b") else "a",
                   name=str(d.get("name") or "Untitled mashup"),
                   vocal_level=d.get("vocal_level", "off") if d.get("vocal_level") in VOCAL_LEVELS else "off",
                   vocal_lufs=float(min(-6.0, max(-36.0, d.get("vocal_lufs", -18.0)))),
                   level_songs=bool(d.get("level_songs", True)))

    def save(self, file) -> None:
        Path(file).write_text(json.dumps(self.to_dict(), indent=1), encoding="utf-8")

    @classmethod
    def load(cls, file) -> "Mashup":
        try:
            return cls.from_dict(json.loads(Path(file).read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError) as e:
            raise MashupError(f"Couldn't read {Path(file).name}: {e}") from None

    def clip(self, cid: str) -> Clip | None:
        return next((c for c in self.clips if c.id == cid), None)

    def ready(self) -> bool:
        return all(s.song_id for s in self.songs)


# -------------------------------------------------------------- tempo and key
def _octave(bpm: float, target: float) -> float:
    """`bpm`, doubled or halved to sit closest to `target` (a 70 BPM song suits a 140 BPM one)."""
    best = bpm
    for k in (0.5, 2.0):
        if abs(math.log(bpm * k / target)) < abs(math.log(best / target)):
            best = bpm * k
    return best


def tempo(m: Mashup, lib: dict) -> float:
    """The mashup's BPM."""
    if m.tempo_from == "custom":
        return float(min(220.0, max(50.0, m.custom_bpm)))
    i = 0 if m.tempo_from == "a" else 1
    sid = m.songs[i].song_id
    return float(lib[sid].bpm) if sid in lib else 120.0


SONG_LUFS = -16.0                # what "level the songs" brings each song to (the mixes use the same)


def song_gain_db(m: Mashup, lib: dict, i: int) -> float:
    """The gain that brings song i to SONG_LUFS (0 when levelling is off or the song isn't analysed)."""
    an = lib.get(m.songs[i].song_id)
    if not m.level_songs or an is None or not np.isfinite(getattr(an, "loudness_lufs", np.nan)):
        return 0.0
    return float(np.clip(SONG_LUFS - an.loudness_lufs, -20.0, 15.0))


def rate(m: Mashup, lib: dict, i: int) -> float:
    """Playback speed of song i (1.0 = as recorded)."""
    an = lib.get(m.songs[i].song_id)
    if not m.beat_match or an is None:
        return 1.0
    target = tempo(m, lib)
    return float(np.clip(target / _octave(an.bpm, target), 0.5, 2.0))


def auto_pitch(m: Mashup, lib: dict, i: int) -> int:
    """The shift key matching gives song i: 0 for the song whose key is kept, else the smallest shift
    (at most MAX_PITCH semitones) that puts it in a key that goes with the other song."""
    keep = 0 if m.key_from == "a" else 1
    if not m.key_match or i == keep:
        return 0
    a, b = lib.get(m.songs[keep].song_id), lib.get(m.songs[i].song_id)
    if a is None or b is None:
        return 0
    best = min(range(-MAX_PITCH, MAX_PITCH + 1),
               key=lambda p: (key_cost(a.key_tonic, a.key_mode, (b.key_tonic + p) % 12, b.key_mode), abs(p)))
    return int(best)


def pitch(m: Mashup, lib: dict, i: int) -> int:
    p = m.songs[i].pitch
    return int(p) if p is not None else auto_pitch(m, lib, i)


def key_after(m: Mashup, lib: dict, i: int) -> str:
    an = lib.get(m.songs[i].song_id)
    return key_name((an.key_tonic + pitch(m, lib, i)) % 12, an.key_mode) if an else ""


def bar_seconds(m: Mashup, lib: dict) -> float:
    """Length of one bar of the timeline."""
    return 240.0 / tempo(m, lib)


def clip_length(m: Mashup, lib: dict, c: Clip) -> float:
    """Seconds the clip takes on the timeline."""
    return (c.src_end - c.src_start) / rate(m, lib, c.song)


def length(m: Mashup, lib: dict) -> float:
    return max([c.start + clip_length(m, lib, c) for c in m.clips] or [0.0])


def song_time_at(m: Mashup, lib: dict, i: int, t: float, anchor_src: float = 0.0, anchor_t: float = 0.0) -> float:
    """The source time of song i that plays at timeline time t, if the song runs from `anchor_src` at `anchor_t`."""
    return anchor_src + (t - anchor_t) * rate(m, lib, i)


def snap_src(an: SongAnalysis, s: float, beats: bool = False) -> float:
    """The song's nearest downbeat (or beat) to source time s."""
    step = an.beat_period if beats else an.bar_length
    return an.grid_origin + round((s - an.grid_origin) / step) * step


def first_bar(an: SongAnalysis) -> float:
    """The song's first downbeat at or after the moment it becomes audible (never before the file starts)."""
    return max(0.0, an.bar_time(an.bar_index_at_or_after(an.audio_start, tol=0.05)))


# ------------------------------------------------------------------ editing
def add_clip(m: Mashup, lib: dict, song: int, stem: str, start: float, bars: float = 8.0, src_start: float | None = None) -> Clip:
    """A new clip of `bars` timeline bars at `start`. Without a source time, the song's bar that "belongs" at
    that point (as if the song had started at the timeline's beginning from its first downbeat)."""
    an = lib[m.songs[song].song_id]
    r = rate(m, lib, song)
    if src_start is None:
        src_start = snap_src(an, first_bar(an) + start * r)
    src_start = float(min(max(0.0, src_start), max(0.0, an.duration - 1.0)))
    src_end = float(min(an.duration, src_start + bars * bar_seconds(m, lib) * r))
    c = Clip(song=song, stem=stem, src_start=src_start, src_end=src_end, start=max(0.0, float(start)))
    m.clips.append(c)
    return c


def split_clip(m: Mashup, lib: dict, cid: str, at: float) -> Clip | None:
    """Cut a clip in two at timeline time `at`. Returns the second half."""
    c = m.clip(cid)
    if c is None:
        return None
    L = clip_length(m, lib, c)
    if not (c.start + 0.05 < at < c.start + L - 0.05):
        return None
    s = c.src_start + (at - c.start) * rate(m, lib, c.song)
    d = Clip(**{**asdict(c), "id": _uid(), "src_start": s, "start": at, "fade_in": 0.0})
    c.src_end, c.fade_out = s, 0.0
    m.clips.insert(m.clips.index(c) + 1, d)
    return d


def duplicate_clip(m: Mashup, lib: dict, cid: str) -> Clip | None:
    c = m.clip(cid)
    if c is None:
        return None
    d = Clip(**{**asdict(c), "id": _uid(), "start": c.start + clip_length(m, lib, c)})
    m.clips.append(d)
    return d


def full_song(m: Mashup, lib: dict, song: int, start: float = 0.0) -> list[Clip]:
    """All four stems of a song from its first downbeat to its end - the song as it is - at `start`."""
    an = lib[m.songs[song].song_id]
    s0 = first_bar(an)
    out = []
    for st in STEMS:
        c = Clip(song=song, stem=st, src_start=s0, src_end=an.duration, start=start)
        m.clips.append(c)
        out.append(c)
    return out


# --------------------------------------------------------------- the AI
def vocal_bars(an: SongAnalysis, song_id: str) -> np.ndarray:
    """How loud the song's vocals are in each of its bars (bar j starts at an.bar_time(j0 + j)), 0..1."""
    from . import stems
    sr = 11025
    try:
        y = stems.load(song_id, "vocals", sr=sr).mean(axis=1)
    except Exception:  # noqa: BLE001
        return np.zeros(0)
    j0 = an.bar_index_at_or_after(0.0)
    out = []
    j = j0
    while True:
        a, b = an.bar_time(j), an.bar_time(j + 1)
        if b > an.duration:
            break
        seg = y[int(a * sr):int(b * sr)]
        out.append(float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0)
        j += 1
    v = np.array(out)
    top = np.percentile(v, 95) if len(v) else 0.0
    return v / top if top > 1e-6 else np.zeros_like(v)


def _vocal_span(an: SongAnalysis, sid: str):
    """(first, last) source time of the song's sung part, on downbeats; None when it has no vocals."""
    v = vocal_bars(an, sid)
    on = np.nonzero(v > 0.3)[0]
    if len(on) == 0:
        return None
    j0 = an.bar_index_at_or_after(0.0)
    first, last = int(on[0]), int(on[-1])
    return an.bar_time(j0 + first), an.bar_time(j0 + last + 1), float(np.mean(v > 0.3))


def _intro_bars(an: SongAnalysis) -> int:
    """How long to let a song's music play before the other singer comes in: its intro, 4 to 16 bars."""
    s0 = first_bar(an)
    for sec in an.sections:
        if sec.end > s0 + 1.0:
            if sec.label.lower().startswith("intro"):
                bars = round((sec.end - s0) / an.bar_length)
                return int(min(16, max(4, 4 * round(bars / 4))))
            break
    return 8


def auto_mashup(m: Mashup, lib: dict, style: str = "auto") -> str:
    """Replace the clips with an arrangement by the AI. Returns the style used. Both songs must have stems."""
    if not m.ready():
        raise MashupError("Choose two songs first.")
    ids = [s.song_id for s in m.songs]
    ans = [lib[i] for i in ids]
    spans = [_vocal_span(an, sid) for an, sid in zip(ans, ids)]
    if style == "auto":
        # the song that sings more lends its vocals; the other its music
        share = [sp[2] if sp else 0.0 for sp in spans]
        style = "b_over_a" if share[1] >= share[0] else "a_over_b"
    m.clips.clear()
    m.beat_match = True
    if style == "trade":
        m.tempo_from, m.key_from = "a", "a"
        _trade(m, lib, ans, spans)
        return style
    music, voice = (0, 1) if style == "b_over_a" else (1, 0)
    m.tempo_from = m.key_from = "ab"[music]
    _vocals_over(m, lib, ans, spans, music, voice)
    return style


def _vocals_over(m, lib, ans, spans, music: int, voice: int):
    bar = bar_seconds(m, lib)
    am, av = ans[music], ans[voice]
    rm, rv = rate(m, lib, music), rate(m, lib, voice)
    m0 = first_bar(am)
    music_bars = int((am.duration - m0) / rm / bar)          # bars of the music song there are to use
    intro = _intro_bars(am)
    sp = spans[voice] or (first_bar(av), av.duration, 0.0)
    v0, v1 = sp[0], sp[1]
    v_bars = int((v1 - v0) / rv / bar)
    v_bars = max(4, min(v_bars, music_bars - intro - 4))
    v_bars = 4 * (v_bars // 4) or 4
    outro = min(8, max(0, music_bars - intro - v_bars))
    total = intro + v_bars + outro
    for st in MUSIC:
        c = Clip(song=music, stem=st, src_start=m0, src_end=min(am.duration, m0 + total * bar * rm), start=0.0)
        c.fade_out = 4 * bar if outro >= 4 else bar
        m.clips.append(c)
    vc = Clip(song=voice, stem="vocals", src_start=v0, src_end=min(av.duration, v0 + v_bars * bar * rv),
              start=intro * bar, fade_in=bar / 8, fade_out=bar / 2)
    m.clips.append(vc)


def _trade(m, lib, ans, spans):
    """Both songs run side by side; every 16 bars the music swaps from one song to the other and the singer
    with it - while one song plays its music, the other one sings over it."""
    bar = bar_seconds(m, lib)
    r = [rate(m, lib, i) for i in (0, 1)]
    starts = [first_bar(an) for an in ans]
    # start each song so that its singing begins together, after an 8-bar intro of song A's music
    sing = [sp[0] if sp else st for sp, st in zip(spans, starts)]
    intro = 8
    # source time of each song at timeline 0 - never before the song's first downbeat
    anchor = [max(starts[i], sing[i] - intro * bar * r[i]) for i in (0, 1)]
    avail = [int((ans[i].duration - anchor[i]) / r[i] / bar) for i in (0, 1)]
    swaps = max(1, (min(avail) - intro) // 16)
    def src(i, t):
        return anchor[i] + t * r[i]
    t, k = 0.0, 0
    blocks = [(0, intro)] + [(1 + (j % 2), 16) for j in range(swaps)]
    for who, bars in blocks:
        music = 0 if who in (0, 1) else 1
        voice = 1 - music
        t1 = t + bars * bar
        for st in MUSIC:
            if src(music, t) >= 0:
                m.clips.append(Clip(song=music, stem=st, src_start=src(music, t), src_end=src(music, t1), start=t,
                                    fade_in=0.0 if k == 0 else bar / 16, fade_out=bar / 16))
        if who != 0 and src(voice, t) >= 0:
            m.clips.append(Clip(song=voice, stem="vocals", src_start=src(voice, t), src_end=src(voice, t1), start=t,
                                fade_in=bar / 16, fade_out=bar / 16))
        t, k = t1, k + 1
    for c in m.clips:                                             # ease out at the very end
        if abs(c.start + clip_length(m, lib, c) - t) < 1e-6:
            c.fade_out = 2 * bar
    for c in m.clips:
        an = ans[c.song]
        c.src_end = min(c.src_end, an.duration)
    m.clips[:] = [c for c in m.clips if c.src_end - c.src_start > 0.05]


# ------------------------------------------------------------- waveforms
WAVE_STEP = 0.05                 # seconds per value of a stem's drawn envelope


def stem_waves(song_id: str) -> dict:
    """Each stem's loudness envelope for drawing - one value 0..1 per WAVE_STEP seconds of the song, scaled
    together so a quiet stem looks quiet next to a loud one. Kept beside the stems once worked out."""
    import soundfile as sf

    from . import stems
    files = stems.cached(song_id)
    if not files:
        return {}
    cache = next(iter(files.values())).parent / "waves.npz"
    try:
        z = np.load(cache)
        if set(z.files) >= set(files):
            return {k: z[k] for k in files}
    except (OSError, ValueError, EOFError):
        pass
    out = {}
    for name, f in files.items():
        y, sr = sf.read(str(f), dtype="float32", always_2d=True)
        hop = max(1, int(sr * WAVE_STEP))
        a = np.abs(y).max(axis=1)
        m = len(a) // hop * hop
        pk = a[:m].reshape(-1, hop).max(axis=1) if m else np.zeros(1, np.float32)
        out[name] = pk
    top = max([float(v.max()) for v in out.values()] + [1e-9])
    out = {k: np.sqrt(v / top).astype(np.float32) for k, v in out.items()}
    try:
        np.savez_compressed(cache, **out)
    except OSError:
        pass
    return out


# --------------------------------------------------------------- rendering
class Renderer:
    """Renders mashups, keeping each song's stems ready at the current speed and pitch so that moving clips
    around and playing again is quick."""

    def __init__(self):
        self._ready: dict[tuple, dict] = {}

    def prepare(self, m: Mashup, lib: dict, paths: dict, i: int, progress=None) -> dict:
        """Song i's four stems at the mashup's speed and pitch (cached)."""
        from . import stems
        from .render import render_track_audio
        from .tempo import RateCurve

        sid = m.songs[i].song_id
        r, p = rate(m, lib, i), pitch(m, lib, i)
        lev = (m.vocal_level, round(m.vocal_lufs, 2)) if m.vocal_level != "off" else ("off",)
        key = (sid, round(r, 6), p, lev)
        if key in self._ready:
            return self._ready[key]
        same = [k for k in self._ready if k[:3] == key[:3]]
        if same:                                     # only the vocal leveling changed: redo just the vocals
            st = dict(self._ready.pop(same[0]))
            st["vocals"] = self._level(m, st.get("_raw_vocals", st.get("vocals")))
            if "_raw_vocals" not in st and "vocals" in st:
                st["_raw_vocals"] = st["vocals"]
            self._ready[key] = st
            return st
        files = stems.cached(sid)
        if not files:
            raise MashupError(f"{lib[sid].title or 'This song'} hasn't been split into stems yet.")
        an = lib[sid]
        for k in [k for k in self._ready if k[0] == sid]:           # keep one version per song in memory (plus raw vocals)
            del self._ready[k]
        if progress:
            progress(f"Getting {an.title or 'the song'} ready…", 0.0)

        class T:                                                   # the parts of a TrackPlan the renderer reads
            src_start, src_end, pitch = 0.0, float(an.duration), p
        _, st = render_track_audio(paths[sid], T, RateCurve([0.0, an.duration], [r, r]), an,
                                   stems={s: files[s] for s in STEMS if s in files}, lag=stems.lag(sid, paths[sid]))
        if "vocals" in st:
            st["_raw_vocals"] = st["vocals"]
            st["vocals"] = self._level(m, st["vocals"])
        self._ready[key] = st
        return st

    @staticmethod
    def _level(m: Mashup, vocals):
        """LUFS Lab's voice leveler on a vocal stem, when it's switched on."""
        if vocals is None or m.vocal_level == "off":
            return vocals
        from .loudness import level_voice
        return level_voice(vocals, SR, m.vocal_level, m.vocal_lufs)

    def render(self, m: Mashup, lib: dict, paths: dict, progress=None, start: float = 0.0, end: float | None = None) -> np.ndarray:
        """The mashup (or the part of it from `start` to `end`) as (2, n) audio."""
        say = progress or (lambda *_: None)
        total = length(m, lib)
        end = total if end is None else min(end, total)
        n = max(1, int(round((end - start) * SR)))
        out = np.zeros((2, n), np.float32)
        live = [c for c in m.clips if not c.muted]
        used = sorted({c.song for c in live})
        ready = {}
        for k, i in enumerate(used):
            ready[i] = self.prepare(m, lib, paths, i, progress=lambda msg, f, k=k: say(msg, (k + f) / max(1, len(used)) * 0.9))
        say("Mixing…", 0.92)
        for c in live:
            audio = ready[c.song].get(c.stem)       # (never the "_raw_vocals" kept for re-leveling)
            if audio is None:
                continue
            r = rate(m, lib, c.song)
            a = int(round(c.src_start / r * SR))
            L = int(round((c.src_end - c.src_start) / r * SR))
            lead = max(0, -a)                                         # a clip may start before the song does
            seg = audio[:, max(0, a):a + L].astype(np.float32, copy=True)
            seg = np.pad(seg, ((0, 0), (lead, max(0, L - lead - seg.shape[1]))))[:, :L]
            lvl = 0.0 if (c.stem == "vocals" and m.vocal_level != "off") else song_gain_db(m, lib, c.song)
            env = np.full(L, 10 ** ((c.gain_db + lvl) / 20), np.float32)      # (leveled vocals are set already)
            fi, fo = min(L, int(c.fade_in * SR)), min(L, int(c.fade_out * SR))
            if fi > 0:
                env[:fi] *= np.sin(np.linspace(0, math.pi / 2, fi)) ** 2
            if fo > 0:
                env[L - fo:] *= np.cos(np.linspace(0, math.pi / 2, fo)) ** 2
            edge = min(L // 2, int(0.003 * SR))                       # no clicks at a clip's ends
            if edge > 0:
                env[:edge] *= np.linspace(0, 1, edge)
                env[L - edge:] *= np.linspace(1, 0, edge)
            seg *= env
            pos = int(round((c.start - start) * SR))
            lo, hi = max(0, pos), min(n, pos + L)
            if hi > lo:
                out[:, lo:hi] += seg[:, lo - pos:hi - pos]
        peak = float(np.max(np.abs(out))) if out.size else 0.0
        if peak > 0.97:                                               # stacked stems can clip: bring it down
            out *= 0.97 / peak
        say("Done", 1.0)
        return out


def export(m: Mashup, lib: dict, paths: dict, out_path, progress=None, renderer: Renderer | None = None) -> dict:
    from .audio_io import write_audio
    audio = (renderer or Renderer()).render(m, lib, paths, progress)
    write_audio(out_path, audio, metadata={"title": m.name, "artist": "Lazy Mixtape Maker"})
    return {"audio": str(out_path), "seconds": audio.shape[1] / SR}
