"""About window and the update system (no real network: GitHub is faked)."""
import io
import json
import os
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LMM_AUDIO_BACKEND", "null")

from lazy_mixtape_maker import updater  # noqa: E402


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("LMM_DATA_DIR", str(tmp_path / "data"))
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def release(tag="build-50", published="2026-11-10T10:00:00Z", draft=False, assets=None):
    names = assets if assets is not None else ["LazyMixtapeMaker-Windows.zip", "LazyMixtapeMaker-macOS.zip", "LazyMixtapeMaker-Linux.tar.gz"]
    return {"tag_name": tag, "name": f"Lazy Mixtape Maker {tag}", "body": "notes", "published_at": published, "draft": draft,
            "html_url": "https://github.com/x/y/releases/tag/" + tag,
            "assets": [{"name": n, "size": 3, "browser_download_url": "https://github.com/x/y/releases/download/%s/%s" % (tag, n)} for n in names]}


class Resp(io.BytesIO):
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def test_version_comparison():
    n = updater.is_newer
    assert n("build-41", "", "build-40", "") and not n("build-40", "", "build-40", "") and not n("build-39", "", "build-40", "")
    assert n("v1.2.0", "", "v1.1.9", "") and not n("v1.0.0", "", "v1.1.0", "")
    assert n("v1.0.0", "2026-11-10T10:00:00Z", "build-40", "2026-11-01T10:00:00Z")      # mixed: by date
    assert not n("v1.0.0", "2026-11-01T10:00:30Z", "build-40", "2026-11-01T10:00:00Z")   # its own release, minutes later
    assert not n("build-99", "2026-11-10T10:00:00Z", "dev", "")                          # source runs don't nag


def test_release_parsing_and_check(monkeypatch):
    up = updater.parse_release(release())
    assert up.tag == "build-50" and up.asset_name == updater.platform_asset_name() and up.asset_url.startswith("https://")
    assert updater.parse_release(release(draft=True)) is None
    assert updater.parse_release(release(assets=[])).asset_url == ""
    monkeypatch.setattr(updater, "current", lambda: ("build-40", "2026-11-01T10:00:00Z"))
    assert updater.check(lambda url: Resp(json.dumps(release("build-50")).encode())).tag == "build-50"
    assert updater.check(lambda url: Resp(json.dumps(release("build-40")).encode())) is None

    def offline(url):
        raise OSError("no network")
    with pytest.raises(updater.UpdateError):
        updater.check(offline)


def test_only_github_https_is_used():
    for bad in ("http://github.com/x", "https://evil.example.com/x", "https://github.com.evil.com/x"):
        with pytest.raises(updater.UpdateError):
            updater._check_url(bad)
    updater._check_url("https://github.com/x/y")
    updater._check_url("https://objects.githubusercontent.com/z")


def test_download_extract_and_helper(tmp_path, monkeypatch):
    # a fake release archive for this system
    if sys.platform == "win32" or sys.platform == "darwin":
        arc_bytes = io.BytesIO()
        with zipfile.ZipFile(arc_bytes, "w") as z:
            z.writestr("Lazy Mixtape Maker.app/Contents/x" if sys.platform == "darwin" else "LazyMixtapeMaker/LazyMixtapeMaker.exe", "new")
    else:
        arc_bytes = io.BytesIO()
        with tarfile.open(fileobj=arc_bytes, mode="w:gz") as t:
            data = b"#!/bin/sh\n"
            ti = tarfile.TarInfo("LazyMixtapeMaker/LazyMixtapeMaker"); ti.size = len(data); ti.mode = 0o755
            t.addfile(ti, io.BytesIO(data))
    payload = arc_bytes.getvalue()
    up = updater.parse_release(release())
    up.size = len(payload)
    seen = []

    def opener(url, timeout=0):
        return Resp(payload)
    f = updater.download(up, tmp_path / "dl", lambda d, t: seen.append(d), opener=opener)
    assert f.read_bytes() == payload and seen[-1] == len(payload)
    root = updater.extract(f, tmp_path / "ex")
    assert root.exists()
    script, cmd = updater.helper_script(root, tmp_path / "installed", 4242, tmp_path / "w")
    text = script.read_text()
    assert "4242" in text and str(tmp_path / "installed") in text
    up.size = len(payload) + 5
    with pytest.raises(updater.UpdateError):
        updater.download(up, tmp_path / "dl2", opener=opener)


def test_unsafe_archives_are_refused(tmp_path):
    z = tmp_path / "bad.zip"
    with zipfile.ZipFile(z, "w") as zz:
        zz.writestr("../evil.txt", "x")
    with pytest.raises(updater.UpdateError):
        updater.extract(z, tmp_path / "o")
    t = tmp_path / "bad.tar.gz"
    with tarfile.open(t, "w:gz") as tt:
        ti = tarfile.TarInfo("../evil"); ti.size = 1
        tt.addfile(ti, io.BytesIO(b"x"))
    with pytest.raises(updater.UpdateError):
        updater.extract(t, tmp_path / "o2")


def test_off_switch(app, monkeypatch):
    monkeypatch.setattr(updater, "current", lambda: ("build-40", ""))
    assert updater.enabled() and updater.due()
    updater.set_enabled(False)
    assert not updater.enabled() and not updater.due()
    updater.set_enabled(True)
    updater.mark_checked()
    assert not updater.due()                      # just checked
    updater.skip("build-50")
    assert updater.skipped("build-50") and not updater.skipped("build-51")


def test_about_window_and_menu(app, tmp_path, monkeypatch):
    from lazy_mixtape_maker.gui import about
    from lazy_mixtape_maker.gui.main_window import MainWindow
    d = about.AboutDialog(None, None, lambda: None)
    html = d.credits.toPlainText()
    for name in ("librosa", "Qt / PySide6", "ModernGL", "FFmpeg", "Shadertoy", "Mutagen"):
        assert name in html
    assert "Claude" in about.AUTHORS and "Emmanuel Hoachlander" in about.AUTHORS
    assert "section9agent%40hotmail.com" in about.DONATE_URL and about.DONATE_URL.startswith("https://www.paypal.com/donate")
    assert d.auto.isChecked()
    d.auto.setChecked(False)
    assert not updater.enabled()
    w = MainWindow()
    titles = [a.text() for a in w.menuBar().actions()]
    assert "&Help" in titles
    help_menu = next(a for a in w.menuBar().actions() if a.text() == "&Help").menu()
    assert [a.text() for a in help_menu.actions() if a.text()] == ["Check for updates…", "Check for updates automatically", "About Lazy Mixtape Maker…"]
    assert not w.a_auto_update.isChecked()       # follows the saved choice
    w.a_auto_update.trigger()                     # ticking it in the menu saves the choice
    assert updater.enabled()
    w.a_auto_update.trigger()
    assert not updater.enabled()
    w.state.dirty = False
    w.close()
