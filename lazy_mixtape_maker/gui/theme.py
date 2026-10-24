from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPixmap
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
        QPushButton { padding: 7px 14px; min-height: 20px; font-size: 13px; border-radius: 6px; border: 1px solid #3a3f4b; }
        QPushButton:hover { background: #3a3f4b; }
        QPushButton:disabled { color: #6b7282; }
        QTabBar::tab { padding: 8px 18px; font-size: 13px; }
        QListWidget::item:selected { background: #3b3f4d; }
        QToolBar { spacing: 6px; padding: 4px; border: 0; }
        QToolButton { padding: 6px 12px; border-radius: 6px; font-size: 13px; font-weight: 600; }
        QToolButton:hover { background: #3a3f4b; }
    """)
