"""Project settings for the Visualization Studio, in one window: how the visuals are chosen, size and speed of the
video, the cover card, the blend between songs and the default transition."""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel,
                               QSpinBox, QVBoxLayout)

from ..video import MODE_LABELS, MODES
from .transition_editor import TransitionEditor

SIZES = (("1280 × 720 (HD)", (1280, 720)), ("1920 × 1080 (Full HD)", (1920, 1080)), ("854 × 480", (854, 480)),
         ("1080 × 1080 (square)", (1080, 1080)))


class StudioSettingsDialog(QDialog):
    def __init__(self, video, shaders, has_source_video: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Project settings")
        self.v = video
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.mode = QComboBox()
        for k in MODES:
            self.mode.addItem(MODE_LABELS[k], k)
        self.mode.setCurrentIndex(max(0, self.mode.findData(video.mode)))
        self.single = QComboBox()
        for sh in shaders.all():
            self.single.addItem(sh.name, sh.id)
        self.single.setCurrentIndex(max(0, self.single.findData(video.single_shader)))
        self.blend = QDoubleSpinBox(); self.blend.setRange(0.5, 60); self.blend.setSingleStep(0.5); self.blend.setSuffix(" s")
        self.blend.setValue(video.blend)
        self.res = QComboBox()                                  # (not "size": that is a QWidget method)
        for label, (w, h) in SIZES:
            self.res.addItem(label, f"{w}x{h}")
        self.res.setCurrentIndex(max(0, self.res.findData(f"{video.width}x{video.height}")))
        self.fps = QComboBox()
        for v in (24, 30, 60):
            self.fps.addItem(f"{v} fps", v)
        self.fps.setCurrentIndex(max(0, self.fps.findData(video.fps)))
        self.crf = QSpinBox(); self.crf.setRange(10, 32); self.crf.setValue(video.crf)
        self.crf.setToolTip("Video quality: lower is sharper and makes a bigger file (18 is very good).")
        self.overlay = QCheckBox("Show cover art, artist and title (lower left)")
        self.overlay.setChecked(video.show_overlay)
        self.use_video = QCheckBox("Use the file's own video as the picture")
        self.use_video.setChecked(video.use_video)
        self.use_video.setEnabled(has_source_video)
        form.addRow("Visuals", self.mode)
        form.addRow("The one visual", self.single)
        form.addRow("Visual blend", self.blend)
        form.addRow("Size", self.res)
        form.addRow("Frame rate", self.fps)
        form.addRow("Quality (CRF)", self.crf)
        lay.addLayout(form)
        lay.addWidget(self.overlay)
        lay.addWidget(self.use_video)
        lay.addWidget(QLabel("<b>Default transition between songs</b>"))
        self.trans = TransitionEditor()
        self.trans.set_value(video.transition)
        lay.addWidget(self.trans)
        self.mode.currentIndexChanged.connect(self._sync)
        self._sync()
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Apply")
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _sync(self):
        self.single.setEnabled(self.mode.currentData() == "single")

    def changes(self) -> dict:
        """Only what is different from the project's current settings."""
        w, h = (int(x) for x in self.res.currentData().split("x"))
        new = {"mode": self.mode.currentData(), "single_shader": self.single.currentData(), "blend": self.blend.value(),
               "width": w, "height": h, "fps": self.fps.currentData(), "crf": self.crf.value(),
               "show_overlay": self.overlay.isChecked(), "use_video": self.use_video.isChecked(),
               "transition": self.trans.value()}
        return {k: val for k, val in new.items() if getattr(self.v, k) != val}
