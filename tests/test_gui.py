"""Smoke tests of the windows (offscreen)."""
import os
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LMM_AUDIO_BACKEND", "null")
sys.path.insert(0, str(Path(__file__).parent))
import synth  # noqa: E402

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _need_gl():
    from lazy_mixtape_maker.visuals import make_context
    try:
        make_context().release()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"no OpenGL available: {e}")


def spin(app, n=20, d=0.05):
    for _ in range(n):
        app.processEvents()
        time.sleep(d)


def test_studio_window_edit_flow(app, tmp_path, monkeypatch):
    monkeypatch.setenv("LMM_DATA_DIR", str(tmp_path / "data"))
    from lazy_mixtape_maker import studio
    from lazy_mixtape_maker.gui.studio_window import StudioWindow
    synth.make_song(tmp_path / "m.wav", 120, 9, True, structure=[("verse", 4), ("chorus", 4)], tags={"title": "T", "artist": "A"})
    w = StudioWindow()
    w.show()
    w.open_audio(tmp_path / "m.wav")
    for _ in range(100):
        spin(app, 1, 0.1)
        if w.task is None and w._has_audio():
            break
    assert w._has_audio() and len(w.project.markers) == 1
    w.add_marker(6.0)
    w.add_marker(10.0)
    assert [round(m.time) for m in w.project.markers] == [0, 6, 10]
    uid = w.project.markers[1].uid
    w.select(uid)
    w.f_title.setText("Renamed"); w.f_title.editingFinished.emit()
    assert w.project.find(uid).title == "Renamed"
    w._history(False)
    assert w.project.find(uid).title != "Renamed"
    w._edit(lambda p: p.set_markers(studio.parse_tracklist("0:00 A - One\n0:08 B - Two")))
    w.refresh(True)
    assert w.table.rowCount() == 2
    w.group.buttons()[0].setChecked(True)
    w.radios["random"].setChecked(True)
    assert w.project.video.mode == "random"
    w.overlay.setChecked(False)
    assert w.project.video.show_overlay is False
    f = tmp_path / "p.lmv"
    w.file = f
    assert w.save_project()
    w.dirty = False
    spin(app, 10)
    w.close()


def test_shader_manager(app, tmp_path, monkeypatch):
    monkeypatch.setenv("LMM_DATA_DIR", str(tmp_path / "data"))
    _need_gl()
    from lazy_mixtape_maker.gui.panels import ThumbCache
    from lazy_mixtape_maker.gui.shader_manager import ShaderManager
    from lazy_mixtape_maker.visuals import ShaderLibrary
    lib = ShaderLibrary()
    sh = lib.add_from_text("void mainImage(out vec4 c, in vec2 p){ c = vec4(p/iResolution.xy, 0.3, 1.0); }", "Mine")
    thumbs = ThumbCache()
    m = ShaderManager(lib, thumbs)
    m.show()
    spin(app, 5)
    assert m.list.count() == len(lib.all())
    for r in range(m.list.count()):
        if m.list.item(r).data(0x100) == sh.id:
            m.list.setCurrentRow(r)
    assert m.current().id == sh.id and m.name.isEnabled()
    m.name.setText("Renamed"); m.name.editingFinished.emit()
    assert lib.get(sh.id).name == "Renamed"
    m.energy.setCurrentIndex(m.energy.findData("high")); m.energy.activated.emit(m.energy.currentIndex())
    assert lib.get(sh.id).energy == "high"
    for _ in range(60):                       # a live frame arrives
        spin(app, 1, 0.1)
        if m.screen.pixmap() is not None and not m.screen.pixmap().isNull():
            break
    else:
        if m.worker is not None and "OpenGL" in m.screen.text():
            pytest.skip("no OpenGL")
        pytest.fail("no live preview frame")
    builtin = next(s for s in lib.all() if s.builtin)
    for r in range(m.list.count()):
        if m.list.item(r).data(0x100) == builtin.id:
            m.list.setCurrentRow(r)
    assert not m.b_remove.isEnabled()          # built-ins can't be removed
    m.shutdown(); thumbs.shutdown()
