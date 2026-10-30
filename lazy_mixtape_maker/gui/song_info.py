"""One dialog for a song's information (cover art, artist, title), used by the mix window and the studio.
It starts with what is in the song now; "Reset" goes back to what the audio file itself says."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QVBoxLayout)

IMAGES = "Images (*.png *.jpg *.jpeg *.webp *.bmp)"


class SongInfoDialog(QDialog):
    """artist/title: what is used now. cover: a picture file in use now (or None). file_*: what the audio file says
    (used by Reset); file_cover is a picture taken from the file (or None)."""

    def __init__(self, artist: str, title: str, cover: str | None, file_artist: str, file_title: str,
                 file_cover: str | None, parent=None, heading: str = "", start_dir: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Song information")
        self.file_artist, self.file_title, self.file_cover = file_artist, file_title, file_cover
        self.start_dir = start_dir
        self.action: object = "keep"           # "keep" | "file" | "none" | picture path
        self._shown = cover
        lay = QVBoxLayout(self)
        if heading:
            h = QLabel(heading)
            h.setStyleSheet("color:#8b93a1")
            h.setWordWrap(True)
            lay.addWidget(h)
        top = QHBoxLayout()
        self.pic = QLabel()
        self.pic.setFixedSize(150, 150)
        self.pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pic.setStyleSheet("background:#111;border:1px solid #3a3f4b;border-radius:6px;color:#8b93a1")
        top.addWidget(self.pic)
        col = QVBoxLayout()
        self.b_choose = QPushButton("Choose picture…")
        self.b_none = QPushButton("No cover")
        self.b_file = QPushButton("Use the file's cover")
        for b in (self.b_choose, self.b_none, self.b_file):
            col.addWidget(b)
        col.addStretch(1)
        top.addLayout(col)
        lay.addLayout(top)
        form = QFormLayout()
        self.artist = QLineEdit(artist)
        self.title = QLineEdit(title)
        form.addRow("Artist", self.artist)
        form.addRow("Title", self.title)
        lay.addLayout(form)
        self.b_reset = QPushButton("Reset everything to the file's own information")
        lay.addWidget(self.b_reset)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.b_choose.clicked.connect(self._choose)
        self.b_none.clicked.connect(lambda: self._set("none", None))
        self.b_file.clicked.connect(lambda: self._set("file", self.file_cover))
        self.b_reset.clicked.connect(self._reset)
        self.b_file.setEnabled(True)
        self._show()

    def _show(self):
        pm = QPixmap(self._shown) if self._shown else QPixmap()
        if pm.isNull():
            self.pic.setPixmap(QPixmap())
            self.pic.setText("no cover")
        else:
            self.pic.setPixmap(pm.scaled(146, 146, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _set(self, action, shown):
        self.action, self._shown = action, shown
        self._show()

    def _choose(self):
        p, _ = QFileDialog.getOpenFileName(self, "Cover art", self.start_dir, IMAGES)
        if p:
            self._set(p, p)

    def _reset(self):
        self.artist.setText(self.file_artist)
        self.title.setText(self.file_title)
        self._set("file", self.file_cover)

    def values(self) -> dict:
        return {"artist": self.artist.text().strip(), "title": self.title.text().strip(), "cover": self.action}
