"""Per-song information you can change: artist, title and cover art.

Everything starts out as what the audio file's own tags say. Edits are kept in the session: artist and title
replace the ones in the song's entry, and a chosen cover picture is stored inside the session file (small
jpg), so a session shared with a friend keeps its covers. "" means "no cover at all"; no entry means "use the
cover that is inside the audio file"."""
from __future__ import annotations

import base64
import hashlib
import io
from pathlib import Path

from . import audio_io

COVER_MAX = 600


def file_info(path) -> dict:
    """What the audio file itself says: {"artist", "title"} (the title falls back to the file name)."""
    t = audio_io.read_tags(path)
    return {"artist": t["artist"], "title": t["title"]}


def file_cover(path, out_path) -> str | None:
    try:
        return str(out_path) if audio_io.extract_cover(path, out_path) else None
    except Exception:  # noqa: BLE001
        return None


def _info(extra: dict) -> dict:
    return extra.setdefault("song_info", {})


def _covers(extra: dict) -> dict:
    return extra.setdefault("covers", {})


def import_cover(extra: dict, image_path) -> str:
    """Store a picture (shrunk, as jpg) and return its key."""
    from PIL import Image

    im = Image.open(image_path).convert("RGB")
    im.thumbnail((COVER_MAX, COVER_MAX))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    raw = buf.getvalue()
    key = hashlib.sha1(raw).hexdigest()[:16]
    _covers(extra)[key] = base64.b64encode(raw).decode("ascii")
    return key


def set_cover(extra: dict, sid: str, cover: str | None) -> None:
    """cover: a picture file, "" (no cover), or None (back to the cover inside the audio file)."""
    if cover is None:
        _info(extra).pop(sid, None)
    elif cover == "":
        _info(extra)[sid] = {"cover": ""}
    else:
        _info(extra)[sid] = {"cover": import_cover(extra, cover)}


def prune(extra: dict) -> None:
    used = {v.get("cover") for v in _info(extra).values()}
    for k in [k for k in _covers(extra) if k not in used]:
        del _covers(extra)[k]


def custom_cover_state(extra: dict, sid: str):
    """None (file's own), "" (none) or the key of a stored picture."""
    d = _info(extra).get(sid)
    return None if d is None else d.get("cover", None)


def cover_file(extra: dict, key: str, tmp_dir) -> str | None:
    b = _covers(extra).get(key)
    if not b:
        return None
    p = Path(tmp_dir) / f"songcover_{key}.jpg"
    if not p.exists():
        p.write_bytes(base64.b64decode(b))
    return str(p)


def overrides(extra: dict, tmp_dir) -> dict:
    """{song id: picture path, or None for "no cover"} for every song whose cover was changed."""
    out = {}
    for sid in list(_info(extra)):
        k = custom_cover_state(extra, sid)
        if k == "":
            out[sid] = None
        elif k:
            p = cover_file(extra, k, tmp_dir)
            if p:
                out[sid] = p
    return out


def current_cover(extra: dict, sid: str, audio_path, tmp_dir) -> str | None:
    """The cover that is in use for a song right now, as a picture file (or None)."""
    k = custom_cover_state(extra, sid)
    if k == "":
        return None
    if k:
        return cover_file(extra, k, tmp_dir)
    if audio_path and Path(audio_path).exists():
        return file_cover(audio_path, Path(tmp_dir) / f"filecover_{sid[:12]}.jpg")
    return None


def snapshot(extra: dict) -> dict:
    return {sid: dict(v) for sid, v in _info(extra).items()}


def restore(extra: dict, snap: dict, covers_keep: dict | None = None) -> None:
    extra["song_info"] = {sid: dict(v) for sid, v in snap.items()}
