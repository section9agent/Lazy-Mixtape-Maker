"""Dialogs: generate-mix options, add a Shadertoy visual."""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox,
                               QTabWidget, QVBoxLayout, QWidget)

from ..plan import MixSettings
from ..visuals import ShaderError, ShaderLibrary


class GenerateDialog(QDialog):
    def __init__(self, settings: MixSettings, has_edits: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generate mix")
        self.s = settings
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.mode = QComboBox()
        self.mode.addItem("Whole songs — a seamless DJ mixtape", "full")
        self.mode.addItem("Short clips — highlight of each song (rave.dj style)", "clips")
        self.mode.setCurrentIndex(self.mode.findData(settings.mode))
        self.clip = QSpinBox(); self.clip.setRange(10, 120); self.clip.setSuffix(" seconds"); self.clip.setValue(int(settings.clip_seconds))
        self.bars = QSpinBox(); self.bars.setRange(1, 32); self.bars.setSuffix(" bars"); self.bars.setValue(settings.overlap_bars)
        self.style = QComboBox()
        for k, v in (("auto", "Let the AI choose"), ("eq_swap", "Bass-swap blends"), ("crossfade", "Crossfades"),
                     ("cut", "Hard cuts with effects")):
            self.style.addItem(v, k)
        self.style.setCurrentIndex(max(0, self.style.findData(settings.transition_style)))
        self.tempo = QComboBox()
        self.tempo.addItem("Let the tempo glide from song to song (best sound)", "drift")
        self.tempo.addItem("Hold one tempo for the whole mix", "locked")
        self.tempo.setCurrentIndex(max(0, self.tempo.findData(settings.tempo_mode)))
        self.cue = QComboBox()
        for k, v in (("start", "When the new song starts to come in"), ("middle", "Middle of the blend"),
                     ("end", "When the old song has gone")):
            self.cue.addItem(v, k)
        self.cue.setCurrentIndex(max(0, self.cue.findData(settings.cue_point)))
        self.order = QCheckBox("Let the AI choose the song order (smoothest tempo and key flow)")
        self.order.setChecked(settings.order == "auto")
        self.key = QCheckBox("Match keys (shift songs by up to 2 semitones so they sound good together)")
        self.key.setChecked(settings.key_match)
        self.fx = QCheckBox("Let the AI add effects (echo, filter sweeps, backspins …)")
        self.fx.setChecked(settings.use_effects)
        self.stretch = QSpinBox(); self.stretch.setRange(2, 30); self.stretch.setSuffix(" %"); self.stretch.setValue(int(settings.max_tempo_stretch * 100))
        form.addRow("Style", self.mode)
        form.addRow("Clip length", self.clip)
        form.addRow("Blend length", self.bars)
        form.addRow("Transitions", self.style)
        form.addRow("Tempo", self.tempo)
        form.addRow("Cue sheet marks", self.cue)
        form.addRow("Biggest tempo change", self.stretch)
        lay.addLayout(form)
        for w in (self.order, self.key, self.fx):
            lay.addWidget(w)
        if has_edits:
            warn = QLabel("This starts the mix over: changes you made by hand to timing, effects and trims are replaced.")
            warn.setWordWrap(True); warn.setStyleSheet("color:#e0a030")
            lay.addWidget(warn)
        self.mode.currentIndexChanged.connect(self._sync)
        self._sync()
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Generate")
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _sync(self):
        self.clip.setEnabled(self.mode.currentData() == "clips")

    def result_settings(self) -> MixSettings:
        s = MixSettings(**{k: getattr(self.s, k) for k in self.s.__dataclass_fields__})
        s.mode = self.mode.currentData()
        s.clip_seconds = float(self.clip.value())
        s.overlap_bars = self.bars.value()
        s.transition_style = self.style.currentData()
        s.order = "auto" if self.order.isChecked() else "given"
        s.key_match = self.key.isChecked()
        s.tempo_mode = self.tempo.currentData()
        s.cue_point = self.cue.currentData()
        s.use_effects = self.fx.isChecked()
        s.max_tempo_stretch = self.stretch.value() / 100.0
        return s


class AddVisualDialog(QDialog):
    """Add a Shadertoy shader: paste the code, load a file, or (online, optional) use its link."""

    def __init__(self, shaders: ShaderLibrary, parent=None):
        super().__init__(parent)
        self.shaders = shaders
        self.added = None
        self.setWindowTitle("Add a visual from Shadertoy")
        self.resize(640, 520)
        lay = QVBoxLayout(self)
        info = QLabel(
            "Find a shader on <b>shadertoy.com</b>, then copy its code from the editor (or use <i>Download</i> → JSON) "
            "and paste it here. It's saved on this computer, so it works offline from then on. Multi-pass shaders "
            "(Buffer A–D) work; inputs that need the internet, a webcam or video are replaced by noise.")
        info.setWordWrap(True); info.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(info)
        self.name = QLineEdit(); self.name.setPlaceholderText("Name (optional)")
        lay.addWidget(self.name)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        self.paste = QPlainTextEdit(); self.paste.setPlaceholderText("Paste the shader code (or Shadertoy JSON) here…")
        self.paste.setStyleSheet("font-family: monospace")
        self.tabs.addTab(self.paste, "Paste code")
        f = QWidget(); fl = QVBoxLayout(f)
        row = QHBoxLayout()
        self.file_label = QLabel("No file chosen")
        pick = QPushButton("Choose a file…")
        row.addWidget(pick); row.addWidget(self.file_label, 1)
        fl.addLayout(row); fl.addWidget(QLabel("A .glsl / .txt file with the code, or a Shadertoy .json export.")); fl.addStretch(1)
        self.tabs.addTab(f, "From a file")
        self.file_path = ""
        o = QWidget(); ol = QFormLayout(o)
        self.url = QLineEdit(); self.url.setPlaceholderText("https://www.shadertoy.com/view/XXXXXX")
        self.key = QLineEdit(); self.key.setPlaceholderText("Your Shadertoy API key")
        self.key.setText(str(QSettings().value("shadertoy_key", "")))
        ol.addRow("Link", self.url); ol.addRow("API key", self.key)
        hint = QLabel("Optional, needs internet. Get a free key on shadertoy.com (profile → Apps). "
                      "Everything else in the app works offline.")
        hint.setWordWrap(True); hint.setStyleSheet("color:#8b93a1")
        ol.addRow(hint)
        self.tabs.addTab(o, "From a link (online)")
        self.msg = QLabel(); self.msg.setWordWrap(True); self.msg.setStyleSheet("color:#ff6b6b")
        lay.addWidget(self.msg)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.go = bb.addButton("Add visual", QDialogButtonBox.ButtonRole.AcceptRole)
        bb.rejected.connect(self.reject)
        self.go.clicked.connect(self._add)
        lay.addWidget(bb)
        pick.clicked.connect(self._pick)

    def _pick(self):
        p, _ = QFileDialog.getOpenFileName(self, "Choose a shader", str(QSettings().value("last_dir", "")),
                                           "Shaders (*.glsl *.frag *.txt *.json);;All files (*)")
        if p:
            self.file_path = p
            self.file_label.setText(p)

    def _add(self):
        self.msg.setText("")
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            tab = self.tabs.currentIndex()
            name = self.name.text().strip()
            if tab == 0:
                sh = self.shaders.add_from_text(self.paste.toPlainText(), name)
            elif tab == 1:
                if not self.file_path:
                    raise ValueError("Choose a file first.")
                sh = self.shaders.add_from_file(self.file_path)
                if name:
                    self.shaders.rename(sh.id, name)
            else:
                QSettings().setValue("shadertoy_key", self.key.text().strip())
                sh = self.shaders.add_from_shadertoy(self.url.text(), self.key.text().strip())
                if name:
                    self.shaders.rename(sh.id, name)
            self.added = sh
            self.accept()
        except (ShaderError, ValueError, OSError, KeyError) as e:
            self.msg.setText(f"Couldn't use that shader:\n{e}")
        finally:
            self.unsetCursor()
