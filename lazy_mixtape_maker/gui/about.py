"""Help > About: who made it, the open-source software it stands on, and a way to say thanks."""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea, QTextBrowser, QVBoxLayout,
                               QWidget)

from .. import __version__, _buildinfo, updater

AUTHORS = "Coded by Claude &amp; Emmanuel Hoachlander"
DONATE_EMAIL = "section9agent@hotmail.com"
DONATE_URL = ("https://www.paypal.com/donate/?business=section9agent%40hotmail.com&no_recurring=0"
              "&item_name=Lazy+Mixtape+Maker&currency_code=USD")

# (name, what it does here, licence, home page)
CREDITS = [
    ("Python", "the language everything is written in", "PSF License", "https://www.python.org"),
    ("Qt / PySide6", "the windows, buttons and timeline", "LGPL-3.0", "https://www.qt.io/qt-for-python"),
    ("NumPy", "number crunching for audio and pictures", "BSD-3-Clause", "https://numpy.org"),
    ("SciPy", "filters and signal processing", "BSD-3-Clause", "https://scipy.org"),
    ("librosa", "finding tempo, key and song parts", "ISC", "https://librosa.org"),
    ("Numba and llvmlite", "make the analysis fast", "BSD-2-Clause", "https://numba.pydata.org"),
    ("SoundFile and libsndfile", "reading and writing audio files", "BSD-3-Clause / LGPL-2.1", "https://python-soundfile.readthedocs.io"),
    ("Mutagen", "song tags and cover art", "GPL-2.0-or-later", "https://mutagen.readthedocs.io"),
    ("Pillow", "pictures and cover art", "MIT-CMU (HPND)", "https://python-pillow.org"),
    ("ModernGL", "drawing the shader visuals with OpenGL", "MIT", "https://github.com/moderngl/moderngl"),
    ("miniaudio (pyminiaudio)", "playing the mix", "MIT", "https://github.com/irmen/pyminiaudio"),
    ("FFmpeg and imageio-ffmpeg", "making the video and MP3 files", "FFmpeg: LGPL / GPL, imageio-ffmpeg: BSD-2-Clause",
     "https://ffmpeg.org"),
    ("pyloudnorm", "loudness measuring", "MIT", "https://github.com/csteinmetz1/pyloudnorm"),
    ("PyInstaller", "packaging the app so it runs without Python", "GPL-2.0 with exception for built apps", "https://pyinstaller.org"),
    ("Shadertoy", "the visuals library idea and the shaders themselves - every shader belongs to its author, "
                  "who is named on the shader's Shadertoy page", "per-shader (see each shader's page)", "https://www.shadertoy.com"),
]


def credits_html() -> str:
    rows = "".join(f"<tr><td><a href='{u}'><b>{n}</b></a></td><td>{d}</td><td>{lic}</td></tr>" for n, d, lic, u in CREDITS)
    return ("<table cellspacing='0' cellpadding='4' width='100%'><tr><th align='left'>Software</th>"
            f"<th align='left'>Used for</th><th align='left'>Licence</th></tr>{rows}</table>")


class AboutDialog(QDialog):
    def __init__(self, parent=None, icon_path=None, check_now=None):
        super().__init__(parent)
        self.setWindowTitle("About Lazy Mixtape Maker")
        self.resize(640, 640)
        lay = QVBoxLayout(self)
        head = QHBoxLayout()
        pic = QLabel()
        if icon_path:
            pm = QPixmap(str(icon_path))
            if not pm.isNull():
                pic.setPixmap(pm.scaled(84, 84, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        head.addWidget(pic)
        tag = _buildinfo.TAG
        txt = QLabel(f"<h2 style='margin:0'>Lazy Mixtape Maker</h2>Version {__version__}"
                     + (f" &nbsp;·&nbsp; build {tag}" if tag != "dev" else "") +
                     f"<br><b>{AUTHORS}</b><br>An offline auto-DJ: your music stays on your computer."
                     "<br><span style='color:#8b93a1'>Free software under the GNU GPL v3.</span>")
        txt.setTextFormat(Qt.TextFormat.RichText)
        txt.setWordWrap(True)
        head.addWidget(txt, 1)
        lay.addLayout(head)

        box = QLabel("<b>If you enjoy this program, please consider a donation.</b><br>"
                     "It's free and always will be, but a little thanks helps keep it growing.")
        box.setWordWrap(True)
        box.setStyleSheet("background:#2a2d38;border:1px solid #3a3f4b;border-radius:6px;padding:10px")
        lay.addWidget(box)
        row = QHBoxLayout()
        self.donate = QPushButton("♥  Donate with PayPal")
        self.donate.setToolTip(f"Opens PayPal in your browser - donations go to {DONATE_EMAIL}")
        self.donate.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(DONATE_URL)))
        row.addWidget(self.donate)
        row.addWidget(QLabel(f"<span style='color:#8b93a1'>goes to {DONATE_EMAIL}</span>"), 1)
        lay.addLayout(row)

        lay.addWidget(QLabel("<b>Built with open-source software</b> - thank you to everyone who made these:"))
        self.credits = QTextBrowser()
        self.credits.setOpenExternalLinks(True)
        self.credits.setHtml(credits_html())
        lay.addWidget(self.credits, 1)

        upd = QHBoxLayout()
        self.auto = QCheckBox("Check for updates automatically")
        self.auto.setChecked(updater.enabled())
        self.auto.toggled.connect(updater.set_enabled)
        upd.addWidget(self.auto, 1)
        self.b_check = QPushButton("Check for updates now")
        if check_now:
            self.b_check.clicked.connect(check_now)
        else:
            self.b_check.setEnabled(False)
        upd.addWidget(self.b_check)
        lay.addLayout(upd)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        lay.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
