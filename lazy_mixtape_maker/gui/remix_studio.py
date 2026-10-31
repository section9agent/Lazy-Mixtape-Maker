"""Shader Remix Studio: make a visual react to the music, and see it happen next to the original.

Pick effects (zoom, flash, colour shift, shake, RGB split, wobble, kaleidoscope, time push, contrast), how much of
each, and which part of the music (bass, mids, treble) drives it. A beat loop plays through both previews so you
can see the difference straight away. Save the result as a new visual, or update the remix you opened."""
from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from .. import remix as rmx
from ..video import AudioTexture
from ..visuals import Shader, ShaderError, ShaderLibrary
from .workers import FrameWorker

PREVIEW_W, PREVIEW_H = 400, 225
TEST_SR = 11025
TEST_SECONDS = 8.0


def beat_loop(seconds: float = TEST_SECONDS, sr: int = TEST_SR) -> np.ndarray:
    """A small made-up track to preview with: kick on every beat (120 BPM), hats, a bass note and a chord stab."""
    n = int(seconds * sr)
    y = np.zeros(n, np.float32)
    rng = np.random.default_rng(1)
    t = np.arange(int(0.5 * sr)) / sr
    kick = np.sin(2 * np.pi * (45 * t + 3.0 * (1 - np.exp(-30 * t)))) * np.exp(-t * 9) * 0.9
    hat = np.diff(rng.uniform(-1, 1, len(t) + 1)) * np.exp(-t * 70) * 0.35
    stab = sum(np.sin(2 * np.pi * f * t) for f in (440, 554.4, 659.3)) * np.exp(-t * 5) * 0.12
    for k in range(int(seconds / 0.5)):
        i = k * int(0.5 * sr)
        y[i:i + len(t)] += kick[: n - i]
        j = i + int(0.25 * sr)
        y[j:j + len(t)] += hat[: max(0, n - j)]
        if k % 2 == 0:
            y[i:i + len(t)] += stab[: n - i]
    y += 0.12 * np.sin(2 * np.pi * 55 * np.arange(n) / sr).astype(np.float32)
    return np.clip(y, -1, 1)[None, :]


class _Screen(QLabel):
    def __init__(self, text):
        super().__init__(text)
        self.setFixedSize(PREVIEW_W, PREVIEW_H)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background:#0b0b10;border-radius:6px;color:#8b93a1")


