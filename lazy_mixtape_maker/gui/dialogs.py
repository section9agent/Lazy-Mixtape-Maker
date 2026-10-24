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
        self.bars = QSpinBox(); self.bars.setRange(1, 64); self.bars.setSuffix(" bars")
        self.bars.setToolTip("The AI uses each song's whole outro and the next song's whole intro for the blend, up to this many bars."); self.bars.setValue(settings.overlap_bars)
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
        form.addRow("Longest blend", self.bars)
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


CHANNEL_LABELS = [("noise", "Nothing / noise texture"), ("audio", "Music (audio)"), ("keyboard", "Keyboard"),
                  ("buffer:A", "Buffer A"), ("buffer:B", "Buffer B"), ("buffer:C", "Buffer C"), ("buffer:D", "Buffer D")]


class _PassEditor(QWidget):
    """Code box for one Shadertoy tab, plus what feeds its iChannel0-3 inputs."""

    def __init__(self, title: str, has_inputs: bool, placeholder: str = ""):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.code = QPlainTextEdit()
        self.code.setPlaceholderText(placeholder or f"Paste the {title} code here (leave empty if the shader has no {title} tab)")
        self.code.setStyleSheet("font-family: monospace")
        lay.addWidget(self.code, 1)
        self.combos: list[QComboBox] = []
        if has_inputs:
            row = QHBoxLayout()
            for ch in range(4):
                col = QVBoxLayout()
                col.addWidget(QLabel(f"iChannel{ch}"))
                c = QComboBox()
                for k, v in CHANNEL_LABELS:
                    c.addItem(v, k)
                self.combos.append(c)
                col.addWidget(c)
                row.addLayout(col)
            lay.addLayout(row)

    def text(self) -> str:
        return self.code.toPlainText()

    def inputs(self) -> dict:
        return {ch: c.currentData() for ch, c in enumerate(self.combos) if c.currentData() != "noise"}


class AddVisualDialog(QDialog):
    """Add a Shadertoy shader: paste its code (or Shadertoy JSON), fill in each tab of a multi-pass
    shader (Common, Buffer A-D, Image), or download it from its link (no API key needed)."""

    def __init__(self, shaders: ShaderLibrary, parent=None):
        super().__init__(parent)
        self.shaders = shaders
        self.added = None
        self.setWindowTitle("Add a visual from Shadertoy")
        self.resize(760, 640)
        lay = QVBoxLayout(self)
        info = QLabel(
            "Find a shader on <b>shadertoy.com</b>. Simple shaders: paste the code. Shaders with <i>Buffer</i> tabs: use "
            "<b>Multi-pass</b> and paste each tab. Or paste its <b>link</b> and it's downloaded for you. "
            "Visuals are saved on this computer, so they work offline from then on. Inputs that need the internet, a "
            "webcam or video are replaced by noise.")
        info.setWordWrap(True); info.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(info)
        self.name = QLineEdit(); self.name.setPlaceholderText("Name (optional)")
        lay.addWidget(self.name)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        # 1. paste
        self.paste = QPlainTextEdit(); self.paste.setPlaceholderText("Paste the shader code (or Shadertoy JSON) here…")
        self.paste.setStyleSheet("font-family: monospace")
        self.tabs.addTab(self.paste, "Paste code")
        # 2. multi-pass
        self.passes = QTabWidget()
        self.p_common = _PassEditor("Common", False)
        self.p_buf = {L: _PassEditor(f"Buffer {L}", True) for L in "ABCD"}
        self.p_image = _PassEditor("Image", True, "Paste the Image tab code here (required)")
        self.passes.addTab(self.p_common, "Common")
        for L in "ABCD":
            self.passes.addTab(self.p_buf[L], f"Buffer {L}")
        self.passes.addTab(self.p_image, "Image")
        self.passes.setCurrentWidget(self.p_image)
        mp = QWidget(); ml = QVBoxLayout(mp)
        hint = QLabel("Fill in only the tabs the shader has, then set which input each <i>iChannel</i> uses "
                      "(in Shadertoy it's shown under each tab). A buffer that reads its own name is a feedback loop.")
        hint.setWordWrap(True); hint.setTextFormat(Qt.TextFormat.RichText); hint.setStyleSheet("color:#8b93a1")
        ml.addWidget(hint); ml.addWidget(self.passes, 1)
        self.tabs.addTab(mp, "Multi-pass")
        # 3. link
        o = QWidget(); ol = QFormLayout(o)
        self.url = QLineEdit(); self.url.setPlaceholderText("https://www.shadertoy.com/view/XXXXXX")
        self.key = QLineEdit(); self.key.setPlaceholderText("Optional: your Shadertoy API key")
        self.key.setText(str(QSettings().value("shadertoy_key", "")))
        ol.addRow("Link", self.url); ol.addRow("API key (optional)", self.key)
        h2 = QLabel("Needs internet just for the download. No account or key is needed; a key is only a fallback. "
                    "Multi-pass shaders come down complete. If a shader's author turned off outside access, use "
                    "the Paste or Multi-pass tab.")
        h2.setWordWrap(True); h2.setStyleSheet("color:#8b93a1")
        ol.addRow(h2)
        self.tabs.addTab(o, "From a link")
        self.msg = QLabel(); self.msg.setWordWrap(True); self.msg.setStyleSheet("color:#ff6b6b")
        lay.addWidget(self.msg)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.go = bb.addButton("Add visual", QDialogButtonBox.ButtonRole.AcceptRole)
        bb.rejected.connect(self.reject)
        self.go.clicked.connect(self._add)
        lay.addWidget(bb)

    def _add(self):
        self.msg.setText("")
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            tab = self.tabs.currentIndex()
            name = self.name.text().strip()
            if tab == 0:
                sh = self.shaders.add_from_text(self.paste.toPlainText(), name)
            elif tab == 1:
                sh = self.shaders.add_from_passes(
                    name, self.p_common.text(),
                    {L: (e.text(), e.inputs()) for L, e in self.p_buf.items()},
                    (self.p_image.text(), self.p_image.inputs()))
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
