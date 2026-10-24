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


def test_drag_a_tracks_start_edge(app, tmp_path, monkeypatch):
    monkeypatch.setenv("LMM_DATA_DIR", str(tmp_path / "data"))
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent
    from lazy_mixtape_maker import audio_io
    from lazy_mixtape_maker.engine import new_session
    from lazy_mixtape_maker.gui.main_window import MainWindow
    from lazy_mixtape_maker.plan import MixSettings
    from lazy_mixtape_maker.session import save_session
    d = tmp_path / "s"
    d.mkdir()
    for n, bpm, root in (("a", 120, 9), ("b", 122, 0)):
        synth.make_song(d / f"B - {n}.wav", bpm, root, True, structure=[("intro", 8), ("verse", 8), ("chorus", 8)],
                        tags={"title": n, "artist": "B"})
    s, _ = new_session(audio_io.list_audio_files([d]), MixSettings(seed=1, overlap_bars=8), name="x")
    save_session(s, tmp_path / "m.lmm")
    w = MainWindow()
    w.show()
    w.load_session(tmp_path / "m.lmm")
    spin(app, 3, 0.05)
    tl = w.timeline
    tl.set_zoom(20.0)
    st = w.state
    t1 = st.plan.tracks[1]
    start0, beats0 = t1.src_start, st.plan.transitions[0].overlap_beats
    assert beats0 >= 8
    _slots, rects = tl._rects()
    r = rects[1]
    y = r.center().y()

    def ev(kind, x):
        pt = QPointF(x, y)
        btn = Qt.MouseButton.LeftButton
        return QMouseEvent(kind, pt, tl.mapToGlobal(pt), btn, btn if kind != QEvent.Type.MouseButtonRelease else Qt.MouseButton.NoButton,
                           Qt.KeyboardModifier.NoModifier)

    tl.mousePressEvent(ev(QEvent.Type.MouseButtonPress, r.left() + 3))
    assert tl._drag and tl._drag["kind"] == "edge_l"
    beat = 60.0 / st.plan.transitions[0].tempo
    tl.mouseMoveEvent(ev(QEvent.Type.MouseMove, r.left() + 3 + 4 * beat * 20.0))     # 4 beats to the right
    tl.mouseReleaseEvent(ev(QEvent.Type.MouseButtonRelease, r.left() + 3 + 4 * beat * 20.0))
    t1 = st.plan.tracks[1]
    assert t1.src_start > start0 + 1.0                       # the song now starts later
    assert st.plan.transitions[0].overlap_beats == beats0 - 4   # and the blend got that much shorter
    assert not t1.auto_bounds
    st.undo()
    assert st.plan.tracks[1].src_start == pytest.approx(start0)
    w.state.dirty = False
    w.close()
