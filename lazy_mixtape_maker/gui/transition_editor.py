"""Controls for video transitions: one editor for all 20, used by the mix window and the studio."""
from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QSpinBox, QVBoxLayout, QWidget)

from .. import transitions as tr
from .state import AppState


class TransitionEditor(QWidget):
    """Type + every parameter. With allow_inherit there is a "use the default" box and value() is None while it's ticked."""
    changed = Signal()

    def __init__(self, allow_inherit: bool = False, parent=None):
        super().__init__(parent)
        self.allow_inherit = allow_inherit
        self._busy = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.inherit = QCheckBox("Use the default transition")
        self.inherit.setChecked(allow_inherit)
        self.inherit.setVisible(allow_inherit)
        lay.addWidget(self.inherit)
        self.body = QWidget()
        f = QFormLayout(self.body)
        f.setContentsMargins(0, 0, 0, 0)
        self.type = QComboBox()
        for k, label, kind, _ in tr.TRANSITIONS:
            self.type.addItem(("♪ " if kind == "rhythm" else "") + label, k)
        self.type.insertSeparator(self.type.count())
        for k, label in tr.RANDOM_CHOICES.items():
            self.type.addItem("🎲 " + label, k)
        self.type.setToolTip("Classic transitions, and ♪ ones that react to the kick and bass of the music.")
        self.duration = QDoubleSpinBox(); self.duration.setRange(0, 60); self.duration.setSingleStep(0.5)
        self.duration.setSuffix(" s"); self.duration.setSpecialValueText("Automatic")
        self.duration.setToolTip("How long the transition lasts. Automatic follows the audio blend (mixes) or the "
                                 "Visual blend setting (studio).")
        self.angle = QSpinBox(); self.angle.setRange(0, 359); self.angle.setSuffix("°")
        self.angle.setToolTip("Direction of wipes, pushes and blinds (0° = from the left, 90° = from the bottom); "
                              "start angle of the clock wipe.")
        self.soft = self._dspin(0, 1, 0.05, "How soft the edge of a wipe, iris, clock or dissolve is.")
        self.inten = self._dspin(0, 2, 0.1, "Strength: zoom amount, pixel size, swirl, shake, glitch, flash…")
        self.sens = self._dspin(0, 2, 0.1, "How strongly the ♪ transitions react to the music's kick and bass. "
                                           "0 = ignore the music.")
        self.ease = QComboBox()
        for k, v in tr.EASES.items():
            self.ease.addItem(v, k)
        self.rows = {}
        for key, label, w in (("type", "Transition", self.type), ("duration", "Length", self.duration),
                              ("angle", "Angle", self.angle), ("softness", "Softness", self.soft),
                              ("intensity", "Intensity", self.inten), ("sensitivity", "Beat sensitivity", self.sens),
                              ("ease", "Easing", self.ease)):
            f.addRow(label, w)
            self.rows[key] = (f.labelForField(w), w)
        lay.addWidget(self.body)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(350)
        self._timer.timeout.connect(self.changed)
        for w in (self.duration, self.angle, self.soft, self.inten, self.sens):
            w.valueChanged.connect(self._poke)
        for w in (self.type, self.ease):
            w.currentIndexChanged.connect(self._poke)
        self.inherit.toggled.connect(self._poke)
        self.type.currentIndexChanged.connect(self._enable)
        self.inherit.toggled.connect(self._enable)
        self._enable()

    @staticmethod
    def _dspin(lo, hi, step, tip):
        s = QDoubleSpinBox()
        s.setRange(lo, hi); s.setSingleStep(step); s.setDecimals(2); s.setToolTip(tip)
        return s

    def _poke(self, *_):
        if not self._busy:
            self._timer.start()

    def _enable(self, *_):
        off = self.allow_inherit and self.inherit.isChecked()
        k = self.type.currentData()
        used = set().union(*tr.USES.values()) if k not in tr.USES else tr.USES[k]
        self.type.setEnabled(not off)
        self.duration.setEnabled(not off)
        self.ease.setEnabled(not off)
        for key in ("angle", "softness", "intensity", "sensitivity"):
            label, w = self.rows[key]
            w.setEnabled(not off and key in used)
            label.setEnabled(not off and key in used)

    def set_value(self, d: dict | None):
        self._busy = True
        try:
            if self.allow_inherit:
                self.inherit.setChecked(d is None)
            p = tr.TransitionParams.from_dict(d)
            self.type.setCurrentIndex(max(0, self.type.findData(p.type)))
            self.duration.setValue(p.duration)
            self.angle.setValue(int(p.angle) % 360)
            self.soft.setValue(p.softness)
            self.inten.setValue(p.intensity)
            self.sens.setValue(p.sensitivity)
            self.ease.setCurrentIndex(max(0, self.ease.findData(p.ease)))
            self._enable()
        finally:
            self._busy = False

    def value(self) -> dict | None:
        if self.allow_inherit and self.inherit.isChecked():
            return None
        return tr.TransitionParams(
            type=self.type.currentData(), duration=self.duration.value(), angle=float(self.angle.value()),
            softness=self.soft.value(), intensity=self.inten.value(), sensitivity=self.sens.value(),
            ease=self.ease.currentData()).to_dict()


