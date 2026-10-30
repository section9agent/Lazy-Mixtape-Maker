"""Playlists (.m3u, .m3u8, .pls, .xspf): the songs in the order the playlist lists them.

A mix made from a playlist keeps that order - the app never reorders it."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlparse

from .audio_io import AUDIO_EXTS, list_audio_files

PLAYLIST_EXTS = {".m3u", ".m3u8", ".pls", ".xspf"}


def is_playlist(path) -> bool:
    return Path(path).suffix.lower() in PLAYLIST_EXTS


def _text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _location(entry: str, base: Path) -> Path | None:
    entry = entry.strip().strip('"')
    if not entry:
        return None
    if re.match(r"^file:", entry, re.I):
        u = urlparse(entry)
        p = unquote(u.path)
        if re.match(r"^/[A-Za-z]:", p):          # file:///C:/music/a.mp3
            p = p[1:]
        if u.netloc and u.netloc.lower() != "localhost":
            p = "//" + u.netloc + p
        entry = p
    elif re.match(r"^[a-z][a-z0-9+.-]+://", entry, re.I):
        return None                               # a web stream, not a file on this computer
    p = Path(entry.replace("\\", "/")) if "\\" in entry and "/" not in entry.replace("\\", "") else Path(entry)
    if not p.is_absolute() and not re.match(r"^[A-Za-z]:", entry):
        p = base / p
    return p


def read_playlist(path) -> list[Path]:
    """The files a playlist points to, in playlist order (missing and non-audio entries included as written)."""
    path = Path(path)
    base = path.parent
    ext = path.suffix.lower()
    entries: list[str] = []
    if ext == ".xspf":
        root = ET.fromstring(path.read_bytes())
        entries = [el.text or "" for el in root.iter() if el.tag.split("}")[-1] == "location"]
    elif ext == ".pls":
        pairs = []
        for line in _text(path).splitlines():
            m = re.match(r"^\s*File(\d+)\s*=\s*(.*)$", line, re.I)
            if m:
                pairs.append((int(m.group(1)), m.group(2)))
        entries = [v for _, v in sorted(pairs)]
    else:
        entries = [ln for ln in _text(path).splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    out = []
    for e in entries:
        p = _location(e, base)
        if p is not None:
            out.append(p)
    return out


def expand_inputs(inputs) -> tuple[list[Path], bool, list[str]]:
    """Files and folders and playlists -> (songs, from_a_playlist, entries that couldn't be found).

    Folders give their songs sorted by name; a playlist gives its songs in its own order. The first time a
    file is listed wins. When any playlist is involved the caller must keep the order."""
    out: list[Path] = []
    missing: list[str] = []
    playlist = False
    for item in inputs:
        p = Path(item)
        if p.is_file() and is_playlist(p):
            playlist = True
            for f in read_playlist(p):
                if f.is_file() and f.suffix.lower() in AUDIO_EXTS:
                    out.append(f)
                elif f.is_dir():
                    out.extend(list_audio_files([f]))
                else:
                    missing.append(str(f))
        else:
            out.extend(list_audio_files([p]))
    seen, uniq = set(), []
    for f in out:
        r = f.resolve()
        if r not in seen:
            seen.add(r)
            uniq.append(f)
    return uniq, playlist, missing
