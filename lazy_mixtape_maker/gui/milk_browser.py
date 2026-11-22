"""MilkDrop browser: look through the preset pack by category, watch presets live and add them as visuals,
or import .milk files from this computer."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout)

from .. import milkdrop
from ..video import AudioTexture
from ..visuals import Shader, ShaderError, ShaderLibrary
from .fit import FitImage
from .workers import FrameWorker

ALL = "__all__"


def import_milk_files(parent, shaders: ShaderLibrary) -> list[Shader]:
    """Ask for .milk files and add them; returns the visuals added."""
    d = str(QSettings().value("last_milk_dir", ""))
    paths, _ = QFileDialog.getOpenFileNames(parent, "Import MilkDrop presets", d, "MilkDrop presets (*.milk);;All files (*)")
    if not paths:
        return []
    QSettings().setValue("last_milk_dir", str(Path(paths[0]).parent))
    added, bad = [], []
    for p in paths:
        try:
            added.append(shaders.add_milk(Path(p)))
        except (ShaderError, OSError, UnicodeError) as e:
            bad.append(f"{Path(p).name}: {e}")
    if bad and parent is not None:
        QMessageBox.warning(parent, "Lazy Mixtape Maker", "Some files weren't added:\n\n" + "\n".join(bad[:12]))
    return added


class MilkBrowser(QDialog):
    def __init__(self, shaders: ShaderLibrary, parent=None):
        super().__init__(parent)
        self.shaders = shaders
        self.added: list[Shader] = []
        self.worker: FrameWorker | None = None
        self._audio = AudioTexture(None)
        self._t0 = time.monotonic()
        self._k = 0
        self.setWindowTitle("Add MilkDrop presets")
        self.resize(1060, 600)
        lay = QVBoxLayout(self)
        n = sum(len(v) for v in milkdrop.browse().values())
        head = ("<b>MilkDrop presets</b> — the Cream of the Crop pack, %d presets" % n) if milkdrop.pack_dir() \
            else "<b>MilkDrop presets</b> — the featured set (this install doesn't have the full pack)"
        lay.addWidget(QLabel(head))
        if not milkdrop.available():
            note = QLabel("MilkDrop isn't available on this computer, so presets can't be shown or drawn (they'd be "
                          "replaced by a built-in visual). " + milkdrop.why_unavailable()[:240])
            note.setWordWrap(True)
            note.setStyleSheet("color:#ffb454")
            lay.addWidget(note)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search names and authors…")
        self.search.setClearButtonEnabled(True)
        lay.addWidget(self.search)
        body = QHBoxLayout()
        self.cats = QListWidget()
        self.cats.setFixedWidth(170)
        body.addWidget(self.cats)
        self.items = QListWidget()
        self.items.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        body.addWidget(self.items, 1)
        right = QVBoxLayout()
        self.screen = FitImage(QSize(240, 135))
        self.screen.setMaximumSize(QSize(640, 360))
        self.screen.setText("Click a preset to watch it")
        right.addWidget(self.screen, 1)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setStyleSheet("color:#8b93a1")
        right.addWidget(self.info)
        body.addLayout(right)
        lay.addLayout(body, 1)
        row = QHBoxLayout()
        self.b_add = QPushButton("Add to my visuals")
        self.b_add.setToolTip("Add the selected presets (Ctrl/Shift-click to pick several).")
        self.b_import = QPushButton("Import .milk files…")
        self.b_close = QPushButton("Close")
        self.status = QLabel()
        self.status.setStyleSheet("color:#8b93a1")
        row.addWidget(self.b_add)
        row.addWidget(self.b_import)
        row.addWidget(self.status, 1)
        row.addWidget(self.b_close)
        lay.addLayout(row)

        self._all = milkdrop.browse()
        self.cats.addItem(QListWidgetItem(f"All ({n})"))
        self.cats.item(0).setData(Qt.ItemDataRole.UserRole, ALL)
        for c, ps in self._all.items():
            it = QListWidgetItem(f"{c} ({len(ps)})")
            it.setData(Qt.ItemDataRole.UserRole, c)
            self.cats.addItem(it)
        self.cats.setCurrentRow(0)
        self._debounce = QTimer(self, singleShot=True, interval=250, timeout=self.refill)
        self.search.textChanged.connect(lambda _: self._debounce.start())
        self.cats.currentRowChanged.connect(lambda _: self.refill())
        self.items.currentItemChanged.connect(lambda *_: self._pick())
        self.items.itemDoubleClicked.connect(lambda _: self.add_selected())
        self.b_add.clicked.connect(self.add_selected)
        self.b_import.clicked.connect(self.import_files)
        self.b_close.clicked.connect(self.reject)
        self.timer = QTimer(self, interval=40, timeout=self._tick)
        self.refill()

    # ------------------------------------------------------------ the lists
    def refill(self):
        cur = self.cats.currentItem()
        cat = cur.data(Qt.ItemDataRole.UserRole) if cur else ALL
        words = [w for w in self.search.text().lower().split() if w]
        self.items.clear()
        shown = 0
        for c, ps in self._all.items():
            if cat not in (ALL, c):
                continue
            for p in ps:
                if words and not all(w in p.stem.lower() for w in words):
                    continue
                it = QListWidgetItem(milkdrop.preset_name(p) + ("" if cat != ALL else f"   · {c}"))
                it.setData(Qt.ItemDataRole.UserRole, str(p))
                it.setData(Qt.ItemDataRole.UserRole + 1, c)
                it.setToolTip(p.name)
                self.items.addItem(it)
                shown += 1
                if shown >= 3000:          # plenty to scroll through; searching narrows it
                    break
        self.status.setText(f"{shown} shown" + (" (search to narrow it down)" if shown >= 3000 else ""))

    def _selected(self) -> list[tuple[Path, str]]:
        return [(Path(it.data(Qt.ItemDataRole.UserRole)), it.data(Qt.ItemDataRole.UserRole + 1))
                for it in self.items.selectedItems()]

    # ------------------------------------------------------------ adding
    def add_selected(self):
        got = []
        for p, cat in self._selected():
            try:
                got.append(self.shaders.add_milk(p, energy=milkdrop.energy_for(cat)))
            except (ShaderError, OSError) as e:
                self.status.setText(f"{p.name}: {e}")
        self.added += got
        if got:
            self.status.setText(f"Added {len(got)} to your visuals" if len(got) > 1 else f"Added “{got[0].name}”")

    def import_files(self):
        got = import_milk_files(self, self.shaders)
        self.added += got
        if got:
            self.status.setText(f"Imported {len(got)} preset{'s' if len(got) != 1 else ''}")

    # ------------------------------------------------------------ live preview
    def _pick(self):
        it = self.items.currentItem()
        if it is None:
            return
        p = Path(it.data(Qt.ItemDataRole.UserRole))
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            self.info.setText(str(e))
            return
        self._sh = Shader(id=f"browse:{abs(hash(str(p)))}", name=p.stem, source=text, kind="milkdrop")
        cat = it.data(Qt.ItemDataRole.UserRole + 1)
        self.info.setText(f"{p.stem}<br>{cat} · suits {dict(calm='calm', mid='medium', high='intense')[milkdrop.energy_for(cat)]} songs")
        if not milkdrop.available():
            return
        if self.worker is None:
            self.worker = FrameWorker(480, 270, self)
            self.worker.frame.connect(self._frame)
            self.worker.unavailable.connect(lambda m: self.screen.setText("Live preview needs OpenGL 3.3.\n" + m[:200]))
            self.worker.failed.connect(lambda m, _t: self.screen.setText("Couldn't draw this preset:\n" + m[-300:]))
            self.worker.start()
        self._t0 = time.monotonic()
        self.timer.start()
        self._tick()

    def _tick(self):
        sh = getattr(self, "_sh", None)
        if sh is None or self.worker is None:
            return
        t = time.monotonic() - self._t0
        self._k += 1
        audio = self._audio

        def job(r):
            r.audio = audio
            r.draw_shader(sh, t, 0, 0)
            return r.composite(0.0)
        self.worker.submit(job, sh.id)

    def _frame(self, img, tag):
        sh = getattr(self, "_sh", None)
        if sh is not None and tag == sh.id:
            self.screen.setPixmap(QPixmap.fromImage(img))

    def done(self, r):
        self.timer.stop()
        if self.worker is not None:
            self.worker.stop()
            self.worker.wait(3000)
            self.worker = None
        super().done(r)
