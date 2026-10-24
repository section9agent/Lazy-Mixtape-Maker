"""App-wide preferences kept in a small JSON file next to the saved visuals."""
from __future__ import annotations

import json

from .visuals import data_dir

_DEFAULTS = {"show_overlay": True}     # cover art + artist + title on every video, until switched off


def _file():
    return data_dir() / "preferences.json"


def load() -> dict:
    try:
        d = json.loads(_file().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def get(key: str):
    return load().get(key, _DEFAULTS.get(key))


def set(key: str, value) -> None:  # noqa: A001
    d = load()
    d[key] = value
    f = _file()
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(d, indent=1), encoding="utf-8")
    except OSError:
        pass


def overlay_enabled() -> bool:
    """The master switch: when off, no video shows the cover / artist / title card."""
    return bool(get("show_overlay"))
