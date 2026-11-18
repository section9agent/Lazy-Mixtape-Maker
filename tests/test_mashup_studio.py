"""The Mashup Studio window, driven like a person would: pick songs, mash up, drag, trim, undo, play, export."""
import os
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LMM_AUDIO_BACKEND", "null")
sys.path.insert(0, str(Path(__file__).parent))
from test_mashup import songs  # noqa: E402,F401  (fixture)

from lazy_mixtape_maker import mashup as mm  # noqa: E402


@pytest.fixture()
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def wait(w, secs=120):
    from PySide6.QtWidgets import QApplication
    end = time.time() + secs
    while w.task is not None and time.time() < end:
        QApplication.processEvents()
        time.sleep(0.01)
    assert w.task is None


def test_studio(app, songs, tmp_path, monkeypatch):  # noqa: F811
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    from lazy_mixtape_maker.gui.mashup_studio import MashupStudio
    m0, lib, paths = songs
    ids = [s.song_id for s in m0.songs]
    said = []
    for k in ("information", "warning"):
        monkeypatch.setattr(QMessageBox, k, lambda *a, **kw: said.append(a[2]))
    w = MashupStudio(lib, paths, songs=ids)
    w.show()
    assert [cb.currentData() for cb in w.song_combo] == ids and not w.dirty
    assert "Both songs are split" in w.stems_label.text() and w.ai_btn.isEnabled()
    assert "BPM" in w.song_info[1].text() and "→" in w.song_info[1].text()     # song B plays at song A's tempo

    w.style.setCurrentIndex(w.style.findData("b_over_a"))
    w.ai_btn.click()
    assert len(w.m.clips) == 4 and w.dirty
    voc = next(c for c in w.m.clips if c.stem == "vocals")
    bar = mm.bar_seconds(w.m, lib)
    tl = w.timeline
    w.timeline.grab()                                                         # paints without trouble

    # drag the vocals one bar to the right (snapped to bars)
    r = tl.clip_rect(voc)
    start = voc.start
    p0 = QPoint(int(r.center().x()), int(r.center().y()))
    QTest.mousePress(tl, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p0)
    QTest.mouseMove(tl, p0 + QPoint(int(bar * tl.pps * 1.2), 0))
    QTest.mouseRelease(tl, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p0 + QPoint(int(bar * tl.pps * 1.2), 0))
    voc = w.m.clip(voc.id)
    assert voc.start == pytest.approx(start + bar)
    w.undo()
    assert w.m.clip(voc.id).start == pytest.approx(start)
    w.redo()
    voc = w.m.clip(voc.id)
    assert voc.start == pytest.approx(start + bar)

    # trim its right edge back by two bars
    L = mm.clip_length(w.m, lib, voc)
    r = tl.clip_rect(voc)
    pe = QPoint(int(r.right()) - 2, int(r.center().y()))
    QTest.mousePress(tl, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pe)
    QTest.mouseMove(tl, pe - QPoint(int(2 * bar * tl.pps), 0))
    QTest.mouseRelease(tl, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pe - QPoint(int(2 * bar * tl.pps), 0))
    voc = w.m.clip(voc.id)
    assert mm.clip_length(w.m, lib, voc) == pytest.approx(L - 2 * bar, abs=1e-6)

    # change it in the inspector
    tl.sel = voc.id
    w._fill_inspector()
    w.c_gain.setValue(-6.0)
    w.c_gain.editingFinished.emit()
    assert w.m.clip(voc.id).gain_db == pytest.approx(-6.0)
    w.c_fin.setValue(2.0)
    w.c_fin.editingFinished.emit()
    assert w.m.clip(voc.id).fade_in == pytest.approx(2 * bar / 4)

    # double-click an empty spot of song A's vocals lane to add a clip; Delete removes it
    n = len(w.m.clips)
    end_x = int(tl.x_of(mm.length(w.m, lib) + 4 * bar))
    QTest.mouseDClick(tl, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(end_x, 26 + 10))
    assert len(w.m.clips) == n + 1
    new = w.m.clips[-1]
    assert (new.song, new.stem) == (0, "vocals") and tl.sel == new.id
    assert (new.start / bar) == pytest.approx(round(new.start / bar))
    tl.setFocus()
    QTest.keyClick(tl, Qt.Key.Key_Delete)
    assert len(w.m.clips) == n

    # split at the playhead, then duplicate
    tl.sel = voc.id
    w.seek(voc.start + 2 * bar)
    w.split_clip()
    assert len(w.m.clips) == n + 1
    w.undo()
    assert len(w.m.clips) == n

    # play: renders, then the (silent test) player runs
    w.seek(0.0)
    w.toggle_play()
    wait(w)
    assert w._render_path and Path(w._render_path).exists() and w.player.loaded and not said, said
    w.stop()

    # export, save and open again
    out = tmp_path / "mash.wav"
    w._export_to(out)
    wait(w)
    import soundfile as sf
    assert sf.info(str(out)).duration == pytest.approx(mm.length(w.m, lib), abs=0.05)
    f = tmp_path / "m.lmmash"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(f), ""))
    assert w.save() and not w.dirty and f.exists()
    before = w.m.to_dict()
    w.new_mashup()
    assert not w.m.clips
    w.open_mashup(str(f))
    assert w.m.to_dict() == before and w.file == f

    # changing song A removes its clips (Undo brings them back)
    a_clips = [c.id for c in w.m.clips if c.song == 0]
    w.song_combo[0].setCurrentIndex(0)
    assert not w.m.songs[0].song_id and not [c for c in w.m.clips if c.song == 0] and not w.ai_btn.isEnabled()
    w.undo()
    assert sorted(c.id for c in w.m.clips if c.song == 0) == sorted(a_clips)

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Discard)
    w.close()


def test_from_the_main_window(app, songs, tmp_path, monkeypatch):  # noqa: F811
    from lazy_mixtape_maker.gui.main_window import MainWindow
    from test_oct30 import _mix_window
    w, _ = _mix_window(tmp_path)
    assert w.a_mashup.shortcut().toString() == "Ctrl+Shift+M"
    w.state.select(1)
    w.open_mashup_studio()
    ms = w._mashup
    sel = [t.song_id for t in w.state.plan.tracks[1:3]]
    assert [s.song_id for s in ms.m.songs] == sel
    assert "still need splitting" in ms.stems_label.text()
    from lazy_mixtape_maker import stems
    shown = []
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    monkeypatch.setattr(stems, "available", lambda: False)
    ms.ai_btn.click()                                                    # needs stems: explains how to get them
    assert shown and "with stems" in shown[0]
    ms.dirty = False
    ms.close()
    w.state.dirty = False
    w.close()
    assert isinstance(w, MainWindow)
