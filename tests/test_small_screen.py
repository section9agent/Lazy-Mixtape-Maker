"""Small screens (Steam Deck, 1280×800): the main window must fit, and pages scroll instead of being crushed
(widgets squeezed below their minimum size end up drawn on top of each other)."""
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LMM_AUDIO_BACKEND", "null")


@pytest.fixture()
def big_font_window(tmp_path, monkeypatch):
    monkeypatch.setenv("LMM_DATA_DIR", str(tmp_path / "data"))
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    old = app.font()
    f = app.font()
    f.setPointSize(12)                  # SteamOS desktop mode uses big text
    app.setFont(f)
    from lazy_mixtape_maker.gui.main_window import MainWindow
    w = MainWindow()
    w.show()
    yield app, w
    w.state.dirty = False
    w.close()
    app.setFont(old)


def _settle(app, n=10):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.02)


def test_main_window_fits_a_steam_deck(big_font_window):
    app, w = big_font_window
    hint = w.minimumSizeHint()
    assert hint.width() <= 1100 and hint.height() <= 650, hint


def _crushed(page):
    """Widgets in `page` laid out smaller than their own minimum (what makes them overlap)."""
    from PySide6.QtWidgets import QAbstractSpinBox, QComboBox, QHeaderView, QScrollBar, QWidget
    bad = []
    for c in page.findChildren(QWidget):
        if not c.isVisibleTo(page) or c.parent() is None or isinstance(c, (QHeaderView, QScrollBar)) \
                or isinstance(c.parent(), (QAbstractSpinBox, QComboBox)):         # (their own inner parts)
            continue
        m = c.minimumSizeHint()
        if m.isValid() and c.height() + 1 < min(m.height(), c.maximumHeight()):
            bad.append((type(c).__name__, c.height(), m.height()))
    return bad


def test_pages_scroll_instead_of_squashing(big_font_window):
    app, w = big_font_window
    w.resize(1280, 760)
    _settle(app)
    sp = w.centralWidget()
    sp.setSizes([500, 220])                   # a short bottom area, like a maximised window on the Deck
    _settle(app)
    for i in range(w.bottom.count()):
        w.bottom.setCurrentIndex(i)
        _settle(app, 4)
        page = w.bottom.widget(i)
        assert not _crushed(page), (w.bottom.tabText(i), _crushed(page)[:5])
    for i in range(w.inspector.count()):
        w.inspector.setCurrentIndex(i)
        _settle(app, 4)
        assert not _crushed(w.inspector.widget(i)), w.inspector.tabText(i)


def test_tabs_still_hand_back_their_pages(big_font_window):
    app, w = big_font_window
    w.bottom.setCurrentWidget(w.visuals)
    assert w.bottom.currentWidget() is w.visuals and w.bottom.indexOf(w.library) == 4
    w.inspector.setCurrentWidget(w.inspector.trans_tab)
    assert w.inspector.currentWidget() is w.inspector.trans_tab


def test_shader_preview_shrinks_to_fit(big_font_window):
    app, w = big_font_window
    from PySide6.QtGui import QColor, QPixmap
    w.bottom.setCurrentWidget(w.library)
    w.resize(1280, 760)
    w.centralWidget().setSizes([380, 380])      # room for the page, but not for a full-size preview
    _settle(app)
    scr = w.library.screen
    pix = QPixmap(480, 270)
    pix.fill(QColor("red"))
    scr.setPixmap(pix)
    _settle(app, 3)
    assert scr.height() < 270 and scr.minimumSizeHint().height() <= 110
    assert scr.geometry().bottom() < w.library.b_play.geometry().top()     # never on top of the buttons