class RemixStudio(QDialog):
    """Opens on a visual. If it is already a remix, its settings are loaded and "Update" changes it in place."""

    def __init__(self, shaders: ShaderLibrary, shader: Shader, parent=None):
        super().__init__(parent)
        self.shaders = shaders
        self.orig = shader
        self.editing: Shader | None = shader if shader.remix.get("base") else None
        self.base_info = shaders.remix_base(shader)
        self.base = Shader(id="remix:base", name=self.base_info["name"], source=self.base_info["source"],
                           passes=[dict(p) for p in self.base_info["passes"]], origin="pasted")
        self.saved: Shader | None = None
        self._busy = False
        self.setWindowTitle(f"Shader Remix Studio — {self.base_info['name']}")
        self.resize(1000, 620)
        self.spec = rmx.normalize_spec(shader.remix.get("spec")) if self.editing else rmx.default_spec("club")
        self._remixed: Shader | None = None
        self._audio_on = AudioTexture(beat_loop()[:, :], TEST_SR)
        self._audio_off = AudioTexture(np.zeros((1, int(TEST_SECONDS * TEST_SR)), np.float32), TEST_SR)
        self._t0 = time.monotonic()
        self._frame_no = 0

        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        reacts = rmx.reacts_to_audio(self.base)
        self.head = QLabel(f"<b>{self.base_info['name']}</b><br>" + (
            "This visual already reacts to the music. A remix adds more on top of that." if reacts else
            "This visual <b>doesn't react to the music</b> yet. Switch on effects below to make it move with the sound."))
        self.head.setWordWrap(True)
        left.addWidget(self.head)
        top = QHBoxLayout()
        self.preset = QComboBox()
        self.preset.addItem("Start from a preset…", "")
        for k, (label, _m) in rmx.PRESETS.items():
            self.preset.addItem(label, k)
        self.preset.addItem("Everything off", "off")
        top.addWidget(self.preset, 1)
        top.addWidget(QLabel("Strength"))
        self.gain = QDoubleSpinBox(); self.gain.setRange(0.2, 3.0); self.gain.setSingleStep(0.1); self.gain.setDecimals(2)
        self.gain.setToolTip("How strongly the music drives every effect (turn it up if your music is quiet).")
        top.addWidget(self.gain)
        left.addLayout(top)
        grid = QGridLayout()
        grid.addWidget(QLabel("<b>Effect</b>"), 0, 0); grid.addWidget(QLabel("<b>Amount</b>"), 0, 1)
        grid.addWidget(QLabel("<b>Listens to</b>"), 0, 2)
        self.rows: dict[str, tuple[QCheckBox, QDoubleSpinBox, QComboBox]] = {}
        for r, m in enumerate(rmx.MODS, start=1):
            cb = QCheckBox(m.label); cb.setToolTip(m.tip)
            sp = QDoubleSpinBox(); sp.setRange(0.0, 2.0); sp.setSingleStep(0.1); sp.setDecimals(2); sp.setToolTip(m.tip)
            bd = QComboBox()
            for k, v in rmx.BANDS.items():
                bd.addItem(v, k)
            grid.addWidget(cb, r, 0); grid.addWidget(sp, r, 1); grid.addWidget(bd, r, 2)
            self.rows[m.key] = (cb, sp, bd)
            cb.toggled.connect(self._changed); sp.valueChanged.connect(self._changed); bd.currentIndexChanged.connect(self._changed)
        left.addLayout(grid)
        self.test = QComboBox()
        self.test.addItem("Preview with a beat loop", "beat")
        self.test.addItem("Preview with silence", "silence")
        left.addWidget(self.test)
        self.name = QLineEdit(self.editing.name if self.editing else f"{self.base_info['name']} (remix)")
        row = QHBoxLayout(); row.addWidget(QLabel("Name")); row.addWidget(self.name, 1)
        left.addLayout(row)
        self.msg = QLabel(); self.msg.setWordWrap(True); self.msg.setStyleSheet("color:#ff6b6b")
        left.addWidget(self.msg)
        btns = QHBoxLayout()
        self.b_save = QPushButton("Save as new visual")
        self.b_update = QPushButton("Update this remix")
        self.b_update.setVisible(self.editing is not None)
        self.b_close = QPushButton("Close")
        btns.addWidget(self.b_save); btns.addWidget(self.b_update); btns.addStretch(1); btns.addWidget(self.b_close)
        left.addLayout(btns)
        left.addStretch(1)
        lay.addLayout(left, 3)

        right = QVBoxLayout()
        right.addWidget(QLabel("Original"))
        self.s_orig = _Screen("starting…")
        right.addWidget(self.s_orig)
        right.addWidget(QLabel("Remix"))
        self.s_remix = _Screen("starting…")
        right.addWidget(self.s_remix)
        right.addStretch(1)
        lay.addLayout(right, 2)

        self._set_spec(self.spec)
        self.worker = FrameWorker(PREVIEW_W, PREVIEW_H, self)       # one drawing thread draws both pictures
        self.worker.frame.connect(self._frame)
        self.worker.unavailable.connect(lambda m: [s.setText("The preview needs OpenGL 3.3.\n" + m[:160]) for s in (self.s_orig, self.s_remix)])
        self.worker.failed.connect(lambda m, _t: self.s_remix.setText("Couldn't draw: " + m[-120:]))
        self.worker.start()
        self.preset.activated.connect(self._preset)
        self.gain.valueChanged.connect(self._changed)
        self.b_save.clicked.connect(lambda: self._save(False))
        self.b_update.clicked.connect(lambda: self._save(True))
        self.b_close.clicked.connect(self.accept)
        self._debounce = QTimer(self); self._debounce.setSingleShot(True); self._debounce.setInterval(300)
        self._debounce.timeout.connect(self._rebuild)
        self.timer = QTimer(self); self.timer.setInterval(40); self.timer.timeout.connect(self._tick)
        self._rebuild()
        self.timer.start()

    # ------------------------------------------------------------------ the settings
    def _set_spec(self, spec: dict):
        self._busy = True
        try:
            self.spec = rmx.normalize_spec(spec)
            self.gain.setValue(self.spec["gain"])
            for k, (cb, sp, bd) in self.rows.items():
                v = self.spec["mods"][k]
                cb.setChecked(v["on"]); sp.setValue(v["amount"]); bd.setCurrentIndex(max(0, bd.findData(v["band"])))
        finally:
            self._busy = False

    def current_spec(self) -> dict:
        return {"gain": self.gain.value(),
                "mods": {k: {"on": cb.isChecked(), "amount": sp.value(), "band": bd.currentData()}
                         for k, (cb, sp, bd) in self.rows.items()}}

    def _preset(self, _):
        k = self.preset.currentData()
        if not k:
            return
        if k == "off":
            spec = self.current_spec()
            for v in spec["mods"].values():
                v["on"] = False
        else:
            spec = rmx.default_spec(k)
        self._set_spec(spec)
        self.preset.setCurrentIndex(0)
        self._rebuild()

    def _changed(self, *_):
        if not self._busy:
            self._debounce.start()

    def _rebuild(self):
        self.msg.setText("")
        try:
            spec = self.current_spec()
            source, passes = rmx.apply(self.base.source, self.base.passes, spec)
        except rmx.RemixError as e:
            self.msg.setText(str(e))
            self._remixed = None
            return
        self.spec = rmx.normalize_spec(spec)
        self._remixed = Shader(id="remix:preview", name="preview", source=source, passes=passes, origin="pasted")

    # ------------------------------------------------------------------ the previews
    def _tick(self):
        if not self.isVisible():
            return
        t = time.monotonic() - self._t0
        self._frame_no += 1
        k = self._frame_no
        audio = self._audio_on if self.test.currentData() == "beat" else self._audio_off
        at = t % TEST_SECONDS

        remixed = self._remixed

        def job(r):
            out = []
            for tag, sh in (("orig", self.base), ("remix", remixed)):
                if sh is None:
                    continue
                r.audio = audio
                r.last_t = -1.0
                r.update_audio(at)
                r.draw_shader(sh, t, k, 0)
                out.append((tag, r.composite(0.0)))
            return out
        self.worker.submit(job)

    def _frame(self, img, tag):
        (self.s_orig if tag == "orig" else self.s_remix).setPixmap(QPixmap.fromImage(img))

    # ------------------------------------------------------------------ saving
    def _save(self, update: bool):
        self.msg.setText("")
        spec = self.current_spec()
        if not any(v["on"] and v["amount"] > 0 for v in spec["mods"].values()):
            self.msg.setText("Switch on at least one effect first.")
            return
        try:
            if update and self.editing is not None:
                self.saved = self.shaders.update_remix(self.editing.id, spec, self.name.text())
            else:
                self.saved = self.shaders.add_remix(self.orig, spec, self.name.text())
        except (ShaderError, rmx.RemixError, ValueError) as e:
            self.msg.setText(f"Couldn't save that remix:\n{e}")
            return
        self.accept()

    def done(self, r):
        self.timer.stop()
        self.worker.stop()
        self.worker.wait(3000)
        super().done(r)