class TransitionsPanel(QWidget):
    """The mix window's "Video transitions" tab: the default for every song change, and an override for the
    transition into the selected song."""

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self._busy = False
        lay = QHBoxLayout(self)
        box = QGroupBox("Default transition (every song change)")
        bl = QVBoxLayout(box)
        self.default = TransitionEditor()
        bl.addWidget(self.default)
        self.use_video = QCheckBox("Use video files as the picture (instead of a visual)")
        self.use_video.setToolTip("Songs that are video files show their own video, in time with the music.")
        bl.addWidget(self.use_video)
        bl.addStretch(1)
        lay.addWidget(box, 1)
        self.sel_box = QGroupBox("Into the selected song")
        sl = QVBoxLayout(self.sel_box)
        self.head = QLabel("Select a song (not the first one) to give its transition its own settings.")
        self.head.setWordWrap(True)
        sl.addWidget(self.head)
        self.own = TransitionEditor(allow_inherit=True)
        sl.addWidget(self.own)
        sl.addStretch(1)
        lay.addWidget(self.sel_box, 1)
        info = QLabel("<b>Classic</b>: crossfade, dips, wipe, push, iris, clock, zoom, dissolve, pixelate, blinds, swirl.<br>"
                      "<b>♪ Rhythm</b>: beat zoom, flash, shake + RGB split, glitch, bass ripple, strobe, mosaic, kick spin "
                      "- they pulse with the kick and bass of your music.<br>🎲 Random picks a different one at each change. "
                      "Watch the result in <i>Preview video</i>.")
        info.setWordWrap(True)
        info.setStyleSheet("color:#8b93a1")
        lay.addWidget(info, 1)
        self.default.changed.connect(lambda: None if self._busy else state.edit_video(
            lambda v: setattr(v, "transition", self.default.value())))
        self.own.changed.connect(self._own_changed)
        self.use_video.toggled.connect(lambda c: None if self._busy else state.edit_video(lambda v: setattr(v, "use_video", c)))
        state.changed.connect(self.refresh)
        state.selection.connect(self.refresh)
        state.library_changed.connect(self.refresh)
        self.refresh()

    def _uid(self):
        i = self.state.sel
        return self.state.plan.tracks[i].uid if 0 < i < len(self.state.plan.tracks) else None

    def refresh(self):
        v = self.state.video
        self._busy = True
        try:
            self.default.set_value(v.transition)
            self.use_video.setChecked(v.use_video)
            uid = self._uid()
            self.sel_box.setEnabled(uid is not None)
            if uid is None:
                self.head.setText("Select a song (not the first one) to give its transition its own settings.")
                self.own.set_value(None)
            else:
                t = self.state.plan.tracks[self.state.sel]
                self.head.setText(f"Transition into <b>{self.state.lib[t.song_id].title}</b>")
                self.own.set_value(v.transitions.get(uid))
        finally:
            self._busy = False

    def _own_changed(self):
        uid = self._uid()
        if self._busy or uid is None:
            return
        val = self.own.value()

        def fn(v):
            if val is None:
                v.transitions.pop(uid, None)
            else:
                v.transitions[uid] = val
        self.state.edit_video(fn)
