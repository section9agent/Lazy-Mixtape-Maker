"""Small-screen helpers (Steam Deck: 1280×800).

When a window is maximised on a screen smaller than its contents need, Qt squeezes widgets below their minimum
size and they end up drawn on top of each other. Pages that scroll instead keep every control usable."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QScrollArea, QSizePolicy, QTabWidget, QWidget


class _Holder(QWidget):
    """Holds a page inside a scroll area. QScrollArea sizes a page with word-wrapping labels to its preferred
    height-for-width (so it never shrinks before scrolling); the holder offers only the page's real minimum."""

    def __init__(self, page: QWidget):
        super().__init__()
        self.page = page
        page.setParent(self)
        page.installEventFilter(self)

    def eventFilter(self, obj, ev):                            # noqa: N802
        if obj is self.page and ev.type() == QEvent.Type.LayoutRequest:
            self.updateGeometry()
        return False

    def sizeHint(self):                                        # noqa: N802
        return self.page.sizeHint()

    def minimumSizeHint(self):                                 # noqa: N802
        m = self.page.minimumSizeHint().expandedTo(self.page.minimumSize())
        lay = self.page.layout()
        w = max(self.width(), m.width())
        if lay is not None and lay.hasHeightForWidth() and w > 0:
            # wrapped text takes more lines when narrower: the least height that fits at this width
            m.setHeight(max(m.height(), lay.minimumHeightForWidth(w) + 2))
        return m

    def resizeEvent(self, ev):                                 # noqa: N802
        self.page.setGeometry(self.rect())
        if ev.oldSize().width() != ev.size().width():
            self.updateGeometry()                  # (the height it needs depends on the width)


def scrollable(w: QWidget) -> QScrollArea:
    """`w` inside a frameless scroll area that only shows scroll bars when there isn't room."""
    sa = QScrollArea()
    sa.setWidget(_Holder(w))
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.Shape.NoFrame)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    sa.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    sa.setMinimumSize(QSize(120, 80))
    sa._page = w
    return sa


class FitTabs(QTabWidget):
    """Tabs whose pages scroll when the window is too small for them, instead of being crushed.

    addTab/insertTab wrap the page (pass wrap=False for pages that scroll by themselves); currentWidget(),
    setCurrentWidget(), widget() and indexOf() all work with the pages themselves, not the wrappers."""

    def addTab(self, page, label, wrap: bool = True):          # noqa: N802 (Qt naming)
        return super().addTab(scrollable(page) if wrap else page, label)

    def insertTab(self, index, page, label, wrap: bool = True):  # noqa: N802
        return super().insertTab(index, scrollable(page) if wrap else page, label)

    @staticmethod
    def _inner(w):
        return getattr(w, "_page", w) if w is not None else None

    def widget(self, index):
        return self._inner(super().widget(index))

    def currentWidget(self):                                   # noqa: N802
        return self._inner(super().currentWidget())

    def indexOf(self, page):                                   # noqa: N802
        for i in range(self.count()):
            if self.widget(i) is page:
                return i
        return super().indexOf(page)

    def setCurrentWidget(self, page):                          # noqa: N802
        i = self.indexOf(page)
        if i >= 0:
            self.setCurrentIndex(i)


class FitImage(QWidget):
    """Shows a picture as large as fits (keeping its shape) - unlike a QLabel with a pixmap, it never forces its
    parent to be at least the picture's size."""

    def __init__(self, min_size=QSize(160, 90), parent=None):
        super().__init__(parent)
        self._pix: QPixmap | None = None
        self._text = ""
        self.setMinimumSize(min_size)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def setPixmap(self, pix: QPixmap):                         # noqa: N802
        self._pix, self._text = pix, ""
        self.update()

    def setText(self, text: str):                              # noqa: N802
        self._pix, self._text = None, text
        self.update()

    def clear(self):
        self._pix, self._text = None, ""
        self.update()

    def text(self) -> str:
        return self._text

    def pixmap(self):
        return self._pix

    def sizeHint(self):                                        # noqa: N802
        return QSize(480, 270)

    def hasHeightForWidth(self):                               # noqa: N802
        return False

    def paintEvent(self, ev):                                  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), self.palette().window().color().darker(160))
        if self._pix is not None and not self._pix.isNull():
            s = self._pix.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
            x, y = (self.width() - s.width()) // 2, (self.height() - s.height()) // 2
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawPixmap(x, y, s.width(), s.height(), self._pix)
        elif self._text:
            p.setPen(self.palette().placeholderText().color())
            p.drawText(self.rect().adjusted(8, 8, -8, -8), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                       self._text)
