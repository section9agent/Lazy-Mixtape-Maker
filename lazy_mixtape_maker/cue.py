"""Cue sheet / tracklist for a rendered mix."""
from __future__ import annotations

from pathlib import Path

from .analysis import SongAnalysis
from .audio_io import SR
from .plan import MixPlan, timeline

_FILE_TYPES = {".wav": "WAVE", ".mp3": "MP3", ".flac": "FLAC"}


def _cue_time(seconds: float) -> str:
    frames = int(round(seconds * 75))
    return f"{frames // (75 * 60):02d}:{(frames // 75) % 60:02d}:{frames % 75:02d}"


def _clock(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{(s // 60) % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def tracklist(plan: MixPlan, lib: dict[str, SongAnalysis], sr: int = SR) -> list[dict]:
    """One entry per song with the time the 'track break' is marked at."""
    slots = timeline(plan, sr)
    rows = []
    for i, (t, sl) in enumerate(zip(plan.tracks, slots)):
        an = lib[t.song_id]
        start, end = sl.start / sr, sl.end / sr
        cue = start
        if i > 0:
            ov = sl.overlap_in / sr
            mode = plan.settings.cue_point
            cue = start + (ov / 2 if mode == "middle" else ov if mode == "end" else 0.0)
        rows.append({
            "index": i + 1, "title": an.title, "artist": an.artist, "cue": cue,
            "start": start, "end": end,
            "bpm": round(t.bpm or plan.master_bpm, 1),
            "key": an.camelot, "transition_in": slots[i].trans_in.type if slots[i].trans_in else "",
            "overlap_in": slots[i].overlap_in / sr,
        })
    return rows


def write_cue(path, plan: MixPlan, lib: dict[str, SongAnalysis], audio_file: str,
              title: str = "Lazy Mixtape", sr: int = SR) -> None:
    rows = tracklist(plan, lib, sr)
    ftype = _FILE_TYPES.get(Path(audio_file).suffix.lower(), "WAVE")
    esc = lambda s: s.replace('"', "'")
    lines = [f'REM GENERATOR "Lazy Mixtape Maker"', f'TITLE "{esc(title)}"', 'PERFORMER "Various Artists"',
             f'FILE "{esc(Path(audio_file).name)}" {ftype}']
    for r in rows:
        lines += [f"  TRACK {r['index']:02d} AUDIO", f'    TITLE "{esc(r["title"])}"']
        if r["artist"]:
            lines.append(f'    PERFORMER "{esc(r["artist"])}"')
        lines.append(f"    INDEX 01 {_cue_time(r['cue'])}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_tracklist_txt(path, plan: MixPlan, lib: dict[str, SongAnalysis], sr: int = SR) -> None:
    rows = tracklist(plan, lib, sr)
    out = []
    for r in rows:
        who = f"{r['artist']} - " if r["artist"] else ""
        out.append(f"{_clock(r['cue']):>8}  {who}{r['title']}   [{r['key']} / {r['bpm']:g} BPM]")
    Path(path).write_text("\n".join(out) + "\n", encoding="utf-8")
