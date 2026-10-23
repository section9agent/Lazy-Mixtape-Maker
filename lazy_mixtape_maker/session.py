"""Session files (.lmm): the library analysis + the full mix plan in one JSON
file. Songs are referenced by content fingerprint plus a relative path, so a
friend can load the session, point the app at their own copy of the songs
folder, and get the exact same mix (or tweak it)."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__, audio_io
from .analysis import SongAnalysis
from .plan import MixPlan

FORMAT = "lazy-mixtape-maker-session"
VERSION = 1


@dataclass
class Session:
    library: dict[str, SongAnalysis] = field(default_factory=dict)
    plan: MixPlan = field(default_factory=MixPlan)
    paths: dict[str, str] = field(default_factory=dict)      # song id -> local path (not shared)
    export: dict = field(default_factory=dict)               # last export settings (format etc.)
    extra: dict = field(default_factory=dict)                # room for video / visuals settings later
    name: str = "Untitled mixtape"

    def missing(self) -> list[SongAnalysis]:
        used = {t.song_id for t in self.plan.tracks}
        return [self.library[i] for i in used if i not in self.paths]


def _rel(path: str, base: Path) -> str:
    try:
        return Path(os.path.relpath(path, base)).as_posix()
    except ValueError:  # different drive on Windows
        return Path(path).as_posix()


def save_session(session: Session, file) -> None:
    file = Path(file)
    base = file.resolve().parent
    songs = []
    for sid, an in session.library.items():
        d = an.to_dict()
        d.pop("path", None)
        p = session.paths.get(sid)
        d["filename"] = Path(p).name if p else d.get("filename", "")
        d["relpath"] = _rel(p, base) if p else ""
        d["size"] = Path(p).stat().st_size if p and Path(p).exists() else 0
        songs.append(d)
    doc = {
        "format": FORMAT, "version": VERSION, "app_version": __version__,
        "saved": time.strftime("%Y-%m-%dT%H:%M:%S"), "name": session.name,
        "songs": songs, "plan": session.plan.to_dict(), "export": session.export, "extra": session.extra,
    }
    tmp = file.with_suffix(file.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    tmp.replace(file)


def load_session(file, search_dirs=()) -> Session:
    file = Path(file)
    doc = json.loads(file.read_text(encoding="utf-8"))
    if doc.get("format") != FORMAT:
        raise ValueError(f"{file.name} is not a Lazy Mixtape Maker session")
    if doc.get("version", 0) > VERSION:
        raise ValueError("This session was saved by a newer version of Lazy Mixtape Maker")
    base = file.resolve().parent
    s = Session(name=doc.get("name", file.stem), export=doc.get("export", {}), extra=doc.get("extra", {}))
    hints: dict[str, dict] = {}
    for d in doc["songs"]:
        hint = {"filename": d.pop("filename", ""), "relpath": d.pop("relpath", ""), "size": d.pop("size", 0)}
        d["path"] = ""
        an = SongAnalysis.from_dict(d)
        s.library[an.id] = an
        hints[an.id] = hint
    s.plan = MixPlan.from_dict(doc["plan"])
    relink(s, hints, [base, *map(Path, search_dirs)])
    return s


def relink(session: Session, hints: dict[str, dict] | None = None, search_dirs=()) -> list[str]:
    """Find local copies of the session's songs. Returns ids still missing."""
    need = {t.song_id for t in session.plan.tracks} | set(session.library)
    need = {i for i in need if i not in session.paths or not Path(session.paths[i]).exists()}
    hints = hints or {}
    # 1) the recorded relative path
    base = Path(search_dirs[0]) if search_dirs else Path(".")
    for sid in list(need):
        rel = hints.get(sid, {}).get("relpath")
        if rel:
            cand = (base / rel)
            if cand.is_file() and audio_io.file_id(cand) == sid:
                session.paths[sid] = str(cand.resolve())
                session.library[sid].path = session.paths[sid]
                need.discard(sid)
    if not need:
        return []
    # 2) look through the folders: same size first (cheap), then confirm by fingerprint
    files = audio_io.list_audio_files([d for d in search_dirs if Path(d).exists()])
    by_size: dict[int, list[Path]] = {}
    for f in files:
        by_size.setdefault(f.stat().st_size, []).append(f)
    for sid in list(need):
        size = hints.get(sid, {}).get("size", 0)
        cands = by_size.get(size, []) if size else files
        name = hints.get(sid, {}).get("filename", "")
        cands = sorted(cands, key=lambda f: f.name != name)
        for f in cands:
            if audio_io.file_id(f) == sid:
                session.paths[sid] = str(f.resolve())
                session.library[sid].path = session.paths[sid]
                need.discard(sid)
                break
    return sorted(need)
