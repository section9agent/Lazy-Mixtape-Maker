"""Dialogs: generate-mix options, add a Shadertoy visual."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox,
                               QTabWidget, QVBoxLayout, QWidget)

from ..plan import MixSettings
from ..visuals import (Shader, ShaderError, ShaderLibrary, add_media, build_passes, kind_media, media_path)


class GenerateDialog(QDialog):
    def __init__(self, settings: MixSettings, has_edits: bool, parent=None, playlist: bool = False, project: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Project settings" if project else "Generate mix")
        self.project = project
        self.playlist = playlist
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
        self.order.setChecked(settings.order == "auto" and not playlist)
        if playlist:
            self.order.setText("Songs are mixed in the order of your playlist (it is never reordered)")
            self.order.setEnabled(False)
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
        self.rebuild = QCheckBox("Rebuild the whole mix with these settings now")
        if project:
            self.rebuild.setToolTip("Off: the settings are applied to the mix as it is (tempo, blends, keys, effects the AI "
                                    "chose) and your hand edits and song order are kept. On: the mix is made again from scratch.")
            lay.addWidget(self.rebuild)
            note = QLabel("With the box off, your hand edits and the song order stay as they are. With it on, the mix starts "
                          "over: edits to timing, effects and trims are replaced, and the AI may reorder the songs if that is ticked.")
            note.setWordWrap(True); note.setStyleSheet("color:#8b93a1")
            lay.addWidget(note)
        if has_edits:
            warn = QLabel("This starts the mix over: changes you made by hand to timing, effects and trims are replaced.")
            warn.setWordWrap(True); warn.setStyleSheet("color:#e0a030")
            lay.addWidget(warn)
        self.mode.currentIndexChanged.connect(self._sync)
        self._sync()
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Apply" if project else "Generate")
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
        s.order = "auto" if self.order.isChecked() and not self.playlist else "given"
        s.key_match = self.key.isChecked()
        s.tempo_mode = self.tempo.currentData()
        s.cue_point = self.cue.currentData()
        s.use_effects = self.fx.isChecked()
        s.max_tempo_stretch = self.stretch.value() / 100.0
        return s


CHANNEL_LABELS = [("noise", "Nothing / noise texture"), ("audio", "Music (audio)"), ("keyboard", "Keyboard"),
                  ("buffer:A", "Buffer A"), ("buffer:B", "Buffer B"), ("buffer:C", "Buffer C"), ("buffer:D", "Buffer D"),
                  ("pick:texture", "Texture image…"), ("pick:video", "Video clip…")]
IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp)"
VIDEO_FILTER = "Video clips (*.mp4 *.webm *.mov *.mkv *.avi *.ogv)"


class ChannelCombo(QWidget):
    """What feeds one iChannel: noise, the music, a buffer, or a texture / video clip chosen with a browser.
    A shader that already refers to a texture or clip shows exactly that one (with a button to point it at a
    file on this computer); the generic "Texture image…" entries open the file browser."""

    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.combo = QComboBox()
        for k, v in CHANNEL_LABELS:
            self.combo.addItem(v, k)
        self.browse = QPushButton("…")
        self.browse.setFixedWidth(30)
        self.browse.setToolTip("Choose the texture / video file")
        self.browse.setVisible(False)
        lay.addWidget(self.combo, 1)
        lay.addWidget(self.browse)
        self._last = 0
        self.combo.activated.connect(self._picked)
        self.browse.clicked.connect(self._rebrowse)

    def _label(self, kind: str) -> str:
        t, n = kind_media(kind)
        name = n.split("_", 1)[-1] if "_" in n and len(n.split("_", 1)[0]) == 8 else n
        return f"{'Video' if t == 'video' else 'Texture'}: {name}" + ("" if media_path(n) else "  (file needed)")

    def set_kind(self, kind: str):
        i = self.combo.findData(kind)
        if i < 0 and kind_media(kind):
            self.combo.insertItem(self.combo.count() - 2, self._label(kind), kind)
            i = self.combo.findData(kind)
        self.combo.setCurrentIndex(max(0, i))
        self._last = self.combo.currentIndex()
        self.browse.setVisible(bool(kind_media(self.kind())))

    def kind(self) -> str:
        k = self.combo.currentData()
        return "noise" if str(k).startswith("pick:") else k

    def _choose(self, which: str) -> str | None:
        flt = VIDEO_FILTER if which == "video" else IMAGE_FILTER
        d = str(QSettings().value("last_media_dir", ""))
        path, _ = QFileDialog.getOpenFileName(self, f"Choose a {which}", d, flt)
        if not path:
            return None
        QSettings().setValue("last_media_dir", str(Path(path).parent))
        try:
            return f"{which}:{add_media(path)}"
        except OSError:
            return None

    def _picked(self, i):
        k = self.combo.itemData(i)
        if isinstance(k, str) and k.startswith("pick:"):
            new = self._choose(k.split(":")[1])
            if new is None:
                self.combo.setCurrentIndex(self._last)
                return
            self.set_kind(new)
        else:
            self._last = i
            self.browse.setVisible(bool(kind_media(self.kind())))

    def _rebrowse(self):
        t, n = kind_media(self.kind())
        new = self._choose(t)
        if new:
            i = self.combo.currentIndex()
            self.combo.setItemText(i, self._label(new))
            self.combo.setItemData(i, new)
            self._last = i


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
        self.combos: list[ChannelCombo] = []
        if has_inputs:
            row = QHBoxLayout()
            for ch in range(4):
                col = QVBoxLayout()
                col.addWidget(QLabel(f"iChannel{ch}"))
                c = ChannelCombo()
                self.combos.append(c)
                col.addWidget(c)
                row.addLayout(col)
            lay.addLayout(row)

    def text(self) -> str:
        return self.code.toPlainText()

    def inputs(self) -> dict:
        return {ch: c.kind() for ch, c in enumerate(self.combos) if c.kind() != "noise"}

    def set_text(self, text: str):
        self.code.setPlainText(text)

    def set_inputs(self, inputs: dict):
        for ch, c in enumerate(self.combos):
            c.set_kind((inputs or {}).get(str(ch), "noise"))


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
            "Visuals are saved on this computer, so they work offline from then on. Textures and video clips can be picked "
            "from your computer (or are downloaded with a link); webcam, cube-map and volume inputs are replaced by noise. "
            "Shaders that make their own sound are fine - that sound is muted.")
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



class EditShaderDialog(QDialog):
    """View and edit a saved shader: the code of every pass, and what feeds each iChannel (including the
    texture / video clip a shader uses). Saving checks that it compiles."""

    def __init__(self, shaders: ShaderLibrary, sh: Shader, parent=None):
        super().__init__(parent)
        self.shaders, self.sh = shaders, sh
        self.saved = False
        self.setWindowTitle(f"{'View' if sh.builtin else 'View / Edit'} code — {sh.name}")
        self.resize(780, 640)
        lay = QVBoxLayout(self)
        self.common = _PassEditor("Common", False)
        self.buf = {L: _PassEditor(f"Buffer {L}", True) for L in "ABCD"}
        self.image = _PassEditor("Image", True)
        multi = bool(sh.passes)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        if multi:
            self.tabs.addTab(self.common, "Common")
            for L in "ABCD":
                self.tabs.addTab(self.buf[L], f"Buffer {L}")
        self.tabs.addTab(self.image, "Image")
        self.tabs.setCurrentWidget(self.image)
        if multi:
            for p in sh.passes:
                if p["type"] == "common":
                    self.common.set_text(p["code"])
                elif p["type"] == "buffer":
                    self.buf[p["name"][-1].upper()].set_text(p["code"])
                    self.buf[p["name"][-1].upper()].set_inputs(p.get("inputs"))
                else:
                    self.image.set_text(p["code"])
                    self.image.set_inputs(p.get("inputs"))
        else:
            self.image.set_text(sh.source)
            self.image.set_inputs({"0": "audio"})
        for e in [self.common, *self.buf.values(), self.image]:
            e.code.setReadOnly(sh.builtin)
            for c in e.combos:
                c.setEnabled(not sh.builtin)
        miss = sh.missing_media()
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color:#ffb454")
        if miss:
            self.note.setText(self.shaders.media_instructions(sh.id))
        lay.addWidget(self.note)
        self.msg = QLabel(); self.msg.setWordWrap(True); self.msg.setStyleSheet("color:#ff6b6b")
        lay.addWidget(self.msg)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        self.save_btn = None
        if not sh.builtin:
            self.save_btn = bb.addButton("Save changes", QDialogButtonBox.ButtonRole.AcceptRole)
            self.save_btn.clicked.connect(self._save)
        bb.button(QDialogButtonBox.StandardButton.Close).clicked.connect(self.reject)
        lay.addWidget(bb)

    def _save(self):
        self.msg.setText("")
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            multi = bool(self.sh.passes) or any(e.text().strip() for e in (self.common, *self.buf.values()))
            img_in = self.image.inputs()
            if not multi and img_in == {0: "audio"}:
                self.shaders.update_code(self.sh.id, self.image.text(), [])
            else:
                source, passes = build_passes(
                    self.common.text(), {L: (e.text(), e.inputs()) for L, e in self.buf.items()},
                    (self.image.text(), img_in))
                if not passes:       # a bare image pass with no inputs
                    passes = [{"name": "Image", "type": "image", "code": source, "inputs": {}}]
                self.shaders.update_code(self.sh.id, source, passes)
            self.saved = True
            self.accept()
        except (ShaderError, ValueError, OSError) as e:
            self.msg.setText(f"Not saved:\n{e}")
        finally:
            self.unsetCursor()
