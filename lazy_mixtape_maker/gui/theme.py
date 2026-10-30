from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPixmap, QPolygonF
from PySide6.QtWidgets import QApplication


def glyph_icon(ch: str, size: int = 34, color: str = "#e6e9ef") -> QIcon:
    """A big toolbar icon drawn from a symbol character."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    f = QFont()
    f.setPixelSize(int(size * 0.78))
    p.setFont(f)
    p.setPen(QColor(color))
    p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, ch)
    p.end()
    dim = QPixmap(pm)
    q = QPainter(dim)
    q.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    q.fillRect(dim.rect(), QColor("#5b6272"))
    q.end()
    ic = QIcon(pm)
    ic.addPixmap(dim, QIcon.Mode.Disabled)
    return ic


def arrow_icon(up: bool, size: int = 30, color: str = "#f2f4f8") -> QIcon:
    """A bold, filled up / down arrow (thick shaft and a wide head) that stays crisp and heavy on every platform."""
    def draw(col: str) -> QPixmap:
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(col))
        u = size / 30.0
        pts = [(15, 3), (27, 16), (19.5, 16), (19.5, 27), (10.5, 27), (10.5, 16), (3, 16)]
        if not up:
            pts = [(x, 30 - y) for x, y in pts]
        p.drawPolygon(QPolygonF([QPointF(x * u, y * u) for x, y in pts]))
        p.end()
        return pm
    ic = QIcon(draw(color))
    ic.addPixmap(draw("#5b6272"), QIcon.Mode.Disabled)
    return ic


BUTTON_QSS = """
    QPushButton, QToolButton {
        color: #eef0f5;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #565d70, stop:0.48 #3f4455, stop:0.52 #383c4b, stop:1 #2d303c);
        border-style: solid; border-width: 1px 1px 4px 1px;
        border-color: #7d869c #14161b #0b0c10 #14161b;
        border-radius: 7px;
    }
    QPushButton:hover, QToolButton:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #69718a, stop:0.48 #4c5266, stop:0.52 #444a5d, stop:1 #363a4a);
        border-color: #9aa3bb #14161b #0b0c10 #14161b;
    }
    QPushButton:pressed, QToolButton:pressed, QPushButton:checked, QToolButton:checked {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2a2d38, stop:1 #3a3f4e);
        border-width: 4px 1px 1px 1px;
        border-color: #0b0c10 #14161b #5d657a #14161b;
    }
    QPushButton:checked, QToolButton:checked { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #7a2f3c, stop:1 #a63f52); }
    QPushButton:disabled, QToolButton:disabled {
        color: #6b7282; background: #2a2d36; border-width: 1px 1px 3px 1px; border-color: #3a3f4b #30333c #272a32 #30333c;
    }
    QPushButton:default { border-color: #ff8a9a #14161b #7a1f2e #14161b; }
"""


def apply_dark(app: QApplication):
    app.setStyle("Fusion")
    p = QPalette()
    c = QColor
    p.setColor(QPalette.ColorRole.Window, c("#23262e"))
    p.setColor(QPalette.ColorRole.WindowText, c("#e6e9ef"))
    p.setColor(QPalette.ColorRole.Base, c("#1b1d23"))
    p.setColor(QPalette.ColorRole.AlternateBase, c("#20232a"))
    p.setColor(QPalette.ColorRole.Text, c("#e6e9ef"))
    p.setColor(QPalette.ColorRole.Button, c("#2f333d"))
    p.setColor(QPalette.ColorRole.ButtonText, c("#e6e9ef"))
    p.setColor(QPalette.ColorRole.ToolTipBase, c("#2f333d"))
    p.setColor(QPalette.ColorRole.ToolTipText, c("#e6e9ef"))
    p.setColor(QPalette.ColorRole.Highlight, c("#ff5d73"))
    p.setColor(QPalette.ColorRole.HighlightedText, c("#ffffff"))
    p.setColor(QPalette.ColorRole.PlaceholderText, c("#7b8394"))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, c("#6b7282"))
    app.setPalette(p)
    app.setStyleSheet("""
        QToolTip { border: 1px solid #3a3f4b; padding: 4px; }
        QGroupBox { border: 1px solid #3a3f4b; border-radius: 6px; margin-top: 12px; padding-top: 8px; }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #aab2c0; }
        QPushButton { padding: 6px 14px; min-height: 20px; font-size: 13px; }
        QTabBar::tab { padding: 8px 18px; font-size: 13px; }
        QListWidget::item:selected { background: #3b3f4d; }
        QToolBar { spacing: 6px; padding: 4px; border: 0; }
        QToolButton { padding: 5px 12px; font-size: 13px; font-weight: 600; }
    """ + BUTTON_QSS)
