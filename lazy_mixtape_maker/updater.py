"""Update check and self-update from the GitHub releases of this project.

The check asks GitHub for the latest *published* release (drafts are never visible), compares it with the
version this build was made from, and for the packaged app can download the build for this system and swap
it in after the app has closed. Nothing here runs unless the user allows it (Help menu > Automatically check
for updates), and every network step is plain HTTPS to github.com."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from . import __version__, _buildinfo

REPO = "section9agent/Lazy-Mixtape-Maker"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
USER_AGENT = "LazyMixtapeMaker-updater"
ALLOWED_HOSTS = ("github.com", "api.github.com", "objects.githubusercontent.com", "githubusercontent.com")
CHECK_EVERY = 6 * 3600          # a start-up check is skipped when one was made less than this long ago


class UpdateError(RuntimeError):
    pass


@dataclass
class Update:
    tag: str
    name: str
    notes: str
    published: str
    page: str
    asset_name: str = ""
    asset_url: str = ""
    size: int = 0


# ------------------------------------------------------------------ versions
def current() -> tuple[str, str]:
    """(tag, build time) of the running app; ("dev", "") when run from source."""
    return _buildinfo.TAG, _buildinfo.BUILT


def parse_tag(tag: str):
    """("v", (1, 2, 3)) for v1.2.3, ("build", 41) for build-41, else None."""
    m = re.fullmatch(r"[vV]?(\d+)\.(\d+)(?:\.(\d+))?", tag.strip())
    if m:
        return "v", (int(m[1]), int(m[2]), int(m[3] or 0))
    m = re.fullmatch(r"build-(\d+)", tag.strip())
    if m:
        return "build", int(m[1])
    return None


def _when(text: str):
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def is_newer(tag: str, published: str, cur_tag: str | None = None, cur_built: str | None = None) -> bool:
    """Is the release `tag` (published at `published`) newer than the running build?"""
    if cur_tag is None:
        cur_tag, cur_built = current()
    if tag == cur_tag:
        return False
    a, b = parse_tag(tag), parse_tag(cur_tag)
    if a and b and a[0] == b[0]:
        return a[1] > b[1]
    if cur_tag == "dev":                                   # run from source: nothing to compare with
        return False
    pub, built = _when(published), _when(cur_built or "")
    if pub and built:
        return (pub - built).total_seconds() > 3600       # published clearly after this build was made
    return False


# --------------------------------------------------------------- the network
def _check_url(url: str):
    u = urlparse(url)
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS):
        raise UpdateError(f"Refusing to use {url}")


def _open(url: str, timeout: float = 15.0):
    _check_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout)


def platform_asset_name() -> str:
    if sys.platform == "win32":
        return "LazyMixtapeMaker-Windows.zip"
    if sys.platform == "darwin":
        return "LazyMixtapeMaker-macOS.zip"
    return "LazyMixtapeMaker-Linux.tar.gz"


def parse_release(data: dict) -> Update | None:
    if not isinstance(data, dict) or data.get("draft") or not data.get("tag_name"):
        return None
    want = platform_asset_name()
    asset = next((a for a in data.get("assets", []) if a.get("name") == want), None)
    return Update(tag=str(data["tag_name"]), name=str(data.get("name") or data["tag_name"]),
                  notes=str(data.get("body") or ""), published=str(data.get("published_at") or ""),
                  page=str(data.get("html_url") or RELEASES_PAGE),
                  asset_name=asset["name"] if asset else "", asset_url=asset.get("browser_download_url", "") if asset else "",
                  size=int(asset.get("size", 0)) if asset else 0)


def fetch_latest(opener=_open) -> Update | None:
    """The latest published release, or None when there is none (or it is a draft)."""
    try:
        with opener(API_LATEST) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001 - offline, rate limited, no release yet ...
        if getattr(e, "code", None) == 404:
            return None
        raise UpdateError(f"Couldn't reach GitHub: {e}") from None
    return parse_release(data)


def check(opener=_open) -> Update | None:
    """An Update when a newer release exists, else None."""
    up = fetch_latest(opener)
    if up and is_newer(up.tag, up.published):
        return up
    return None


# ------------------------------------------------------------------ the files
def download(up: Update, dest: Path, progress=None, cancel=None, opener=_open) -> Path:
    """Download the release archive for this system into `dest` (a folder). progress(done, total)."""
    if not up.asset_url:
        raise UpdateError(f"This release has no download for this computer ({platform_asset_name()}).")
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / up.asset_name
    done = 0
    with opener(up.asset_url, 60.0) as r, open(out, "wb") as f:
        total = int(r.headers.get("Content-Length") or up.size or 0)
        while True:
            if cancel and cancel():
                raise UpdateError("Cancelled")
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    if up.size and out.stat().st_size != up.size:
        raise UpdateError("The download is incomplete - please try again.")
    return out


def _safe_name(name: str) -> bool:
    p = Path(name)
    return not p.is_absolute() and ".." not in p.parts


def extract(archive: Path, into: Path) -> Path:
    """Unpack the archive and return the folder (or .app) holding the new version."""
    into.mkdir(parents=True, exist_ok=True)
    s = str(archive)
    if s.endswith(".zip"):
        if sys.platform == "darwin" and shutil.which("ditto"):      # keeps the executable bits of the .app
            subprocess.run(["ditto", "-x", "-k", s, str(into)], check=True)
        else:
            with zipfile.ZipFile(archive) as z:
                if not all(_safe_name(n) for n in z.namelist()):
                    raise UpdateError("The download has unsafe file names.")
                z.extractall(into)
    else:
        with tarfile.open(archive) as t:
            for m in t.getmembers():
                if not _safe_name(m.name) or m.isdev() or ((m.issym() or m.islnk()) and not _safe_name(m.linkname)):
                    raise UpdateError("The download has unsafe file names.")
            try:
                t.extractall(into, filter="data")
            except TypeError:                                   # older Python without extraction filters
                t.extractall(into)
    for cand in ("Lazy Mixtape Maker.app", "LazyMixtapeMaker"):
        if (into / cand).exists():
            return into / cand
    raise UpdateError("The download doesn't contain the app.")


def install_target() -> Path | None:
    """The installed copy that an update replaces, or None when run from source / not replaceable."""
    if not getattr(sys, "frozen", False):
        return None
    exe = Path(sys.executable).resolve()
    t = exe.parents[2] if sys.platform == "darwin" else exe.parent
    if sys.platform == "darwin" and t.suffix != ".app":
        return None
    return t if os.access(t.parent if sys.platform == "darwin" else t, os.W_OK) else None


def helper_script(new_root: Path, target: Path, pid: int, work: Path) -> tuple[Path, list[str]]:
    """Write the little script that waits for the app to close, swaps the files and starts the new version."""
    work.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        s = work / "update.bat"
        exe = target / "LazyMixtapeMaker.exe"
        s.write_text(
            "@echo off\r\n"
            f":wait\r\ntasklist /FI \"PID eq {pid}\" 2>NUL | find \"{pid}\" >NUL\r\n"
            "if not errorlevel 1 (ping -n 2 127.0.0.1 >NUL & goto wait)\r\n"
            f"robocopy \"{new_root}\" \"{target}\" /E /R:10 /W:2 /NFL /NDL /NJH /NJS >NUL\r\n"
            f"start \"\" \"{exe}\"\r\n", encoding="utf-8")
        return s, ["cmd", "/c", str(s)]
    s = work / "update.sh"
    if sys.platform == "darwin":
        body = (f'n=0; while kill -0 {pid} 2>/dev/null && [ $n -lt 1200 ]; do sleep 0.5; n=$((n+1)); done\n'
                f'old="{target}.old"\nrm -rf "$old"\n'
                f'mv "{target}" "$old" && cp -R "{new_root}" "{target}" && xattr -dr com.apple.quarantine "{target}" 2>/dev/null\n'
                f'if [ -d "{target}" ]; then rm -rf "$old"; else mv "$old" "{target}"; fi\n'
                f'open "{target}"\n')
    else:
        body = (f'n=0; while kill -0 {pid} 2>/dev/null && [ $n -lt 1200 ]; do sleep 0.5; n=$((n+1)); done\n'
                f'cp -a "{new_root}/." "{target}/"\n'
                f'chmod +x "{target}/LazyMixtapeMaker"\n'
                f'nohup "{target}/LazyMixtapeMaker" >/dev/null 2>&1 &\n')
    s.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    s.chmod(0o755)
    return s, ["/bin/sh", str(s)]


def launch_helper(cmd: list[str]) -> None:
    kw: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True}
    if sys.platform == "win32":
        kw["creationflags"] = 0x00000008 | 0x00000200       # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    subprocess.Popen(cmd, **kw)


# ------------------------------------------------------------------ settings
def enabled() -> bool:
    from . import prefs
    return bool(prefs.get("auto_update"))


def set_enabled(on: bool) -> None:
    from . import prefs
    prefs.set("auto_update", bool(on))


def due() -> bool:
    """Is an automatic start-up check allowed now (switched on, and not checked a moment ago)?"""
    from . import prefs
    if not enabled() or current()[0] == "dev":              # never on its own when run from source
        return False
    return time.time() - float(prefs.get("last_update_check") or 0) > CHECK_EVERY


def mark_checked() -> None:
    from . import prefs
    prefs.set("last_update_check", time.time())


def skipped(tag: str) -> bool:
    from . import prefs
    return prefs.get("skip_version") == tag


def skip(tag: str) -> None:
    from . import prefs
    prefs.set("skip_version", tag)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = ["Update", "UpdateError", "check", "fetch_latest", "is_newer", "parse_tag", "download", "extract", "install_target",
           "helper_script", "launch_helper", "enabled", "set_enabled", "due", "mark_checked", "skipped", "skip", "RELEASES_PAGE",
           "__version__"]
