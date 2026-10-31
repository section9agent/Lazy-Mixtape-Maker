"""Visualization Studio: make a video for a mixtape you already have.

Import any audio file, mark where the songs change (by hand, or from a .cue sheet / text
track list), pick the visuals (one for everything, one per song, or random) and export an
mp4. The same cover-art / artist / title card and cross-fades as the mix videos."""
from __future__ import annotations

import dataclasses
import json
import re
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import audio_io
from .video import Segment, VideoSettings, pick_visuals, render_segments
from .visuals import BUILTIN, ShaderLibrary

FORMAT = "lazy-mixtape-visualization"
VERSION = 1
TEXTURE_SR = 22050
LONG_TEXTURE_SR = 11025          # for very long files, to keep memory sane
LONG_SECONDS = 40 * 60


def _uid() -> str:
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------- the model
@dataclass
class Marker:
    """Where one song starts."""
    time: float = 0.0
    artist: str = ""
    title: str = ""
    cover: str = ""                  # path of an image for this song's card ("" = none)
    shader: str = ""                 # this song's visual in "I choose per song" mode ("" = not chosen yet)
    uid: str = field(default_factory=_uid)
    # A video placed on the timeline instead of a visual: {"path", "start" (timeline seconds where the video's
    # first frame plays), "speed" (1.0 = normal), "loop"}. Its own sound is never used.
    clip: dict = field(default_factory=dict)


@dataclass
class StudioProject:
    audio: str = ""
    audio_id: str = ""               # content fingerprint, to find the file again on another computer
    duration: float = 0.0
    name: str = "Untitled"
    file_artist: str = ""            # tags of the imported file (shown until the first marker)
    file_title: str = ""
    markers: list[Marker] = field(default_factory=list)
    video: VideoSettings = field(default_factory=VideoSettings)

    # ------------------------------------------------------------------ editing
    def _sort(self) -> None:
        self.markers.sort(key=lambda m: m.time)

    def find(self, uid: str) -> Marker | None:
        return next((m for m in self.markers if m.uid == uid), None)

    def clamp(self, t: float) -> float:
        hi = self.duration if self.duration > 0 else float("inf")
        return float(min(max(0.0, t), hi))

    def add_marker(self, time: float, artist: str = "", title: str = "", **kw) -> Marker:
        m = Marker(self.clamp(time), artist, title, **kw)
        if not m.title and not m.artist:
            m.title = f"Song {len(self.markers) + 1}"
        self.markers.append(m)
        self._sort()
        return m

    def move_marker(self, uid: str, time: float) -> None:
        m = self.find(uid)
        if m:
            m.time = self.clamp(time)
            self._sort()

    def remove_marker(self, uid: str) -> None:
        self.markers = [m for m in self.markers if m.uid != uid]

    def update_marker(self, uid: str, **fields) -> None:
        m = self.find(uid)
        if not m:
            return
        for k, v in fields.items():
            if k not in ("time", "artist", "title", "cover", "shader", "clip"):
                raise KeyError(k)
            setattr(m, k, self.clamp(v) if k == "time" else v)
        self._sort()

    def set_clip(self, uid: str, path: str | None = None, **fields) -> None:
        """Put a video on a song (path given), or change its start / speed / loop (path omitted)."""
        m = self.find(uid)
        if not m:
            return
        if path is not None:
            m.clip = {"path": str(path), "start": float(m.time), "speed": 1.0, "loop": False}
        if not m.clip:
            return
        for k, v in fields.items():
            if k == "off":                           # True: a visual is used instead; the video stays here to switch back to
                if v:
                    m.clip["off"] = True
                else:
                    m.clip.pop("off", None)
            elif k == "start":
                m.clip["start"] = float(v)
            elif k == "speed":
                m.clip["speed"] = float(min(4.0, max(0.1, v)))
            elif k == "loop":
                m.clip["loop"] = bool(v)
            else:
                raise KeyError(k)

    def clear_clip(self, uid: str) -> None:
        m = self.find(uid)
        if m:
            m.clip = {}

    def set_markers(self, rows: list[dict]) -> None:
        """Replace all markers (used when a cue sheet is imported)."""
        self.markers = [Marker(self.clamp(r["time"]), r.get("artist", ""), r.get("title", "")) for r in rows]
        self._sort()
        self.video.assignments = {}

    # --------------------------------------------------------------- persistence
    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["video"] = self.video.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "StudioProject":
        p = cls(**{k: v for k, v in d.items() if k in ("audio", "audio_id", "duration", "name", "file_artist", "file_title")})
        p.markers = [Marker(**{k: v for k, v in m.items() if k in Marker.__dataclass_fields__}) for m in d.get("markers", [])]
        p.video = VideoSettings.from_dict(d.get("video"))
        p._sort()
        return p


