"""Mashup Studio: two songs split into stems, arranged on eight lanes - by hand, by the AI, or both."""
from __future__ import annotations

import copy
import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
                               QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox, QPushButton, QScrollArea, QSpinBox,
                               QSplitter, QToolBar, QVBoxLayout, QWidget)

import numpy as np

from .. import mashup as mm, stems
from ..audio_io import SR
from .panels import fmt_time
from .player import AudioPlayer
from .tasks import APP, TaskMixin

FILTER = "Mashup (*.lmmash)"
AUDIO_FILTER = "Music (*.mp3 *.wav *.flac *.m4a *.ogg *.aiff *.aif)"
EXPORT_FILTER = "WAV (*.wav);;FLAC (*.flac);;MP3 (*.mp3)"
STEM_COLORS = {"vocals": "#ef6f9a", "drums": "#f2a541", "bass": "#4cc9f0", "other": "#7fc8a9"}
SONG_TINT = ("#1b2233", "#2a1b2c")
LANE_H = 44
RULER_H = 26
LABEL_W = 118


def _lane_of(song: int, stem: str) -> int:
    return mm.LANES.index((song, stem))


class LaneLabels(QWidget):
    """The names of the eight lanes, beside the timeline (they don't scroll sideways)."""

    def __init__(self, studio):
        super().__init__()
        self.studio = studio
        self.setFixedWidth(LABEL_W)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#14161c"))
        names = self.studio.song_names()
        for k, (song, stem) in enumerate(mm.LANES):
            y = RULER_H + k * LANE_H
            p.fillRect(QRectF(0, y, LABEL_W, LANE_H - 1), QColor(SONG_TINT[song]))
            p.fillRect(QRectF(0, y, 5, LANE_H - 1), QColor(STEM_COLORS[stem]))
            p.setPen(QColor("#e6e9ef"))
            p.drawText(QRectF(12, y + 3, LABEL_W - 14, 18), Qt.AlignmentFlag.AlignLeft, f"{'AB'[song]}  {stem.capitalize()}")
            p.setPen(QColor("#8b93a1"))
            p.drawText(QRectF(12, y + 21, LABEL_W - 14, 18), Qt.AlignmentFlag.AlignLeft,
                       p.fontMetrics().elidedText(names[song], Qt.TextElideMode.ElideRight, LABEL_W - 16))


