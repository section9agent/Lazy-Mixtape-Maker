"""Shader library: manage and preview the visuals (built in and downloaded from Shadertoy)."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
                               QVBoxLayout, QWidget)

from ..video import AudioTexture
from ..visuals import Shader, ShaderLibrary, shader_to_json
from .dialogs import AddVisualDialog, EditShaderDialog
from .workers import FrameWorker

ENERGY = (("calm", "Calm"), ("mid", "Medium"), ("high", "Intense"))
ORIGINS = {"builtin": "Built in", "pasted": "Pasted code", "file": "Imported file", "shadertoy-json": "Shadertoy JSON",
           "shadertoy-api": "Shadertoy link"}


class CodeDialog(QDialog):
    def __init__(self, sh: Shader, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Code — {sh.name}")
        self.resize(760, 560)
        lay = QVBoxLayout(self)
        box = QPlainTextEdit()
        box.setReadOnly(True)
        box.setStyleSheet("font-family: monospace")
        if sh.passes:
            parts = []
            for p in sh.passes:
                ins = ", ".join(f"iChannel{c} = {k}" for c, k in sorted(p.get("inputs", {}).items()))
                parts.append(f"// ===== {p['name']}{('  (' + ins + ')') if ins else ''} =====\n{p['code']}")
            box.setPlainText("\n\n".join(parts))
        else:
            box.setPlainText(sh.source)
        lay.addWidget(box)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        bb.button(QDialogButtonBox.StandardButton.Close).clicked.connect(self.accept)
        lay.addWidget(bb)


class ShaderManager(QWidget):
    """List of every visual with a live, animated preview and the tools to look after them."""
    changed = Signal()                 # something was added, removed or renamed
    use_clicked = Signal(str)          # "use this one" (shader id)

    def __init__(self, shaders: ShaderLibrary, thumbs, use_label: str = "", parent=None):
        super().__init__(parent)
        self.shaders, self.thumbs = shaders, thumbs
        self._busy = False
        self._t0 = time.monotonic()
        self._offset = 0.0
        self._frame_no = 0
        self.worker: FrameWorker | None = None
        self._fake_audio = AudioTexture(None)

        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        left.addWidget(QLabel("<b>Shader library</b> — stored on this computer, works offline"))
        self.list = QListWidget()
        self.list.setIconSize(QSize(96, 54))
        self.list.setSpacing(2)
        left.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.b_add = QPushButton("Add from Shadertoy…")
        self.b_remove = QPushButton("Remove")
        self.b_export = QPushButton("Export…")
        for b in (self.b_add, self.b_export, self.b_remove):
            row.addWidget(b)
        left.addLayout(row)
        row2 = QHBoxLayout()
        self.b_backup = QPushButton("Back up all…")
        self.b_backup.setToolTip("Save every visual you added (with their textures and clips) into one file.")
        self.b_restore = QPushButton("Import backup…")
        self.b_restore.setToolTip("Add back the visuals from a backup file.")
        row2.addWidget(self.b_backup); row2.addWidget(self.b_restore)
        left.addLayout(row2)
        lay.addLayout(left, 3)

        right = QVBoxLayout()
        self.screen = QLabel("Choose a visual to preview it")
        self.screen.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.screen.setFixedSize(480, 270)
        self.screen.setStyleSheet("background:#0b0b10;border-radius:6px;color:#8b93a1")
        right.addWidget(self.screen, 0, Qt.AlignmentFlag.AlignHCenter)
        ctl = QHBoxLayout()
        self.b_play = QPushButton("❚❚ Pause")
        self.b_restart = QPushButton("↺ Restart")
        ctl.addWidget(self.b_play); ctl.addWidget(self.b_restart); ctl.addStretch(1)
        self.b_use = QPushButton(use_label or "Use")
        self.b_use.setVisible(bool(use_label))
        ctl.addWidget(self.b_use)
        right.addLayout(ctl)
        form = QFormLayout()
        self.name = QLineEdit()
        self.energy = QComboBox()
        for k, v in ENERGY:
            self.energy.addItem(v, k)
        self.energy.setToolTip("Used when the app picks visuals for you: calm ones suit quiet songs, intense ones loud songs.")
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.info.setOpenExternalLinks(True)
        self.info.setStyleSheet("color:#8b93a1")
        form.addRow("Name", self.name)
        form.addRow("Suits", self.energy)
        form.addRow(self.info)
        right.addLayout(form)
        self.b_code = QPushButton("View/Edit Code")
        right.addWidget(self.b_code, 0, Qt.AlignmentFlag.AlignLeft)
        self.warn = QLabel()
        self.warn.setWordWrap(True)
        self.warn.setStyleSheet("color:#ffb454")
        right.addWidget(self.warn)
        right.addStretch(1)
        lay.addLayout(right, 4)

        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._tick)
        self.list.currentItemChanged.connect(lambda *_: self._select())
        self.b_add.clicked.connect(self.add)
        self.b_remove.clicked.connect(self.remove)
        self.b_export.clicked.connect(self.export)
        self.b_code.clicked.connect(self.view_code)
        self.b_backup.clicked.connect(self.backup)
        self.b_restore.clicked.connect(self.restore)
        self.b_play.clicked.connect(self._toggle)
        self.b_restart.clicked.connect(self._restart)
        self.b_use.clicked.connect(lambda: self.current() and self.use_clicked.emit(self.current().id))
        self.name.editingFinished.connect(self._rename)
        self.energy.activated.connect(self._set_energy)
        thumbs.updated.connect(self._thumb)
        self.rebuild()

    # ----------------------------------------------------------------- list
    def current(self) -> Shader | None:
        it = self.list.currentItem()
        return self.shaders.get(it.data(Qt.ItemDataRole.UserRole)) if it else None

    def rebuild(self, keep: str | None = None):
        keep = keep or (self.current().id if self.current() else None)
        self._busy = True
        self.list.clear()
        for sh in self.shaders.all():
            tag = dict(ENERGY).get(sh.energy, "")
            it = QListWidgetItem(f"{sh.name}{' ⚠' if sh.warnings else ''}\n{ORIGINS.get(sh.origin, sh.origin)}"
                                 f"{' · ' + sh.author if sh.author else ''} · {tag}")
            it.setData(Qt.ItemDataRole.UserRole, sh.id)
            pm = self.thumbs.get(sh)
            if pm:
                it.setIcon(QIcon(pm))
            self.list.addItem(it)
            if sh.id == keep:
                self.list.setCurrentItem(it)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self._busy = False
        self._select()

    def _thumb(self, sid):
        for r in range(self.list.count()):
            it = self.list.item(r)
            if it.data(Qt.ItemDataRole.UserRole) == sid and self.thumbs.pix.get(sid):
                it.setIcon(QIcon(self.thumbs.pix[sid]))

    def _select(self):
        sh = self.current()
        self._busy = True
        self.name.setEnabled(bool(sh) and not sh.builtin)
        self.energy.setEnabled(bool(sh) and not sh.builtin)
        self.b_remove.setEnabled(bool(sh) and not sh.builtin)
        for b in (self.b_export, self.b_code, self.b_use, self.b_restart, self.b_play):
            b.setEnabled(bool(sh))
        if sh:
            self.name.setText(sh.name)
            self.energy.setCurrentIndex(max(0, self.energy.findData(sh.energy)))
            bits = [ORIGINS.get(sh.origin, sh.origin)]
            if sh.author:
                bits.append(f"by {sh.author}")
            if sh.passes:
                bits.append(f"{len(sh.passes) - (1 if sh.passes[0]['type'] == 'common' else 0)} passes")
            if sh.added:
                bits.append(f"added {sh.added[:10]}")
            text = " · ".join(bits)
            if sh.url:
                text += f'<br><a href="{sh.url}">{sh.url}</a>'
            self.info.setText(text)
            warns = list(sh.warnings)
            miss = sh.missing_media()
            if miss:
                warns.append("Needs " + ", ".join(f"{t} {n}" for _p, _c, t, n in miss)
                             + " - open View/Edit Code and pick the file(s).")
            self.warn.setText("\n".join(warns))
            self._restart()
        else:
            self.name.clear(); self.info.clear(); self.warn.clear()
            self.screen.clear(); self.screen.setText("Choose a visual to preview it")
        self._busy = False

    # -------------------------------------------------------------- actions
    def add(self):
        dlg = AddVisualDialog(self.shaders, self)
        if dlg.exec() and dlg.added:
            self.rebuild(dlg.added.id)
            self.changed.emit()
            if dlg.added.warnings:
                QMessageBox.information(self, "Lazy Mixtape Maker", "Added, with a note:\n\n" + "\n".join(dlg.added.warnings))

    def remove(self):
        sh = self.current()
        if not sh or sh.builtin:
            return
        if QMessageBox.question(self, "Lazy Mixtape Maker", f"Remove “{sh.name}” from this computer?") \
                != QMessageBox.StandardButton.Yes:
            return
        self.shaders.remove(sh.id)
        self.thumbs.forget(sh.id)
        self.rebuild()
        self.changed.emit()

    def export(self):
        sh = self.current()
        if not sh:
            return
        d = str(QSettings().value("last_export_dir", ""))
        multi = bool(sh.passes)
        flt = "Shadertoy JSON (*.json)" if multi else "Shader code (*.glsl);;Shadertoy JSON (*.json)"
        path, chosen = QFileDialog.getSaveFileName(self, "Export visual", str(Path(d) / (sh.name.replace("/", "-") + (".json" if multi else ".glsl"))), flt)
        if not path:
            return
        p = Path(path)
        if p.suffix.lower() == ".json" or multi:
            p.write_text(shader_to_json(sh), encoding="utf-8")
        else:
            p.write_text(sh.source, encoding="utf-8")

    def view_code(self):
        sh = self.current()
        if not sh:
            return
        dlg = EditShaderDialog(self.shaders, sh, self)
        dlg.exec()
        if dlg.saved:
            self.thumbs.forget(sh.id)
            self.rebuild(sh.id)
            self.changed.emit()

    def backup(self):
        d = str(QSettings().value("last_export_dir", ""))
        path, _ = QFileDialog.getSaveFileName(self, "Back up all visuals",
                                              str(Path(d) / time.strftime("LazyMixtapeMaker-visuals-%Y%m%d.lmmshaders")),
                                              "Shader backup (*.lmmshaders)")
        if not path:
            return
        try:
            n = self.shaders.backup(path)
        except OSError as e:
            QMessageBox.warning(self, "Lazy Mixtape Maker", f"Couldn't write the backup:\n{e}")
            return
        QMessageBox.information(self, "Lazy Mixtape Maker", f"Backed up {n} visual{'s' if n != 1 else ''}.")

    def restore(self):
        d = str(QSettings().value("last_export_dir", ""))
        path, _ = QFileDialog.getOpenFileName(self, "Import a visuals backup", d,
                                              "Shader backup (*.lmmshaders *.json)")
        if not path:
            return
        try:
            added, have = self.shaders.restore(path)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Lazy Mixtape Maker", f"Couldn't read that backup:\n{e}")
            return
        self.rebuild()
        self.changed.emit()
        QMessageBox.information(self, "Lazy Mixtape Maker",
                                f"Added {added} visual{'s' if added != 1 else ''}"
                                + (f"; {have} were already here." if have else "."))

    def _rename(self):
        sh = self.current()
        if self._busy or not sh or sh.builtin or not self.name.text().strip() or self.name.text().strip() == sh.name:
            return
        self.shaders.rename(sh.id, self.name.text())
        self.rebuild(sh.id)
        self.changed.emit()

    def _set_energy(self, _):
        sh = self.current()
        if self._busy or not sh or sh.builtin:
            return
        self.shaders.set_energy(sh.id, self.energy.currentData())
        self.rebuild(sh.id)
        self.changed.emit()

    # -------------------------------------------------------- live preview
    def _ensure_worker(self):
        if self.worker is None:
            self.worker = FrameWorker(480, 270, self)
            self.worker.frame.connect(self._frame)
            self.worker.unavailable.connect(lambda m: self.screen.setText("Live preview needs OpenGL 3.3.\n" + m[:200]))
            self.worker.failed.connect(lambda m, _t: self.screen.setText("Couldn't draw this visual:\n" + m[-300:]))
            self.worker.start()

    def _restart(self):
        self._offset = 0.0
        self._t0 = time.monotonic()
        self._frame_no = 0
        self._inflight = False
        if self.current() and self.isVisible():
            self._ensure_worker()
            self.timer.start()
            self.b_play.setText("❚❚ Pause")
            self._tick()

    def _toggle(self):
        if self.timer.isActive():
            self._offset += time.monotonic() - self._t0
            self.timer.stop()
            self.b_play.setText("▶ Play")
        else:
            self._t0 = time.monotonic()
            self.timer.start()
            self.b_play.setText("❚❚ Pause")

    def _tick(self):
        sh = self.current()
        if not sh or self.worker is None:
            return
        t = self._offset + (time.monotonic() - self._t0)
        self._frame_no += 1
        k, audio = self._frame_no, self._fake_audio

        def job(r):
            r.audio = audio
            r.last_t = -1.0
            r.update_audio(t)
            r.draw_shader(sh, t, k, 0)
            return r.composite(0.0)
        self.worker.submit(job, sh.id)

    def _frame(self, img, tag):
        sh = self.current()
        if sh and tag == sh.id:
            self.screen.setPixmap(QPixmap.fromImage(img))

    def showEvent(self, e):
        super().showEvent(e)
        if self.current():
            self._restart()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.timer.stop()

    def shutdown(self):
        self.timer.stop()
        if self.worker:
            self.worker.stop()
            self.worker.wait(3000)
            self.worker = None