_durations: dict[str, float] = {}


def _clip_duration(path: str) -> float:
    if path not in _durations:
        _durations[path] = probe_duration(path)
    return _durations[path]


def clip_active(m: "Marker") -> bool:
    """The song shows its own placed video (not switched to a visual)."""
    return bool(m.clip and m.clip.get("path") and not m.clip.get("off"))


def clip_extent(m: "Marker") -> tuple[float, float] | None:
    """(start, end) on the timeline of the video placed on a song, or None. A looping clip has no end of its own."""
    if not clip_active(m):
        return None
    d = _clip_duration(m.clip["path"])
    sp = float(m.clip.get("speed", 1.0)) or 1.0
    st = float(m.clip.get("start", m.time))
    return st, st + (d / sp if d > 0 else 0.0)


def segment_bounds(p: "StudioProject", uid: str) -> tuple[float, float]:
    ms = sorted(p.markers, key=lambda m: m.time)
    for i, m in enumerate(ms):
        if m.uid == uid:
            return m.time, (ms[i + 1].time if i + 1 < len(ms) else (p.duration or m.time + 60.0))
    return 0.0, p.duration


def auto_sync_clip(p: "StudioProject", uid: str, progress=None):
    """Best-guess the start of the video placed on a song by comparing its sound with the music of that song.
    Updates the project's clip start when a match is found. Returns the videosync.SyncResult."""
    from . import videosync

    m = p.find(uid)
    if not (m and m.clip.get("path")):
        raise ValueError("That song has no video.")
    t0, t1 = segment_bounds(p, uid)
    res = videosync.estimate_offset(p.audio, t0, t1, m.clip["path"], progress)
    if res.found:
        # the video's own speed matters little for the start: its first frame sits `offset` after the segment start
        m.clip["start"] = float(t0 + res.offset)
    return res


def has_source_video(p: "StudioProject") -> bool:
    return bool(p.audio) and audio_io.is_video_file(p.audio)


def new_project(audio_path, name: str = "") -> StudioProject:
    """Open an audio file: length, tags and a first marker at 0:00."""
    path = Path(audio_path)
    if path.suffix.lower() not in audio_io.AUDIO_EXTS:
        raise audio_io.AudioError(f"{path.name} isn't an mp3, wav, flac, m4a or video file.")
    tags = audio_io.read_tags(path)
    p = StudioProject(audio=str(path.resolve()), audio_id=audio_io.file_id(path), duration=probe_duration(path),
                      name=name or path.stem, file_artist=tags["artist"], file_title=tags["title"])
    p.markers.append(Marker(0.0, tags["artist"], tags["title"]))
    return p


