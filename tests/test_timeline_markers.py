"""Timeline markers: transition badges you can drag and click, and effect markers that are easy to grab,
move, lengthen and nudge."""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LMM_AUDIO_BACKEND", "null")
sys.path.insert(0, str(Path(__file__).parent))
from test_oct25 import _gui_window  # noqa: E402

from lazy_mixtape_maker import plan as planmod  # noqa: E402


def _mouse(tl, kind, x, y, mods=None):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    pt = QPointF(x, y)
    btn = Qt.MouseButton.LeftButton
    held = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else btn
    if kind == QEvent.Type.MouseMove:
        btn = Qt.MouseButton.NoButton
    return QMouseEvent(kind, pt, tl.mapToGlobal(pt), btn, held, mods or Qt.KeyboardModifier.NoModifier)


def _drag(tl, x0, y, x1):
    from PySide6.QtCore import QEvent
    tl.mousePressEvent(_mouse(tl, QEvent.Type.MouseButtonPress, x0, y))
    kind = tl._drag and tl._drag["kind"]
    tl.mouseMoveEvent(_mouse(tl, QEvent.Type.MouseMove, x1, y))
    tl.mouseReleaseEvent(_mouse(tl, QEvent.Type.MouseButtonRelease, x1, y))
    return kind


@pytest.fixture()
def win(tmp_path, monkeypatch):
    app, w, _d = _gui_window(tmp_path, monkeypatch)
    w.timeline.set_zoom(20.0)
    yield app, w
    w.state.dirty = False
    w.close()


def test_transition_badge_drags_the_blend_length(win):
    app, w = win
    tl, st = w.timeline, w.state
    slots, rects = tl._rects()
    br = tl._badge_rect(1, slots[1], rects[1])
    assert br.width() >= 90 and br.bottom() < rects[0].top()          # its own row, above the songs
    tr = st.plan.transitions[0]
    beats0 = tr.overlap_beats
    beat_px = 60.0 / planmod.tr_tempo(st.plan, tr) * tl.pps
    assert _drag(tl, br.center().x(), br.center().y(), br.center().x() - 4 * beat_px) == "trans"
    assert st.plan.transition_after(0).overlap_beats == beats0 + 4        # left = longer
    st.undo() if hasattr(st, "undo") else None


def test_clicking_a_badge_opens_that_transition(win):
    app, w = win
    tl, st = w.timeline, w.state
    slots, rects = tl._rects()
    got = []
    tl.transition_clicked.connect(got.append)
    br = tl._badge_rect(2, slots[2], rects[2])
    _drag(tl, br.center().x(), br.center().y(), br.center().x() + 1)
    assert got == [1] and st.sel == 1
    assert w.inspector.currentWidget() is w.inspector.trans_tab


def test_effect_markers_are_big_enough_to_grab_and_lengthen(win):
    app, w = win
    tl, st = w.timeline, w.state
    t = st.plan.tracks[1]
    beat = 60.0 / (t.bpm or st.plan.master_bpm)
    e = planmod.add_effect(st.plan, 1, "echo", anchor="start", offset=4 * beat, duration=0.05)
    slots, rects = tl._rects()
    fr = tl._fx_rect(1, e, slots[1], rects[1])
    assert fr.width() >= 30 and fr.height() >= 20                        # even a very short effect
    hit = tl._hit(fr.center())
    assert hit[0] == "fx" and hit[2] is e
    assert tl._hit(fr.center() + type(fr.center())(0, fr.height() / 2 + 3))[0] == "fx"   # a near miss still grabs it
    # move it two beats later
    assert _drag(tl, fr.center().x(), fr.center().y(), fr.center().x() + 2 * beat * tl.pps) == "fx"
    e = next(x for x in st.plan.tracks[1].effects if x.id == e.id)
    assert e.offset == pytest.approx(6 * beat, abs=1e-6)
    # make it longer by its right end
    planmod.update_effect(st.plan, 1, e.id, duration=4 * beat)
    slots, rects = tl._rects()
    fr = tl._fx_rect(1, e, slots[1], rects[1])
    x = fr.right() - 2
    h = tl._hit(type(fr.center())(x, fr.center().y()))
    assert h[0] == "fx_len", (h, fr, e.duration, [(o.type, o.anchor, o.offset, o.duration) for o in st.plan.tracks[1].effects])
    _drag(tl, x, fr.center().y(), x + 2 * beat * tl.pps)
    e = next(x for x in st.plan.tracks[1].effects if x.id == e.id)
    assert e.duration == pytest.approx(6 * beat, abs=1e-6) and e.offset == pytest.approx(6 * beat, abs=1e-6)


def test_arrow_keys_nudge_the_selected_effect(win):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    app, w = win
    tl, st = w.timeline, w.state
    t = st.plan.tracks[1]
    beat = 60.0 / (t.bpm or st.plan.master_bpm)
    e = planmod.add_effect(st.plan, 1, "filter", anchor="start", offset=2 * beat, duration=beat)
    st.select(1, e.id)

    def key(k, mods=Qt.KeyboardModifier.NoModifier):
        tl.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, k, mods))
        return next(x for x in st.plan.tracks[1].effects if x.id == e.id).offset
    assert key(Qt.Key.Key_Right) == pytest.approx(2.25 * beat)
    assert key(Qt.Key.Key_Left, Qt.KeyboardModifier.ShiftModifier) == pytest.approx(1.25 * beat)


def test_markers_stand_out(win):
    """The blend zones and badges are drawn in their transition's colour, strongly enough to see at a glance."""
    from lazy_mixtape_maker.gui.timeline import trans_color
    app, w = win
    tl, st = w.timeline, w.state
    img = tl.grab().toImage()
    slots, rects = tl._rects()
    br = tl._badge_rect(1, slots[1], rects[1])
    want = trans_color(st.plan.transitions[0].type)
    c = img.pixelColor(int(br.left() + 6), int(br.center().y()))
    dim = (want.red() // 2 + 20, want.green() // 2 + 20)                 # (full colour when selected or hovered)
    assert min(abs(c.red() - r) + abs(c.green() - g) for r, g in (dim, (want.red(), want.green()))) < 40
    z = tl._trans_zone(1, slots[1], rects[1])
    bar = img.pixelColor(int(z.center().x()), int(tl._lane_y(0) + 1))
    assert abs(bar.green() - want.green()) < 40 and abs(bar.blue() - want.blue()) < 40
