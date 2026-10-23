from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


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
        QPushButton { padding: 5px 12px; border-radius: 5px; border: 1px solid #3a3f4b; }
        QPushButton:hover { background: #3a3f4b; }
        QPushButton:disabled { color: #6b7282; }
        QTabBar::tab { padding: 6px 14px; }
        QListWidget::item:selected { background: #3b3f4d; }
        QToolBar { spacing: 6px; padding: 4px; border: 0; }
        QToolButton { padding: 5px 9px; border-radius: 5px; }
        QToolButton:hover { background: #3a3f4b; }
    """)