def save_project(p: StudioProject, file, shaders: ShaderLibrary | None = None) -> None:
    shaders = shaders or ShaderLibrary()
    used = {m.shader for m in p.markers if m.shader} | {p.video.single_shader}
    doc = {"format": FORMAT, "version": VERSION, "project": p.to_dict(), "shaders": shaders.export_used(used),
           "filename": Path(p.audio).name}
    file = Path(file)
    tmp = file.with_suffix(file.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    tmp.replace(file)


def load_project(file, shaders: ShaderLibrary | None = None, search_dirs=()) -> StudioProject:
    file = Path(file)
    doc = json.loads(file.read_text(encoding="utf-8"))
    if doc.get("format") != FORMAT:
        raise ValueError(f"{file.name} is not a Lazy Mixtape visualization project")
    if doc.get("version", 0) > VERSION:
        raise ValueError("This project was saved by a newer version of Lazy Mixtape Maker")
    (shaders or ShaderLibrary()).import_embedded(doc.get("shaders", {}))
    p = StudioProject.from_dict(doc["project"])
    if not Path(p.audio).is_file():
        relink_audio(p, [file.resolve().parent, *map(Path, search_dirs)], doc.get("filename", ""))
    return p


def relink_audio(p: StudioProject, folders, filename: str = "") -> bool:
    """Find this project's audio again (same content, any name or folder)."""
    files = audio_io.list_audio_files([f for f in folders if Path(f).exists()])
    name = filename or Path(p.audio).name
    for f in sorted(files, key=lambda f: f.name != name):
        try:
            if audio_io.file_id(f) == p.audio_id:
                p.audio = str(f.resolve())
                return True
        except OSError:
            continue
    return False


# --------------------------------------------------------------- cue / track lists
def _read_text(path) -> str:
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return raw.decode("latin-1", errors="replace")


def _unquote(s: str) -> str:
    s = s.strip()
    if s.startswith('"') and s.count('"') >= 2:
        s = s[1:s.rindex('"')].replace('""', '"')
    return s.strip()


def parse_cue(text: str) -> list[dict]:
    """Track starts from a .cue sheet: [{time, artist, title}] in seconds."""
    top_artist = ""
    rows: list[dict] = []
    cur: dict | None = None
    for line in text.splitlines():
        ln = line.strip()
        if not ln or ln.upper().startswith("REM"):
            continue
        key, _, rest = ln.partition(" ")
        key = key.upper()
        if key == "TRACK":
            cur = {"time": None, "t00": None, "artist": "", "title": ""}
            rows.append(cur)
        elif key == "PERFORMER":
            if cur is None:
                top_artist = _unquote(rest)
            else:
                cur["artist"] = _unquote(rest)
        elif key == "TITLE" and cur is not None:
            cur["title"] = _unquote(rest)
        elif key == "INDEX" and cur is not None:
            m = re.match(r"(\d+)\s+(\d+):(\d{1,2}):(\d{1,2})", rest.strip())
            if m:
                n, mm, ss, ff = (int(x) for x in m.groups())
                t = mm * 60 + ss + ff / 75.0
                if n == 1:
                    cur["time"] = t
                elif n == 0:
                    cur["t00"] = t
    out = []
    for r in rows:
        t = r["time"] if r["time"] is not None else r["t00"]
        if t is None:
            continue
        artist = r["artist"] or ("" if re.search(r"various", top_artist, re.I) else top_artist)
        out.append({"time": float(t), "artist": artist, "title": r["title"]})
    out.sort(key=lambda r: r["time"])
    return out


_TIME_LINE = re.compile(
    r"^\s*(?:\d{1,3}[.)]\s+)?[\[\(]?\s*(?:(\d{1,2}):)?(\d{1,3}):(\d{2})(?:[.,]\d+)?\s*[\]\)]?\s*[-–—:.]?\s*(.+?)\s*$")


def parse_tracklist(text: str) -> list[dict]:
    """Lines like '3:45  Artist - Title' or '[1:02:03] Artist – Title [8A / 124 BPM]'."""
    out = []
    for line in text.splitlines():
        m = _TIME_LINE.match(line)
        if not m:
            continue
        h, mm, ss, rest = m.groups()
        t = int(h or 0) * 3600 + int(mm) * 60 + int(ss)
        rest = re.sub(r"\s*\[[^\]]*\]\s*$", "", rest).strip()
        if not rest:
            continue
        if " - " in rest:
            artist, _, title = rest.partition(" - ")
        elif " – " in rest:
            artist, _, title = rest.partition(" – ")
        else:
            artist, title = "", rest
        out.append({"time": float(t), "artist": artist.strip(), "title": title.strip()})
    out.sort(key=lambda r: r["time"])
    return out


def import_cue_file(path) -> list[dict]:
    """A .cue sheet, or a plain-text track list; whichever the file turns out to be."""
    text = _read_text(path)
    rows = parse_cue(text) if re.search(r"^\s*TRACK\s+\d+", text, re.I | re.M) else parse_tracklist(text)
    if not rows:
        raise ValueError("Couldn't find any track times in that file. Use a .cue sheet, or a text list with a time "
                         "at the start of each line (for example “12:34  Artist - Title”).")
    return rows


# ------------------------------------------------------------------ audio helpers
def probe_duration(path) -> float:
    err = subprocess.run([audio_io.ffmpeg(), "-hide_banner", "-nostdin", "-i", str(path)],
                         capture_output=True, text=True).stderr
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0


OVERVIEW_SR = 4000


def overview(path, bins: int = 2400) -> tuple[np.ndarray, np.ndarray]:
    """-> ((bins, 2) min/max peaks for drawing, the 4 kHz mono audio for loudness-based choices)."""
    x = audio_io.decode(path, sr=OVERVIEW_SR, channels=1)[0]
    return _peaks(x, bins), x


def waveform_peaks(path, bins: int = 1600) -> np.ndarray:
    return overview(path, bins)[0]


def _peaks(x: np.ndarray, bins: int) -> np.ndarray:
    if len(x) < bins:
        x = np.pad(x, (0, bins - len(x)))
    n = len(x) // bins * bins
    v = x[:n].reshape(bins, -1)
    return np.stack([v.min(axis=1), v.max(axis=1)], axis=1).astype(np.float32)


def make_playback_copy(path, out_path) -> str:
    """44.1 kHz stereo 16-bit FLAC the preview player can stream (any length, no big arrays)."""
    cmd = [audio_io.ffmpeg(), "-v", "error", "-nostdin", "-y", "-i", str(path), "-vn", "-ac", "2", "-ar", "44100",
           "-sample_fmt", "s16", "-c:a", "flac", "-compression_level", "0", str(out_path)]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise audio_io.AudioError("Couldn't prepare the audio for playback: " + proc.stderr.decode(errors="replace")[:300])
    return str(out_path)


def segment_energies(mono: np.ndarray, sr: int, bounds: list[tuple[float, float]]) -> list[float]:
    """0..1 'how loud/intense' per song (loudness rank among the songs), for the app-chosen visuals."""
    rms = []
    for a, b in bounds:
        seg = mono[int(a * sr): max(int(a * sr) + 1, int(b * sr))]
        rms.append(float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0)
    n = len(rms)
    if n < 2:
        return [0.5] * n
    order = np.argsort(np.argsort(rms))
    return [0.12 + 0.76 * float(o) / (n - 1) for o in order]


# --------------------------------------------------------------------- the video
def effective_markers(p: StudioProject) -> list[Marker]:
    """The markers as the video uses them: starting at 0:00 (an unnamed opening part gets the file's tags)."""
    ms = sorted(p.markers, key=lambda m: m.time)
    if not ms or ms[0].time > 1.0:
        ms = [Marker(0.0, p.file_artist, p.file_title or p.name, uid="open")] + ms
    return ms


def fade_windows(times: list[float], blend: float) -> list[tuple[float, float]]:
    """Cross-fade window around each boundary (centred on the marker, never overlapping its neighbours)."""
    wins = []
    for i in range(1, len(times)):
        gap_before = times[i] - times[i - 1]
        gap_after = (times[i + 1] - times[i]) if i + 1 < len(times) else float("inf")
        half = max(0.2, min(blend / 2.0, 0.45 * gap_before, 0.45 * gap_after))
        wins.append((times[i] - half, times[i] + half))
    return wins


def build_segments(p: StudioProject, shaders: ShaderLibrary, seconds: float,
                   energies_from: tuple[np.ndarray, int] | None = None, file_cover: str | None = None):
    """-> (segments, fade windows) for the renderer and for live previews."""
    ms = effective_markers(p)
    ms[0] = dataclasses.replace(ms[0], time=0.0)
    times = [min(m.time, max(0.0, seconds - 0.1)) for m in ms]
    vs = dataclasses.replace(p.video, assignments={m.uid: m.shader for m in ms if m.shader})
    energies: list[float | None] = [None] * len(ms)
    if energies_from is not None and vs.mode == "auto":
        mono, sr = energies_from
        bounds = [(times[i], times[i + 1] if i + 1 < len(times) else seconds) for i in range(len(ms))]
        energies = segment_energies(mono, sr, bounds)
    ids = pick_visuals([m.uid for m in ms], energies, vs, shaders)
    segs = []
    is_video = p.audio and audio_io.is_video_file(p.audio) and vs.use_video
    for m, t, sid in zip(ms, times, ids):
        if m.cover == "none":                      # asked for no cover at all (even if the file has one)
            cover = None
        else:
            cover = m.cover if m.cover and Path(m.cover).is_file() else (file_cover if m.uid == "open" else None)
        seg = Segment(m.uid, t, sid, m.artist, m.title, cover, trans=vs.transitions.get(m.uid))
        if clip_active(m):
            sp = float(m.clip.get("speed", 1.0)) or 1.0
            seg.video, seg.vspeed, seg.vloop = m.clip["path"], sp, bool(m.clip.get("loop"))
            seg.vstart = (t - float(m.clip.get("start", t))) * sp      # where in the video this song begins
        elif isinstance(sid, str) and sid.startswith("@clip:"):
            seg.video, seg.vloop = sid[6:], True
        elif is_video and not (p.video.mode == "per_song" and m.shader):
            seg.video, seg.vstart = p.audio, t            # the file's own picture, in sync with its sound
        segs.append(seg)
    return segs, fade_windows(times, max(0.5, float(p.video.blend)))


def visual_labels(p: StudioProject, shaders: ShaderLibrary) -> dict[str, str]:
    """{marker uid: what the editor's list should say}: the source video, a clip, or "" (= the visual's name)."""
    segs, _ = build_segments(p, shaders, p.duration or 1e9)
    out = {}
    for sg in segs:
        m = p.find(sg.uid)
        if m is not None and clip_active(m) and sg.video == m.clip.get("path"):
            out[sg.uid] = "Video: " + Path(sg.video).name
        elif sg.video and sg.video == p.audio:
            out[sg.uid] = "Source video"
        elif sg.video:
            out[sg.uid] = "Clip: " + Path(sg.video).name
    return out


def resolved_visuals(p: StudioProject, shaders: ShaderLibrary, seconds: float | None = None) -> list[tuple[str, str]]:
    """[(marker uid, shader id)] as the video will use them (for the editor's lists)."""
    segs, _ = build_segments(p, shaders, seconds or p.duration or 1e9)
    return [(s.uid, s.shader) for s in segs]


def render_studio(p: StudioProject, out_path, shaders: ShaderLibrary | None = None,
                  progress=None, cancel=None) -> dict:
    """Render the project's video. The original audio file is the soundtrack."""
    shaders = shaders or ShaderLibrary()
    if not Path(p.audio).is_file():
        raise audio_io.AudioError(f"The audio file can't be found: {p.audio}")
    say = progress or (lambda m, f: None)
    long = (p.duration or probe_duration(p.audio)) > LONG_SECONDS
    sr = LONG_TEXTURE_SR if long else TEXTURE_SR
    say("reading the audio…", 0.0)
    mono = audio_io.decode(p.audio, sr=sr, channels=1)
    seconds = mono.shape[1] / sr
    p.duration = seconds
    with tempfile.TemporaryDirectory(prefix="lmm_studio_") as tmp:
        cover = Path(tmp) / "cover.jpg"
        file_cover = str(cover) if audio_io.extract_cover(p.audio, cover) else None
        segs, wins = build_segments(p, shaders, seconds, (mono[0], sr), file_cover)
        return render_segments(segs, wins, seconds, out_path, p.video, shaders, p.audio, mono, sr,
                               progress=lambda m, f: say(m, 0.05 + 0.95 * f), cancel=cancel)


class StudioHistory:
    """Undo / redo for a project (whole-project snapshots; a drag is one step)."""

    def __init__(self, project: StudioProject):
        self.project = project
        self._undo: list[str] = []
        self._redo: list[str] = []
        self._gesture = False

    def _snap(self) -> str:
        return json.dumps(self.project.to_dict())

    def _load(self, snap: str) -> None:
        self.project = StudioProject.from_dict(json.loads(snap))

    def edit(self, fn) -> None:
        """Run fn(project) as one undoable step."""
        snap = self._snap()
        try:
            fn(self.project)
        except Exception:
            self._load(snap)
            raise
        if not self._gesture:
            self._undo.append(snap)
            del self._undo[:-80]
        self._redo.clear()

    def begin_gesture(self) -> None:
        self._undo.append(self._snap())
        self._redo.clear()
        self._gesture = True

    def end_gesture(self) -> None:
        self._gesture = False
        if self._undo and self._undo[-1] == self._snap():
            self._undo.pop()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> None:
        if self._undo:
            self._redo.append(self._snap())
            self._load(self._undo.pop())

    def redo(self) -> None:
        if self._redo:
            self._undo.append(self._snap())
            self._load(self._redo.pop())

    def reset(self, project: StudioProject) -> None:
        self.project = project
        self._undo.clear()
        self._redo.clear()


def builtin_ids() -> list[str]:
    return list(BUILTIN)