class MashupTimeline(QWidget):
    """Eight lanes of clips on the mashup's bar grid. Drag a clip to move it (Shift: no snapping), drag its
    edges to trim it, double-click an empty spot to add a clip, click the ruler to move the playhead."""
    selected = Signal(object)          # clip id or None
    seek = Signal(float)

    EDGE = 7

    def __init__(self, studio):
        super().__init__()
        self.studio = studio
        self.pps = 14.0                 # pixels per second
        self.playhead = 0.0
        self.sel: str | None = None
        self._drag = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.relayout()

    # ------------------------------------------------------------ geometry
    def relayout(self):
        m, lib = self.studio.m, self.studio.lib
        secs = (mm.length(m, lib) if m.ready() else 0.0) + 60.0
        self.setMinimumSize(int(max(600, secs * self.pps)), RULER_H + len(mm.LANES) * LANE_H + 4)
        self.update()

    def x_of(self, t: float) -> float:
        return t * self.pps

    def t_of(self, x: float) -> float:
        return max(0.0, x / self.pps)

    def lane_at(self, y: float) -> int | None:
        k = int((y - RULER_H) // LANE_H)
        return k if y >= RULER_H and 0 <= k < len(mm.LANES) else None

    def clip_rect(self, c) -> QRectF:
        m, lib = self.studio.m, self.studio.lib
        k = _lane_of(c.song, c.stem)
        return QRectF(self.x_of(c.start), RULER_H + k * LANE_H + 2, max(3.0, mm.clip_length(m, lib, c) * self.pps), LANE_H - 5)

    def clip_at(self, pos):
        for c in reversed(self.studio.m.clips):
            if self.clip_rect(c).contains(pos):
                return c
        return None

    # -------------------------------------------------------------- drawing
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.fillRect(self.rect(), QColor("#101217"))
        st = self.studio
        m, lib = st.m, st.lib
        for k, (song, _stem) in enumerate(mm.LANES):
            p.fillRect(QRectF(0, RULER_H + k * LANE_H, self.width(), LANE_H - 1), QColor(SONG_TINT[song]))
        if m.ready():
            bar = mm.bar_seconds(m, lib)
            beat = bar / 4
            step = 1 if bar * self.pps >= 34 else (4 if bar * self.pps >= 9 else 16)
            n = int(self.width() / self.pps / bar) + 2
            for j in range(n):
                x = self.x_of(j * bar)
                major = j % step == 0
                p.setPen(QPen(QColor("#3a4152" if major else "#232836")))
                p.drawLine(int(x), RULER_H, int(x), self.height())
                if beat * self.pps >= 10:
                    p.setPen(QPen(QColor("#1a1f2a")))
                    for b in (1, 2, 3):
                        xb = int(self.x_of(j * bar + b * beat))
                        p.drawLine(xb, RULER_H, xb, self.height())
        p.fillRect(QRectF(0, 0, self.width(), RULER_H - 1), QColor("#191c24"))
        if m.ready():
            p.setPen(QColor("#aab2c0"))
            bar = mm.bar_seconds(m, lib)
            step = 1 if bar * self.pps >= 34 else (4 if bar * self.pps >= 9 else 16)
            for j in range(0, int(self.width() / self.pps / bar) + 2, step):
                p.drawText(int(self.x_of(j * bar)) + 3, 17, str(j + 1))
        for c in m.clips:
            r = self.clip_rect(c)
            col = QColor(STEM_COLORS[c.stem])
            if c.muted:
                col = QColor("#4a505c")
            fill = QColor(col)
            fill.setAlpha(150 if c.muted else 200)
            p.fillRect(r, fill)
            self._paint_wave(p, c, r)
            fi, fo = c.fade_in * self.pps, c.fade_out * self.pps
            p.setPen(QPen(QColor(16, 18, 23, 200), 1.5))
            if fi > 2:
                p.drawLine(QPointF(r.left(), r.bottom()), QPointF(r.left() + fi, r.top()))
            if fo > 2:
                p.drawLine(QPointF(r.right() - fo, r.top()), QPointF(r.right(), r.bottom()))
            p.setPen(QPen(QColor("#ffffff") if c.id == self.sel else col.darker(160), 2 if c.id == self.sel else 1))
            p.drawRect(r.adjusted(0.5, 0.5, -0.5, -0.5))
            if r.width() > 40:
                p.setPen(QColor("#101217"))
                label = f"{'AB'[c.song]} {c.stem}" + (" (muted)" if c.muted else "")
                if abs(c.gain_db) > 0.05:
                    label += f"  {c.gain_db:+.1f} dB"
                p.drawText(r.adjusted(5, 2, -3, -2), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                           p.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, int(r.width()) - 8))
        x = int(self.x_of(self.playhead))
        p.setPen(QPen(QColor("#ff4d6d"), 2))
        p.drawLine(x, 0, x, self.height())

    def _paint_wave(self, p: QPainter, c, r: QRectF):
        """The stem's own waveform, drawn dark over the clip (as on the main window's timeline)."""
        st = self.studio
        sid = st.m.songs[c.song].song_id
        w = st.waves.get(sid, {}).get(c.stem)
        if w is None or not len(w):
            return
        clip = p.clipBoundingRect()
        x0 = max(r.left(), clip.left() - 2) if not clip.isEmpty() else r.left()
        x1 = min(r.right(), clip.right() + 2) if not clip.isEmpty() else r.right()
        if x1 - x0 < 1:
            return
        rate = mm.rate(st.m, st.lib, c.song)
        xs = np.arange(int(x0), int(x1) + 1, dtype=np.float64)
        amp = np.zeros(len(xs))
        for k in range(3):                       # a few looks per pixel so peaks survive zooming out
            src = c.src_start + ((xs - r.left()) + k / 3.0) / self.pps * rate
            idx = np.clip((src / mm.WAVE_STEP).astype(int), 0, len(w) - 1)
            amp = np.maximum(amp, w[idx])
        amp *= 10 ** (min(c.gain_db, 6.0) / 20)
        amp = np.minimum(amp, 1.0)
        top, bot = r.top() + 16, r.bottom() - 3
        mid, half = (top + bot) / 2, (bot - top) / 2
        path = QPainterPath()
        path.moveTo(xs[0], mid)
        for x, a in zip(xs, amp):
            path.lineTo(x, mid - a * half)
        for x, a in zip(xs[::-1], amp[::-1]):
            path.lineTo(x, mid + a * half)
        path.closeSubpath()
        p.fillPath(path, QColor(8, 8, 12, 150 if c.muted else 190))

    # ----------------------------------------------------------------- mouse
    def _snap(self, t: float, mods) -> float:
        st = self.studio
        if mods & Qt.KeyboardModifier.ShiftModifier or st.snap() == "off" or not st.m.ready():
            return max(0.0, t)
        g = mm.bar_seconds(st.m, st.lib) / (4 if st.snap() == "beat" else 1)
        return max(0.0, round(t / g) * g)

    def mousePressEvent(self, e):
        pos = e.position()
        st = self.studio
        if pos.y() < RULER_H:
            self.seek.emit(self.t_of(pos.x()))
            return
        c = self.clip_at(pos)
        self.sel = c.id if c else None
        self.selected.emit(self.sel)
        self.update()
        if e.button() == Qt.MouseButton.RightButton:
            self._menu(e, c)
            return
        if c is None or e.button() != Qt.MouseButton.LeftButton:
            return
        r = self.clip_rect(c)
        mode = "left" if pos.x() - r.left() < self.EDGE and r.width() > 3 * self.EDGE else \
               "right" if r.right() - pos.x() < self.EDGE else "move"
        self._drag = {"mode": mode, "x": pos.x(), "clip": c.id, "before": st.snapshot(), "orig": copy.copy(c), "moved": False}

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._drag is None:
            c = self.clip_at(pos)
            shape = Qt.CursorShape.ArrowCursor
            if c is not None:
                r = self.clip_rect(c)
                if pos.x() - r.left() < self.EDGE or r.right() - pos.x() < self.EDGE:
                    shape = Qt.CursorShape.SizeHorCursor
                else:
                    shape = Qt.CursorShape.OpenHandCursor
            self.setCursor(shape)
            return
        d = self._drag
        st = self.studio
        m, lib = st.m, st.lib
        c, o = m.clip(d["clip"]), d["orig"]
        if c is None:
            return
        dt = (pos.x() - d["x"]) / self.pps
        if abs(pos.x() - d["x"]) >= 2:
            d["moved"] = True
        an = lib[m.songs[c.song].song_id]
        r = mm.rate(m, lib, c.song)
        if d["mode"] == "move":
            c.start = self._snap(o.start + dt, e.modifiers())
            k = self.lane_at(pos.y())
            if k is not None and mm.LANES[k][0] == c.song:     # another stem of the same song
                c.stem = mm.LANES[k][1]
        elif d["mode"] == "left":
            new = self._snap(o.start + dt, e.modifiers())
            new = min(new, o.start + mm.clip_length(m, lib, o) - 0.1)
            src = o.src_start + (new - o.start) * r
            if src < 0:
                new, src = o.start - o.src_start / r, 0.0
            c.start, c.src_start = max(0.0, new), src
        else:
            end = self._snap(o.start + mm.clip_length(m, lib, o) + dt, e.modifiers())
            end = max(end, o.start + 0.1)
            c.src_end = min(an.duration, o.src_start + (end - o.start) * r)
        self.update()

    def mouseReleaseEvent(self, _e):
        d, self._drag = self._drag, None
        if d and d["moved"]:
            self.studio.edited(d["before"])

    def mouseDoubleClickEvent(self, e):
        pos = e.position()
        k = self.lane_at(pos.y())
        if k is None or self.clip_at(pos) is not None:
            return
        self.studio.add_clip(k, self._snap(self.t_of(pos.x()), e.modifiers()))

    def wheelEvent(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom(1.25 if e.angleDelta().y() > 0 else 0.8)
            e.accept()
        else:
            super().wheelEvent(e)

    def zoom(self, k: float):
        self.pps = float(min(400.0, max(1.0, self.pps * k)))
        self.relayout()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.sel:
            self.studio.delete_clip()
        else:
            super().keyPressEvent(e)

    def _menu(self, e, c):
        st = self.studio
        menu = QMenu(self)
        if c is not None:
            menu.addAction("Split at the playhead", st.split_clip)
            menu.addAction("Duplicate", st.duplicate_clip)
            menu.addAction("Unmute" if c.muted else "Mute", st.toggle_mute)
            menu.addSeparator()
            menu.addAction("Delete", st.delete_clip)
        else:
            k = self.lane_at(e.position().y())
            if k is not None and st.m.ready():
                song, stem = mm.LANES[k]
                t = self._snap(self.t_of(e.position().x()), e.modifiers())
                menu.addAction(f"Add song {'AB'[song]}'s {stem} here", lambda: st.add_clip(k, t))
                menu.addAction(f"Add all of song {'AB'[song]} here", lambda: st.add_whole_song(song, t))
        if not menu.isEmpty():
            menu.exec(e.globalPosition().toPoint())


class MashupStudio(TaskMixin, QMainWindow):
    def __init__(self, lib: dict | None = None, paths: dict | None = None, main=None, songs=()):
        super().__init__()
        self.main = main
        self.lib = dict(lib or {})
        self.paths = dict(paths or {})
        self.m = mm.Mashup()
        self.file: Path | None = None
        self.dirty = False
        self._undo: list[dict] = []
        self._redo: list[dict] = []
        self._busy = False
        self.renderer = mm.Renderer()
        self.waves: dict[str, dict] = {}          # song id -> {stem: envelope} for drawing
        self._wave_jobs: set[str] = set()
        self._waves_new = False
        self.player = AudioPlayer()
        self._render_path: str | None = None
        self._render_n = 0
        self.tmp = Path(tempfile.mkdtemp(prefix="lmm_mashup_"))
        self.settings = QSettings()
        self.setWindowTitle("Mashup Studio")
        self.resize(1280, 820)
        self._build()
        for i, sid in enumerate(list(songs)[:2]):
            self._set_song(i, sid, record=False)
        self._undo.clear()
        self.dirty = False
        self.refresh()
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    # ================================================================ layout
    def _build(self):
        tb = QToolBar("Mashup")
        tb.setMovable(False)
        self.addToolBar(tb)

        def act(text, fn, key=None, tip=None):
            a = QAction(text, self)
            a.triggered.connect(fn)
            if key:
                a.setShortcut(QKeySequence(key))
            if tip:
                a.setToolTip(tip)
            tb.addAction(a)
            return a
        self.a_new = act("New", self.new_mashup, "Ctrl+N")
        self.a_open = act("Open…", self.open_mashup, "Ctrl+O")
        self.a_save = act("Save", self.save, "Ctrl+S")
        tb.addSeparator()
        self.a_undo = act("Undo", self.undo, "Ctrl+Z")
        self.a_redo = act("Redo", self.redo, "Ctrl+Shift+Z")
        tb.addSeparator()
        self.a_play = act("▶ Play", self.toggle_play, "Space")
        self.a_stop = act("■ Stop", self.stop)
        tb.addSeparator()
        self.a_export = act("Export…", self.export, "Ctrl+E", "Save the mashup as a WAV, FLAC or MP3 file")
        self.a_tomix = act("Add to mix", self.add_to_mix, None, "Save the mashup and add it to your mixtape as a song")
        self.a_tomix.setVisible(self.main is not None)

        central = QWidget()
        self.setCentralWidget(central)
        lay = QVBoxLayout(central)

        top = QHBoxLayout()
        songs = QGroupBox("Songs")
        g = QGridLayout(songs)
        self.song_combo, self.song_info, self.split_btn = [], [], []
        for i in (0, 1):
            g.addWidget(QLabel(f"<b>Song {'AB'[i]}</b>"), i, 0)
            cb = QComboBox()
            cb.setMinimumWidth(260)
            cb.currentIndexChanged.connect(lambda _x, i=i: self._combo_changed(i))
            g.addWidget(cb, i, 1)
            other = QPushButton("Other file…")
            other.clicked.connect(lambda _x=False, i=i: self.choose_file(i))
            g.addWidget(other, i, 2)
            info = QLabel()
            info.setStyleSheet("color:#aab2c0")
            g.addWidget(info, i, 3)
            self.song_combo.append(cb)
            self.song_info.append(info)
        self.split_all = QPushButton("Split into stems")
        self.split_all.setToolTip("Both songs must be split into drums, bass, vocals and other (once per song).")
        self.split_all.clicked.connect(lambda: self.split_songs())
        self.stems_label = QLabel()
        self.stems_label.setWordWrap(True)
        g.addWidget(self.stems_label, 2, 0, 1, 3)
        g.addWidget(self.split_all, 2, 3)
        top.addWidget(songs, 3)

        match = QGroupBox("Matching")
        f = QFormLayout(match)
        self.beat = QCheckBox("Beat match (play both at one tempo)")
        self.tempo_from = QComboBox()
        for k, v in (("a", "Song A's tempo"), ("b", "Song B's tempo"), ("custom", "My own tempo:")):
            self.tempo_from.addItem(v, k)
        self.bpm = QDoubleSpinBox()
        self.bpm.setRange(50, 220)
        self.bpm.setDecimals(1)
        self.bpm.setSuffix(" BPM")
        row = QHBoxLayout()
        row.addWidget(self.tempo_from)
        row.addWidget(self.bpm)
        self.key = QCheckBox("Key match (shift one song to suit the other)")
        self.key_from = QComboBox()
        self.key_from.addItem("Keep song A's key", "a")
        self.key_from.addItem("Keep song B's key", "b")
        self.pitch = []
        prow = QHBoxLayout()
        for i in (0, 1):
            sp = QSpinBox()
            sp.setRange(-13, 12)
            sp.setSpecialValueText("auto")
            sp.setSuffix(" st")
            sp.setToolTip(f"Shift song {'AB'[i]} by this many semitones (auto = what key matching chooses)")
            prow.addWidget(QLabel(f"{'AB'[i]}:"))
            prow.addWidget(sp)
            self.pitch.append(sp)
        f.addRow(self.beat)
        f.addRow("Tempo", row)
        f.addRow(self.key)
        f.addRow("Key", self.key_from)
        f.addRow("Pitch", prow)
        self.vlevel = QComboBox()
        for k, t in mm.VOCAL_LEVELS.items():
            self.vlevel.addItem(t, k)
        self.vlevel.setToolTip("LUFS Lab's voice leveler on the vocals: it evens out quiet and loud lines "
                               "(silence and breaths aren't boosted), then sets their loudness")
        self.vlufs = QDoubleSpinBox()
        self.vlufs.setRange(-36, -6)
        self.vlufs.setDecimals(1)
        self.vlufs.setSingleStep(0.5)
        self.vlufs.setSuffix(" LUFS")
        self.vlufs.setToolTip("How loud the leveled vocals are (the music of a typical song is around -14 to -9 LUFS)")
        vrow = QHBoxLayout()
        vrow.addWidget(self.vlevel)
        vrow.addWidget(QLabel("to"))
        vrow.addWidget(self.vlufs)
        f.addRow("Level vocals", vrow)
        self.vlevel.currentIndexChanged.connect(lambda _x: self._set(lambda m: setattr(m, "vocal_level", self.vlevel.currentData())))
        self.vlufs.editingFinished.connect(lambda: self._set(lambda m: setattr(m, "vocal_lufs", float(self.vlufs.value()))))
        self.beat.toggled.connect(lambda on: self._set(lambda m: setattr(m, "beat_match", bool(on))))
        self.tempo_from.currentIndexChanged.connect(lambda _x: self._set(lambda m: setattr(m, "tempo_from", self.tempo_from.currentData())))
        self.bpm.editingFinished.connect(lambda: self._set(lambda m: setattr(m, "custom_bpm", float(self.bpm.value()))))
        self.key.toggled.connect(lambda on: self._set(lambda m: setattr(m, "key_match", bool(on))))
        self.key_from.currentIndexChanged.connect(lambda _x: self._set(lambda m: setattr(m, "key_from", self.key_from.currentData())))
        for i in (0, 1):
            self.pitch[i].valueChanged.connect(lambda v, i=i: self._set(
                lambda m: setattr(m.songs[i], "pitch", None if v == -13 else int(v))))
        top.addWidget(match, 2)

        ai = QGroupBox("Let the AI do it")
        v = QVBoxLayout(ai)
        self.style = QComboBox()
        for k, t in mm.STYLES.items():
            self.style.addItem(t, k)
        self.ai_btn = QPushButton("✨ Mash it up")
        self.ai_btn.setMinimumHeight(40)
        self.ai_btn.setToolTip("Lay out a whole mashup (it replaces the clips there are now - Undo brings them back)")
        self.ai_btn.clicked.connect(self.mash_it_up)
        v.addWidget(self.style)
        v.addWidget(self.ai_btn)
        hint = QLabel("Then change anything you like: drag clips, trim their edges, double-click a lane to add one.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#8b93a1")
        v.addWidget(hint)
        top.addWidget(ai, 2)
        lay.addLayout(top)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Snap to"))
        self.snap_box = QComboBox()
        for k, t in (("bar", "Bars"), ("beat", "Beats"), ("off", "Off")):
            self.snap_box.addItem(t, k)
        bar.addWidget(self.snap_box)
        zin, zout = QPushButton("＋"), QPushButton("－")
        for b in (zin, zout):
            b.setFixedWidth(36)
        zin.setToolTip("Zoom in (or Ctrl + mouse wheel)")
        zout.setToolTip("Zoom out")
        bar.addWidget(zout)
        bar.addWidget(zin)
        self.time_label = QLabel()
        bar.addWidget(self.time_label, 1)
        lay.addLayout(bar)

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        hl = QHBoxLayout(left)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(0)
        self.labels = LaneLabels(self)
        self.timeline = MashupTimeline(self)
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.timeline)
        self.scroll.setWidgetResizable(False)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lv = QVBoxLayout()
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(self.labels)
        lv.addStretch(1)
        hl.addLayout(lv)
        hl.addWidget(self.scroll, 1)
        self.labels.setFixedHeight(RULER_H + len(mm.LANES) * LANE_H + 4)
        left.setMinimumHeight(RULER_H + len(mm.LANES) * LANE_H + 24)
        split.addWidget(left)
        zin.clicked.connect(lambda: self.timeline.zoom(1.4))
        zout.clicked.connect(lambda: self.timeline.zoom(1 / 1.4))
        self.timeline.selected.connect(lambda _c: self._fill_inspector())
        self.timeline.seek.connect(self.seek)

        insp = QGroupBox("Clip")
        fl = QFormLayout(insp)
        self.c_title = QLabel("Click a clip to change it")
        self.c_title.setWordWrap(True)
        self.c_start = QDoubleSpinBox()
        self.c_start.setRange(1, 100000)
        self.c_start.setDecimals(2)
        self.c_start.setToolTip("Where the clip starts on the timeline, in bars (bar 1 = the start)")
        self.c_src = QDoubleSpinBox()
        self.c_src.setRange(0, 100000)
        self.c_src.setDecimals(2)
        self.c_src.setSuffix(" s")
        self.c_src.setToolTip("Where in the song the clip starts playing from")
        self.c_len = QDoubleSpinBox()
        self.c_len.setRange(0.05, 10000)
        self.c_len.setDecimals(2)
        self.c_len.setSuffix(" bars")
        self.c_gain = QDoubleSpinBox()
        self.c_gain.setRange(-40, 12)
        self.c_gain.setDecimals(1)
        self.c_gain.setSuffix(" dB")
        self.c_fin = QDoubleSpinBox()
        self.c_fin.setRange(0, 256)
        self.c_fin.setDecimals(2)
        self.c_fin.setSuffix(" beats")
        self.c_fout = QDoubleSpinBox()
        self.c_fout.setRange(0, 256)
        self.c_fout.setDecimals(2)
        self.c_fout.setSuffix(" beats")
        self.c_mute = QCheckBox("Muted")
        fl.addRow(self.c_title)
        fl.addRow("Starts at bar", self.c_start)
        fl.addRow("Plays the song from", self.c_src)
        fl.addRow("Length", self.c_len)
        fl.addRow("Volume", self.c_gain)
        fl.addRow("Fade in", self.c_fin)
        fl.addRow("Fade out", self.c_fout)
        fl.addRow(self.c_mute)
        brow = QHBoxLayout()
        self.b_split = QPushButton("Split at playhead")
        self.b_dup = QPushButton("Duplicate")
        self.b_del = QPushButton("Delete")
        for b in (self.b_split, self.b_dup, self.b_del):
            brow.addWidget(b)
        fl.addRow(brow)
        self.b_split.clicked.connect(self.split_clip)
        self.b_dup.clicked.connect(self.duplicate_clip)
        self.b_del.clicked.connect(self.delete_clip)
        for w in (self.c_start, self.c_src, self.c_len, self.c_gain, self.c_fin, self.c_fout):
            w.editingFinished.connect(self._apply_inspector)
        self.c_mute.toggled.connect(lambda _on: self._apply_inspector())
        insp.setMinimumWidth(300)
        split.addWidget(insp)
        split.setStretchFactor(0, 1)
        lay.addWidget(split, 1)
        self.statusBar().showMessage("Pick two songs, split them into stems, then press Mash it up - or build it yourself.")

    # =============================================================== state
    def song_names(self) -> list[str]:
        out = []
        for s in self.m.songs:
            an = self.lib.get(s.song_id)
            out.append((an.title or Path(s.path).stem) if an else "(no song)")
        return out

    def snap(self) -> str:
        return self.snap_box.currentData()

    def snapshot(self) -> dict:
        return copy.deepcopy(self.m.to_dict())

    def edited(self, before: dict | None = None):
        """Something changed: remember the state before it for Undo, and redraw."""
        if before is not None:
            self._undo.append(before)
            del self._undo[:-200]
            self._redo.clear()
        self.dirty = True
        self._render_path = None
        self.refresh()

    def _set(self, fn):
        if self._busy:
            return
        before = self.snapshot()
        fn(self.m)
        self.edited(before)

    def undo(self):
        if self._undo:
            self._redo.append(self.snapshot())
            self.m = mm.Mashup.from_dict(self._undo.pop())
            self.edited()

    def redo(self):
        if self._redo:
            self._undo.append(self.snapshot())
            self.m = mm.Mashup.from_dict(self._redo.pop())
            self.edited()

    def refresh(self):
        self._busy = True
        try:
            m, lib = self.m, self.lib
            items = sorted(((an.title or Path(self.paths.get(sid, sid)).stem) + (f" - {an.artist}" if an.artist else ""), sid)
                           for sid, an in lib.items() if sid in self.paths)
            for i, cb in enumerate(self.song_combo):
                cb.clear()
                cb.addItem("(choose a song)", "")
                for name, sid in items:
                    cb.addItem(name, sid)
                cb.setCurrentIndex(max(0, cb.findData(m.songs[i].song_id)))
                an = lib.get(m.songs[i].song_id)
                if an:
                    r, p = mm.rate(m, lib, i), mm.pitch(m, lib, i)
                    txt = f"{an.bpm:.1f} BPM" + (f" → {an.bpm * r:.1f}" if abs(r - 1) > 1e-4 else "")
                    txt += f"  ·  {an.key_name}" + (f" → {mm.key_after(m, lib, i)} ({p:+d})" if p else "")
                    self.song_info[i].setText(txt)
                else:
                    self.song_info[i].setText("")
            todo = self._unsplit()
            if not m.ready():
                self.stems_label.setText("Choose two songs.")
            elif todo:
                self.stems_label.setText(f"{len(todo)} of the songs still need splitting into stems.")
            else:
                self.stems_label.setText("Both songs are split into stems.")
            self.split_all.setEnabled(bool(todo))
            self.beat.setChecked(m.beat_match)
            self.tempo_from.setCurrentIndex(self.tempo_from.findData(m.tempo_from))
            self.bpm.setValue(mm.tempo(m, lib) if m.ready() and m.tempo_from != "custom" else m.custom_bpm)
            self.bpm.setEnabled(m.tempo_from == "custom")
            self.tempo_from.setEnabled(m.beat_match)
            self.key.setChecked(m.key_match)
            self.key_from.setCurrentIndex(self.key_from.findData(m.key_from))
            self.key_from.setEnabled(m.key_match)
            for i in (0, 1):
                self.pitch[i].setValue(-13 if m.songs[i].pitch is None else m.songs[i].pitch)
            self.vlevel.setCurrentIndex(self.vlevel.findData(m.vocal_level))
            self.vlufs.setValue(m.vocal_lufs)
            self.vlufs.setEnabled(m.vocal_level != "off")
            self._load_waves()
            ok = m.ready()
            for w in (self.ai_btn, self.a_play, self.a_export, self.a_tomix):
                w.setEnabled(ok)
            self.a_undo.setEnabled(bool(self._undo))
            self.a_redo.setEnabled(bool(self._redo))
            self.setWindowTitle(f"Mashup Studio - {m.name}{' *' if self.dirty else ''}")
            if self.timeline.sel and m.clip(self.timeline.sel) is None:
                self.timeline.sel = None
            self.timeline.relayout()
            self.labels.update()
            self._fill_inspector()
            self._show_time()
        finally:
            self._busy = False

    def _load_waves(self):
        """Work out the stems' waveforms in the background (once per song), then redraw."""
        for s in self.m.songs:
            sid = s.song_id
            if not sid or sid in self.waves or sid in self._wave_jobs or not stems.cached(sid):
                continue
            self._wave_jobs.add(sid)

            def work(sid=sid):
                try:
                    self.waves[sid] = mm.stem_waves(sid)
                except Exception:  # noqa: BLE001 - a picture we can do without
                    self.waves[sid] = {}
                self._waves_new = True
            threading.Thread(target=work, daemon=True).start()

    def _unsplit(self) -> list[str]:
        return [s.song_id for s in self.m.songs if s.song_id and not stems.cached(s.song_id)]

    def _show_time(self):
        t = self.timeline.playhead
        total = mm.length(self.m, self.lib) if self.m.ready() else 0.0
        extra = ""
        if self.m.ready():
            bar = mm.bar_seconds(self.m, self.lib)
            extra = f"   ·   bar {int(t // bar) + 1}   ·   {mm.tempo(self.m, self.lib):.1f} BPM"
        self.time_label.setText(f"  {fmt_time(t)} / {fmt_time(total)}{extra}")

    # ================================================================ songs
    def _combo_changed(self, i):
        if self._busy:
            return
        self._set_song(i, self.song_combo[i].currentData() or "")

    def _set_song(self, i: int, sid: str, record: bool = True):
        m = self.m
        if m.songs[i].song_id == sid:
            return
        before = self.snapshot()
        mine = [c for c in m.clips if c.song == i]
        m.clips[:] = [c for c in m.clips if c.song != i]                   # the old song's clips go with it
        m.songs[i] = mm.MashupSong(self.paths.get(sid, ""), sid) if sid else mm.MashupSong()
        if m.name == "Untitled mashup" and m.ready():
            m.name = " x ".join(self.song_names())
        self.edited(before if record else None)
        if mine and record:
            self.statusBar().showMessage(f"Song {'AB'[i]} changed: its {len(mine)} clips were removed (Undo brings them back).", 8000)

    def choose_file(self, i: int):
        f, _ = QFileDialog.getOpenFileName(self, "Choose a song", str(self.settings.value("last_dir", "")), AUDIO_FILTER)
        if not f:
            return
        self.settings.setValue("last_dir", str(Path(f).parent))
        self.add_song_files([f], then=lambda ids: ids and self._set_song(i, ids[0]))

    def add_song_files(self, files, then=None):
        from ..engine import analyze_library

        def job(cb, cancel):
            return analyze_library([Path(f) for f in files], progress=cb)

        def done(res):
            lib, paths, errors = res
            self.lib.update(lib)
            self.paths.update(paths)
            if errors:
                QMessageBox.warning(self, APP, "Couldn't read:\n" + "\n".join(errors))
            self.refresh()
            if then:
                then(list(lib))
        self.run_task("Analysing…", job, done)

    def split_songs(self, then=None):
        todo = self._unsplit()
        if not todo:
            if then:
                then()
            return
        if not stems.available():
            QMessageBox.information(self, APP, stems.INSTALL_HINT)
            return
        lib, paths = self.lib, self.paths

        def job(cb, cancel):
            for k, sid in enumerate(todo):
                name = lib[sid].title or Path(paths[sid]).name
                stems.split(paths[sid], sid, cancel=cancel,
                            progress=lambda f, k=k, name=name: cb(f"Splitting {name} into stems ({k + 1}/{len(todo)})…", (k + f) / len(todo)))
                stems.lag(sid, paths[sid])
            return True

        def done(_r):
            self.refresh()
            self.statusBar().showMessage("Split into stems.", 5000)
            if then:
                then()
        self.run_task("Splitting into stems…", job, done)

    # ================================================================== AI
    def mash_it_up(self):
        if not self.m.ready():
            return
        if self._unsplit():
            self.split_songs(then=self.mash_it_up)
            return
        before = self.snapshot()
        style = self.style.currentData()
        try:
            used = mm.auto_mashup(self.m, self.lib, style)
        except mm.MashupError as e:
            QMessageBox.warning(self, APP, str(e))
            return
        self.edited(before)
        self.seek(0.0)
        msg = mm.STYLES[used]
        self.statusBar().showMessage(f"Mashed up: {msg.lower() if style != 'auto' else 'the AI chose “' + msg + '”'}. "
                                     "Press Play to hear it.", 10000)

    # ================================================================ clips
    def _sel(self):
        return self.m.clip(self.timeline.sel) if self.timeline.sel else None

    def add_clip(self, lane: int, t: float):
        if not self.m.ready():
            return
        song, stem = mm.LANES[lane]
        before = self.snapshot()
        c = mm.add_clip(self.m, self.lib, song, stem, t)
        self.timeline.sel = c.id
        self.edited(before)

    def add_whole_song(self, song: int, t: float):
        before = self.snapshot()
        mm.full_song(self.m, self.lib, song, t)
        self.edited(before)

    def split_clip(self):
        c = self._sel()
        if c is None:
            return
        before = self.snapshot()
        if mm.split_clip(self.m, self.lib, c.id, self.timeline.playhead) is None:
            self.statusBar().showMessage("Put the playhead inside the clip to split it there.", 5000)
            return
        self.edited(before)

    def duplicate_clip(self):
        c = self._sel()
        if c is None:
            return
        before = self.snapshot()
        d = mm.duplicate_clip(self.m, self.lib, c.id)
        self.timeline.sel = d.id
        self.edited(before)

    def toggle_mute(self):
        c = self._sel()
        if c is not None:
            self._set(lambda m: setattr(m.clip(c.id), "muted", not c.muted))

    def delete_clip(self):
        c = self._sel()
        if c is None:
            return
        before = self.snapshot()
        self.m.clips.remove(c)
        self.timeline.sel = None
        self.edited(before)

    def _fill_inspector(self):
        c = self._sel()
        ws = (self.c_start, self.c_src, self.c_len, self.c_gain, self.c_fin, self.c_fout, self.c_mute,
              self.b_split, self.b_dup, self.b_del)
        for w in ws:
            w.setEnabled(c is not None)
        if c is None:
            self.c_title.setText("Click a clip to change it")
            return
        m, lib = self.m, self.lib
        bar = mm.bar_seconds(m, lib)
        beat = bar / 4
        old = self._busy
        self._busy = True
        try:
            self.c_title.setText(f"<b>Song {'AB'[c.song]} - {c.stem}</b><br>{self.song_names()[c.song]}")
            self.c_start.setValue(c.start / bar + 1)
            self.c_src.setValue(c.src_start)
            self.c_len.setValue(mm.clip_length(m, lib, c) / bar)
            self.c_gain.setValue(c.gain_db)
            self.c_fin.setValue(c.fade_in / beat)
            self.c_fout.setValue(c.fade_out / beat)
            self.c_mute.setChecked(c.muted)
        finally:
            self._busy = old

    def _apply_inspector(self):
        c = self._sel()
        if c is None or self._busy:
            return
        m, lib = self.m, self.lib
        bar = mm.bar_seconds(m, lib)
        beat = bar / 4
        r = mm.rate(m, lib, c.song)
        dur = lib[m.songs[c.song].song_id].duration
        new = dict(start=max(0.0, (self.c_start.value() - 1) * bar), src_start=min(self.c_src.value(), dur - 0.05),
                   gain_db=self.c_gain.value(), fade_in=self.c_fin.value() * beat, fade_out=self.c_fout.value() * beat,
                   muted=self.c_mute.isChecked())
        new["src_end"] = min(dur, new["src_start"] + self.c_len.value() * bar * r)
        if all(abs(getattr(c, k) - v) < 1e-6 if isinstance(v, float) else getattr(c, k) == v for k, v in new.items()):
            return
        before = self.snapshot()
        for k, v in new.items():
            setattr(c, k, v)
        self.edited(before)

    # ============================================================= playback
    def seek(self, t: float):
        self.timeline.playhead = max(0.0, t)
        if self.player.loaded:
            self.player.seek(self.timeline.playhead)
        self.timeline.update()
        self._show_time()

    def _tick(self):
        if self._waves_new:
            self._waves_new = False
            self.timeline.update()
        if self.player.playing:
            self.timeline.playhead = self.player.position()
            self.timeline.update()
            self._show_time()
            x = self.timeline.x_of(self.timeline.playhead)
            sb = self.scroll.horizontalScrollBar()
            if not (sb.value() <= x <= sb.value() + self.scroll.viewport().width() - 40):
                sb.setValue(int(max(0, x - 80)))
        self.a_play.setText("❚❚ Pause" if self.player.playing else "▶ Play")

    def toggle_play(self):
        if self.player.playing:
            self.player.pause()
            return
        if not self.m.ready() or not self.m.clips:
            self.statusBar().showMessage("Nothing to play yet: press Mash it up, or double-click a lane to add a clip.", 6000)
            return
        if self._render_path and Path(self._render_path).exists():
            self._play(self._render_path)
            return
        if self._unsplit():
            self.split_songs(then=self.toggle_play)
            return
        self._render_n += 1
        out = self.tmp / f"preview_{self._render_n}.wav"
        m, lib, paths, rd = mm.Mashup.from_dict(self.snapshot()), self.lib, self.paths, self.renderer

        def job(cb, cancel):
            import soundfile as sf
            audio = rd.render(m, lib, paths, progress=cb)
            sf.write(str(out), audio.T, SR, subtype="PCM_16")
            return str(out)

        def done(path):
            self._render_path = path
            self._play(path)
        self.run_task("Getting the mashup ready…", job, done, self._failed)

    def _failed(self, msg):
        QMessageBox.warning(self, APP, msg)
        return True

    def _play(self, path):
        try:
            ok = self.player.load(path, self.timeline.playhead) and self.player.play()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, APP, f"Couldn't play:\n{e}")
            return
        if not ok:
            QMessageBox.information(self, APP, f"This computer has no audio output available.\n\n{self.player.error}")

    def stop(self):
        self.player.pause()
        self.seek(0.0)

    # ============================================================ files
    def _ask_keep(self) -> bool:
        if not self.dirty or not self.m.clips:
            return True
        b = QMessageBox.question(self, APP, "Save this mashup first?",
                                 QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
                                 QMessageBox.StandardButton.Cancel)
        if b == QMessageBox.StandardButton.Cancel:
            return False
        return self.save() if b == QMessageBox.StandardButton.Save else True

    def new_mashup(self):
        if not self._ask_keep():
            return
        self.player.pause()
        self.m, self.file, self._undo, self._redo = mm.Mashup(), None, [], []
        self.edited()
        self.dirty = False
        self.refresh()

    def save(self) -> bool:
        if self.file is None:
            f, _ = QFileDialog.getSaveFileName(self, "Save mashup", str(Path(self.settings.value("last_dir", "")) / (self.m.name + ".lmmash")), FILTER)
            if not f:
                return False
            self.file = Path(f).with_suffix(".lmmash")
        self.m.save(self.file)
        self.dirty = False
        self.refresh()
        self.statusBar().showMessage(f"Saved {self.file}", 5000)
        return True

    def open_mashup(self, path=None):
        if not self._ask_keep():
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Open mashup", str(self.settings.value("last_dir", "")), FILTER)
            if not path:
                return
        try:
            m = mm.Mashup.load(path)
        except mm.MashupError as e:
            QMessageBox.warning(self, APP, str(e))
            return
        need = [s.path for s in m.songs if s.song_id and s.song_id not in self.lib]
        missing = [p for p in need if not Path(p).exists()]
        if missing:
            QMessageBox.warning(self, APP, "These songs weren't found:\n" + "\n".join(missing))
            return

        def use(_ids=None):
            for s in m.songs:                                   # the songs may have moved since
                if s.song_id in self.paths:
                    s.path = self.paths[s.song_id]
            self.player.pause()
            self.m, self.file, self._undo, self._redo = m, Path(path), [], []
            self._render_path = None
            self.dirty = False
            self.refresh()
        if need:
            self.add_song_files(need, then=use)
        else:
            use()

    def _ask_export(self, title: str):
        f, flt = QFileDialog.getSaveFileName(self, title, str(Path(self.settings.value("last_dir", "")) / (self.m.name + ".wav")),
                                             EXPORT_FILTER)
        if not f:
            return None
        p = Path(f)
        if p.suffix.lower() not in (".wav", ".flac", ".mp3"):
            p = p.with_suffix("." + flt.split("*.")[1].split(")")[0])
        return p

    def export(self, then=None):
        if not self.m.ready() or not self.m.clips:
            return
        out = self._ask_export("Export mashup")
        if out is None:
            return
        self._export_to(out, then)

    def _export_to(self, out: Path, then=None):
        m, lib, paths, rd = mm.Mashup.from_dict(self.snapshot()), self.lib, self.paths, self.renderer

        def job(cb, cancel):
            return mm.export(m, lib, paths, out, progress=cb, renderer=rd)

        def done(res):
            self.statusBar().showMessage(f"Saved {res['audio']} ({fmt_time(res['seconds'])})", 8000)
            if then:
                then(res["audio"])
        self.run_task("Exporting the mashup…", job, done, self._failed)

    def add_to_mix(self):
        if self.main is None or not self.m.ready() or not self.m.clips:
            return
        out = self._ask_export("Save the mashup to add it to the mix")
        if out is None:
            return
        self._export_to(out, then=lambda path: (self.main.add_files([path]),
                                               self.statusBar().showMessage("Added to the mix.", 6000)))

    def closeEvent(self, ev):
        if self.task is not None:
            ev.ignore()
            return
        if not self._ask_keep():
            ev.ignore()
            return
        self.timer.stop()
        self.player.close()
        super().closeEvent(ev)
