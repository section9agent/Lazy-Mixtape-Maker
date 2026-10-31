"""Visualization Studio: put visuals on a mixtape you already have."""
from __future__ import annotations

import dataclasses
import shutil
import tempfile
from pathlib import Path

import numpy as np
from PySide6.QtCore import QRectF, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
                               QMenu, QMessageBox, QPushButton, QRadioButton, QScrollArea, QSplitter, QTableWidget,
                               QTableWidgetItem, QTabWidget, QToolBar, QVBoxLayout, QWidget)

from .. import audio_io, prefs, studio as st
from ..video import MODE_LABELS, MODES, FrameComposer
from ..visuals import ShaderLibrary, make_context
from . import theme
from .panels import ThumbCache, fmt_time
from .player import AudioPlayer
from .shader_manager import ShaderManager
from .tasks import APP, TaskMixin
from .song_info import SongInfoDialog
from .studio_settings import StudioSettingsDialog
from .. import songinfo
from .transition_editor import TransitionEditor
from .workers import FrameWorker

PROJECT_FILTER = "Visualization project (*.lmv)"
AUDIO_FILTER = "Music and video (*.mp3 *.wav *.flac *.m4a *.mp4 *.mkv *.mov *.webm *.avi *.m4v)"
CUE_FILTER = "Cue sheet or track list (*.cue *.txt *.tracklist);;All files (*)"
COLORS = ["#4cc9f0", "#f2a541", "#7fc8a9", "#c77dff", "#ef476f", "#ffd166", "#06d6a0", "#b388eb"]


def clock(sec: float) -> str:
    s = int(max(0, sec))
    return f"{s // 3600}:{(s // 60) % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


# ====================================================================== timeline
class StudioTimeline(QWidget):
    seek = Signal(float)
    selected = Signal(str)
    drag_begin = Signal()
    dragged = Signal(str, float)
    drag_end = Signal()
    add_at = Signal(float)
    delete = Signal(str)
    clip_moved = Signal(str, float)      # (marker uid, new start time of its video)

    WH = 170                             # height of the waveform part
    H = 198                              # plus a lane for the videos placed on songs

    def __init__(self):
        super().__init__()
        self.peaks: np.ndarray | None = None
        self.duration = 0.0
        self.markers: list = []
        self.sel = ""
        self.playhead = 0.0
        self.pps = 4.0
        self._drag = ""
        self.clips: list[dict] = []
        self._cdrag: tuple[str, float] | None = None
        self.setFixedHeight(self.H)
        self.setMouseTracking(True)
        self._resize()

    def _resize(self):
        self.setFixedWidth(max(300, int(self.duration * self.pps) + 40))

    def set_data(self, peaks, duration):
        self.peaks, self.duration = peaks, duration
        self._resize(); self.update()

    def set_zoom(self, pps):
        self.pps = float(min(200.0, max(0.05, pps)))
        self._resize(); self.update()

    def fit_to(self, width):
        if self.duration > 0:
            self.set_zoom(max(0.05, (width - 60) / self.duration))

    def set_markers(self, markers, sel):
        self.markers, self.sel = markers, sel
        self.update()

    def set_clips(self, clips):
        """clips: [{"uid", "start", "end", "label", "color"}] - the videos placed on songs."""
        self.clips = clips
        self.update()

    def set_playhead(self, t):
        self.playhead = t
        self.update()

    def _x(self, t):
        return 20 + t * self.pps

    def _t(self, x):
        return min(max(0.0, (x - 20) / self.pps), self.duration or 0.0)

    def _clip_at(self, x, y):
        if y < self.WH + 2:
            return None
        for c in reversed(self.clips):
            if self._x(c["start"]) <= x <= self._x(c["end"]):
                return c
        return None

    def _marker_at(self, x):
        best, bd = "", 7
        for m in self.markers:
            d = abs(self._x(m.time) - x)
            if d <= bd:
                best, bd = m.uid, d
        return best

    # ------------------------------------------------------------------ paint
    def paintEvent(self, ev):
        p = QPainter(self)
        r = ev.rect()
        p.fillRect(r, QColor("#14161c"))
        mid = self.WH / 2 + 8
        if self.peaks is not None and self.duration > 0:
            n = len(self.peaks)
            p.setPen(QPen(QColor("#4a6fa5")))
            for x in range(max(20, r.left()), min(self.width() - 20, r.right() + 1)):
                i = int(min(n - 1, max(0, (x - 20) / max(1.0, self.duration * self.pps) * n)))
                lo, hi = self.peaks[i]
                p.drawLine(x, int(mid - hi * (self.WH / 2 - 24)), x, int(mid - lo * (self.WH / 2 - 24)) + 1)
        # ruler
        step = next((s for s in (1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800, 3600) if s * self.pps >= 70), 3600)
        p.setPen(QPen(QColor("#8b93a1")))
        t = 0.0
        while t <= self.duration + 0.01:
            x = int(self._x(t))
            if r.left() - 60 <= x <= r.right() + 60:
                p.drawLine(x, 0, x, 6)
                p.drawText(x + 3, 14, clock(t))
            t += step
        # videos placed on songs (drag one to line it up with the music)
        lane = QRectF(0, self.WH + 2, self.width(), self.H - self.WH - 4)
        p.fillRect(lane, QColor("#101218"))
        for c in self.clips:
            x0, x1 = self._x(c["start"]), self._x(c["end"])
            if x1 < r.left() - 20 or x0 > r.right() + 20:
                continue
            col = QColor(c["color"])
            bar = QRectF(x0, lane.top() + 2, max(4.0, x1 - x0), lane.height() - 4)
            sel = c["uid"] == self.sel
            p.fillRect(bar, QColor(col.red(), col.green(), col.blue(), 235 if sel else 150))
            p.setPen(QPen(QColor("#ffffff") if sel else QColor(0, 0, 0, 120), 2 if sel else 1))
            p.drawRect(bar)
            p.setPen(QColor("#000"))
            fm = p.fontMetrics()
            p.drawText(bar.adjusted(5, 0, -3, 0), Qt.AlignmentFlag.AlignVCenter,
                       fm.elidedText("▶ " + c["label"], Qt.TextElideMode.ElideRight, max(10, int(bar.width()) - 8)))
        # markers
        for i, m in enumerate(self.markers):
            x = int(self._x(m.time))
            if not (r.left() - 200 <= x <= r.right() + 200):
                continue
            col = QColor(COLORS[i % len(COLORS)])
            sel = m.uid == self.sel
            p.setPen(QPen(col, 3 if sel else 2))
            p.drawLine(x, 18, x, self.H)
            label = f"{i + 1}. {m.artist + ' - ' if m.artist else ''}{m.title}"
            fm = p.fontMetrics()
            w = min(190, fm.horizontalAdvance(label) + 10)
            box = QRectF(x, 20, w, 18)
            p.fillRect(box, col if sel else QColor(col.red(), col.green(), col.blue(), 170))
            p.setPen(QColor("#000"))
            p.drawText(box.adjusted(5, 0, -3, 0), Qt.AlignmentFlag.AlignVCenter, fm.elidedText(label, Qt.TextElideMode.ElideRight, w - 8))
        # playhead
        x = int(self._x(self.playhead))
        p.setPen(QPen(QColor("#ff4d4d"), 2))
        p.drawLine(x, 0, x, self.H)
        if self.duration <= 0:
            p.setPen(QColor("#8b93a1"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Open an audio file to start")

    # ------------------------------------------------------------------ mouse
    def mousePressEvent(self, e):
        if self.duration <= 0:
            return
        x = e.position().x()
        uid = self._marker_at(x)
        clip = None if uid else self._clip_at(x, e.position().y())
        if e.button() == Qt.MouseButton.LeftButton:
            if clip:
                self.selected.emit(clip["uid"])
                self._cdrag = (clip["uid"], (x - 20) / self.pps - clip["start"])
                self.drag_begin.emit()
            elif uid:
                self.selected.emit(uid)
                self._drag = uid
                self.drag_begin.emit()
            else:
                self.seek.emit(self._t(x))
        elif e.button() == Qt.MouseButton.RightButton:
            menu = QMenu(self)
            if uid:
                self.selected.emit(uid)
                menu.addAction("Remove this marker", lambda: self.delete.emit(uid))
            else:
                t = self._t(x)
                menu.addAction(f"Add a song marker at {clock(t)}", lambda: self.add_at.emit(t))
            menu.exec(e.globalPosition().toPoint())

    def mouseMoveEvent(self, e):
        x = e.position().x()
        if self._cdrag:
            uid, grab = self._cdrag
            self.clip_moved.emit(uid, round((x - 20) / self.pps - grab, 3))
        elif self._drag:
            self.dragged.emit(self._drag, round(self._t(x), 2))
        else:
            over_clip = self._clip_at(x, e.position().y()) is not None and not self._marker_at(x)
            self.setCursor(Qt.CursorShape.SizeHorCursor if (self._marker_at(x) or over_clip) else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, e):
        if self._cdrag:
            self._cdrag = None
            self.drag_end.emit()
        elif self._drag:
            self._drag = ""
            self.drag_end.emit()

    def mouseDoubleClickEvent(self, e):
        if (e.button() == Qt.MouseButton.LeftButton and self.duration > 0 and not self._marker_at(e.position().x())
                and self._clip_at(e.position().x(), e.position().y()) is None):
            self.add_at.emit(self._t(e.position().x()))


# ======================================================================= window
class StudioWindow(TaskMixin, QMainWindow):
    def __init__(self, shaders: ShaderLibrary | None = None, thumbs: ThumbCache | None = None, parent=None):
        super().__init__(parent)
        self.settings = QSettings("LazyMixtapeMaker", "Lazy Mixtape Maker")
        self.shaders = shaders or ShaderLibrary()
        self._own_thumbs = thumbs is None
        self.thumbs = thumbs or ThumbCache(self)
        self.hist = st.StudioHistory(st.StudioProject())
        self.file: Path | None = None
        self.dirty = False
        self._clip_notes: dict[str, str] = {}
        self.sel = ""
        self.peaks = None
        self.mono = None
        self.playback: str | None = None
        self.file_cover: str | None = None
        self.tmp = Path(tempfile.mkdtemp(prefix="lmm_studio_"))
        self._busy = False
        self._preview_dirty = True
        self._last_t = -1.0
        self._comp: FrameComposer | None = None
        self.player = AudioPlayer()
        self.setAcceptDrops(True)
        self.resize(1320, 880)
        self._build_ui()
        self._build_actions()
        self.worker = FrameWorker(480, 270, self)
        self.worker.frame.connect(self._frame)
        self.worker.unavailable.connect(lambda m: self.screen.setText("Live preview needs OpenGL 3.3.\n" + m[:160]))
        self.worker.start()
        self.tick = QTimer(self)
        self.tick.setInterval(40)
        self.tick.timeout.connect(self._on_tick)
        self.tick.start()
        self.refresh(rebuild_lists=True)

    @property
    def project(self) -> st.StudioProject:
        return self.hist.project

    # ------------------------------------------------------------------- UI
    def _build_ui(self):
        # left: the songs
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(8, 8, 4, 4)
        ll.addWidget(QLabel("<b>Songs in the mixtape</b> (where each one starts)"))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Time", "Artist", "Title", "Visual"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().hide()
        h = self.table.horizontalHeader()
        h.setStretchLastSection(True)
        h.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for c, w in enumerate((60, 120, 170)):
            self.table.setColumnWidth(c, w)
        ll.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.b_add = QPushButton("Add marker here")
        self.b_add.setToolTip("Add a song marker at the playhead (M)")
        self.b_del = QPushButton("Remove")
        self.b_cue = QPushButton("Import cue sheet…")
        row.addWidget(self.b_add); row.addWidget(self.b_del); row.addStretch(1); row.addWidget(self.b_cue)
        ll.addLayout(row)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color:#8b93a1")
        ll.addWidget(self.note)

        # middle: preview
        mid = QWidget()
        ml = QVBoxLayout(mid)
        self.screen = QLabel("Open a mixtape to see its video here")
        self.screen.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.screen.setFixedSize(480, 270)
        self.screen.setStyleSheet("background:#0b0b10;border-radius:6px;color:#8b93a1")
        ml.addWidget(self.screen, 0, Qt.AlignmentFlag.AlignHCenter)
        tr = QHBoxLayout()
        self.b_play = QPushButton("▶ Play")
        self.b_play.setFixedWidth(90)
        self.time = QLabel("0:00 / 0:00")
        tr.addWidget(self.b_play); tr.addWidget(self.time); tr.addStretch(1)
        ml.addLayout(tr)
        ml.addStretch(1)

        # right: the selected song + the video settings
        right = QWidget()
        rl = QVBoxLayout(right)
        box = QGroupBox("Selected song")
        f = QFormLayout(box)
        self.f_time = QDoubleSpinBox(); self.f_time.setDecimals(1); self.f_time.setRange(0, 1e5); self.f_time.setSuffix(" s")
        self.f_artist = QLineEdit(); self.f_title = QLineEdit()
        vrow = QHBoxLayout()
        self.f_visual = QComboBox()
        self.b_clip = QPushButton("Import video…")
        self.b_clip.setToolTip("Put a video on this song instead of a visual. It is lined up with the music by sound; you can then move it and change its speed.")
        vrow.addWidget(self.f_visual, 1); vrow.addWidget(self.b_clip)
        cov = QHBoxLayout()
        self.f_cover = QLabel("none"); self.f_cover.setStyleSheet("color:#8b93a1")
        self.b_cover = QPushButton("Choose…"); self.b_nocover = QPushButton("Clear")
        cov.addWidget(self.f_cover, 1); cov.addWidget(self.b_cover); cov.addWidget(self.b_nocover)
        self.b_info = QPushButton("Edit song info (cover, artist, title)…")
        self.b_info.setToolTip("Change this song's cover art, artist and title. It starts with what the song has now; "
                               "Reset goes back to what the audio file says.")
        f.addRow(self.b_info)
        f.addRow("Starts at", self.f_time)
        f.addRow("Artist", self.f_artist)
        f.addRow("Title", self.f_title)
        f.addRow("Cover art", cov)
        f.addRow("Visual", vrow)
        self.f_visual_note = QLabel()
        self.f_visual_note.setWordWrap(True); self.f_visual_note.setStyleSheet("color:#8b93a1")
        f.addRow(self.f_visual_note)
        rl.addWidget(box)
        self.cbox = QGroupBox("Video on this song")
        cl = QVBoxLayout(self.cbox)
        self.c_name = QLabel()
        self.c_name.setWordWrap(True)
        cl.addWidget(self.c_name)
        crow = QHBoxLayout()
        self.b_csync = QPushButton("Line up by sound")
        self.b_csync.setToolTip("Compare the video's sound with this song's music and place it where they match best")
        self.b_creplace = QPushButton("Replace…")
        self.b_cremove = QPushButton("Remove")
        crow.addWidget(self.b_csync); crow.addWidget(self.b_creplace); crow.addWidget(self.b_cremove)
        cl.addLayout(crow)
        self.c_note = QLabel()
        self.c_note.setWordWrap(True); self.c_note.setStyleSheet("color:#8b93a1")
        cl.addWidget(self.c_note)
        cf = QFormLayout()
        self.c_start = QDoubleSpinBox(); self.c_start.setDecimals(3); self.c_start.setSingleStep(0.001)
        self.c_start.setRange(-36000, 360000); self.c_start.setSuffix(" s")
        self.c_start.setToolTip("Where the video's first frame plays on the timeline. Drag the video bar under the waveform, "
                                "or type a time to the millisecond.")
        cf.addRow("Video starts at", self.c_start)
        nudge = QHBoxLayout()
        self.c_nudges = []
        for label, ds in (("−100 ms", -0.1), ("−10 ms", -0.01), ("−1 ms", -0.001), ("+1 ms", 0.001), ("+10 ms", 0.01), ("+100 ms", 0.1)):
            b = QPushButton(label); b.setProperty("ds", ds); b.setMinimumWidth(48)
            nudge.addWidget(b); self.c_nudges.append(b)
        cf.addRow(nudge)
        self.c_speed = QDoubleSpinBox(); self.c_speed.setDecimals(4); self.c_speed.setSingleStep(0.001)
        self.c_speed.setRange(0.1, 4.0); self.c_speed.setValue(1.0); self.c_speed.setSuffix(" ×")
        self.c_speed.setToolTip("Playback speed of the video (1.0000 = normal). Use this when the video drifts out of sync.")
        cf.addRow("Speed", self.c_speed)
        snudge = QHBoxLayout()
        self.c_snudges = []
        for label, ds in (("−0.01", -0.01), ("−0.001", -0.001), ("+0.001", 0.001), ("+0.01", 0.01)):
            b = QPushButton(label); b.setProperty("ds", ds); b.setMinimumWidth(48)
            snudge.addWidget(b); self.c_snudges.append(b)
        self.b_cspeed1 = QPushButton("1.0 ×")
        snudge.addWidget(self.b_cspeed1)
        cf.addRow(snudge)
        self.c_loop = QCheckBox("Loop the video if it is shorter than the song")
        cf.addRow(self.c_loop)
        cl.addLayout(cf)
        mute = QLabel("The video's own sound is muted: only your music is heard.")
        mute.setStyleSheet("color:#8b93a1")
        cl.addWidget(mute)
        self.cbox.setVisible(False)
        rl.addWidget(self.cbox)
        self.tbox = QGroupBox("Transition into this song")
        tl_ = QVBoxLayout(self.tbox)
        self.t_own = TransitionEditor(allow_inherit=True)
        tl_.addWidget(self.t_own)
        rl.addWidget(self.tbox)
        vb = QGroupBox("Video")
        vl = QVBoxLayout(vb)
        self.group = QButtonGroup(self)
        self.radios = {}
        labels = dict(MODE_LABELS)
        labels["per_song"] = "I choose a visual for each song"
        labels["single"] = "One visual for the whole video"
        for m in MODES:
            rb = QRadioButton(labels[m])
            self.group.addButton(rb)
            self.radios[m] = rb
            vl.addWidget(rb)
        self.single = QComboBox()
        vl.addWidget(QLabel("The one visual:"))
        vl.addWidget(self.single)
        self.reroll = QPushButton("Pick different random visuals")
        vl.addWidget(self.reroll)
        f2 = QFormLayout()
        self.blend = QDoubleSpinBox(); self.blend.setRange(0.5, 60); self.blend.setSingleStep(0.5); self.blend.setSuffix(" s")
        self.blend.setToolTip("How long the visuals take to blend into each other at a song change")
        self.res = QComboBox()
        for label, wh in (("1280 × 720 (HD)", (1280, 720)), ("1920 × 1080 (Full HD)", (1920, 1080)),
                          ("854 × 480", (854, 480)), ("1080 × 1080 (square)", (1080, 1080))):
            self.res.addItem(label, wh)
        self.fps = QComboBox()
        for v in (24, 30, 60):
            self.fps.addItem(f"{v} fps", v)
        self.overlay = QCheckBox("Show cover art, artist and title (lower left)")
        f2.addRow("Visual blend", self.blend); f2.addRow("Size", self.res); f2.addRow("Frame rate", self.fps)
        vl.addLayout(f2)
        vl.addWidget(self.overlay)
        self.overlay_note = QLabel()
        self.overlay_note.setWordWrap(True); self.overlay_note.setStyleSheet("color:#ffb454")
        vl.addWidget(self.overlay_note)
        self.use_video = QCheckBox("Use the file's own video as the picture")
        self.use_video.setToolTip("Only for video files: show the video itself instead of a visual (a visual picked for a song still wins).")
        vl.addWidget(self.use_video)
        tb = QGroupBox("Default transition between songs")
        tbl = QVBoxLayout(tb)
        self.t_default = TransitionEditor()
        tbl.addWidget(self.t_default)
        vl.addWidget(tb)
        rl.addWidget(vb)
        rl.addStretch(1)
        scroll_right = QScrollArea()
        scroll_right.setWidgetResizable(True)
        scroll_right.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll_right.setWidget(right)

        top = QSplitter(Qt.Orientation.Horizontal)
        top.addWidget(left); top.addWidget(mid); top.addWidget(scroll_right)
        top.setSizes([430, 520, 380])

        # bottom: timeline + library
        self.timeline = StudioTimeline()
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.timeline)
        self.scroll.setWidgetResizable(False)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setFixedHeight(StudioTimeline.H + 18)
        tl = QWidget()
        tv = QVBoxLayout(tl)
        tv.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.setContentsMargins(8, 4, 8, 0)
        bar.addWidget(QLabel("Click to move the playhead · drag a marker to move it · double-click or right-click to add one"))
        bar.addStretch(1)
        for txt, tip, fn in (("−", "Zoom out", lambda: self.timeline.set_zoom(self.timeline.pps / 1.3)),
                             ("+", "Zoom in", lambda: self.timeline.set_zoom(self.timeline.pps * 1.3)),
                             ("Fit", "Fit the whole file", lambda: self.timeline.fit_to(self.scroll.viewport().width()))):
            b = QPushButton(txt); b.setToolTip(tip); b.setFixedSize(56, 34); b.setStyleSheet("font-size: 18px; padding: 0"); b.clicked.connect(fn); bar.addWidget(b)
        tv.addLayout(bar)
        tv.addWidget(self.scroll)
        tv.addStretch(1)
        self.library = ShaderManager(self.shaders, self.thumbs, "Use for the whole video")
        self.tabs = QTabWidget()
        self.tabs.addTab(tl, "Timeline")
        self.tabs.addTab(self.library, "Shader library")
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(top); split.addWidget(self.tabs)
        split.setSizes([520, 330])
        self.setCentralWidget(split)
        self.info = QLabel()
        self.statusBar().addPermanentWidget(self.info)

        # wiring
        self.table.itemSelectionChanged.connect(self._table_sel)
        self.table.cellDoubleClicked.connect(lambda r, c: self._seek(self._row_marker(r).time) if self._row_marker(r) else None)
        self.b_add.clicked.connect(lambda: self.add_marker(self.timeline.playhead))
        self.b_del.clicked.connect(lambda: self.remove_marker(self.sel))
        self.b_cue.clicked.connect(self.import_cue)
        self.b_play.clicked.connect(self.toggle_play)
        self.timeline.seek.connect(self._seek)
        self.timeline.selected.connect(self.select)
        self.timeline.drag_begin.connect(self.hist.begin_gesture)
        self.timeline.dragged.connect(self._dragged)
        self.timeline.drag_end.connect(self._drag_end)
        self.timeline.add_at.connect(self.add_marker)
        self.timeline.delete.connect(self.remove_marker)
        self.f_time.editingFinished.connect(lambda: self._edit_sel(time=self.f_time.value()))
        self.f_artist.editingFinished.connect(lambda: self._edit_sel(artist=self.f_artist.text()))
        self.f_title.editingFinished.connect(lambda: self._edit_sel(title=self.f_title.text()))
        self.f_visual.activated.connect(self._pick_visual)
        self.b_clip.clicked.connect(self._add_video)
        self.b_creplace.clicked.connect(self._add_video)
        self.b_cremove.clicked.connect(self._remove_video)
        self.b_csync.clicked.connect(self._sync_video)
        self.c_start.editingFinished.connect(lambda: self._clip_set(start=self.c_start.value()))
        self.c_speed.editingFinished.connect(lambda: self._clip_set(speed=self.c_speed.value()))
        self.c_loop.toggled.connect(lambda c: self._clip_set(loop=c))
        for b in self.c_nudges:
            b.clicked.connect(lambda _=False, b=b: self._clip_set(start=round(self.c_start.value() + b.property("ds"), 3)))
        for b in self.c_snudges:
            b.clicked.connect(lambda _=False, b=b: self._clip_set(speed=round(self.c_speed.value() + b.property("ds"), 4)))
        self.b_cspeed1.clicked.connect(lambda: self._clip_set(speed=1.0))
        self.timeline.clip_moved.connect(self._clip_dragged)
        self.t_own.changed.connect(self._own_transition)
        self.t_default.changed.connect(lambda: self._video(transition=self.t_default.value()))
        self.use_video.toggled.connect(lambda c: None if self._busy else self._video(use_video=c))
        self.b_cover.clicked.connect(self._choose_cover)
        self.b_info.clicked.connect(self._song_info)
        self.b_nocover.clicked.connect(lambda: self._edit_sel(cover=""))
        self.group.buttonToggled.connect(self._mode)
        self.single.activated.connect(lambda _: self._video(single_shader=self.single.currentData()))
        self.reroll.clicked.connect(lambda: self._video(seed=self.project.video.seed + 1))
        self.blend.editingFinished.connect(lambda: self._video(blend=self.blend.value()))
        self.res.activated.connect(lambda _: self._video(width=self.res.currentData()[0], height=self.res.currentData()[1]))
        self.fps.activated.connect(lambda _: self._video(fps=self.fps.currentData()))
        self.overlay.toggled.connect(lambda c: None if self._busy else self._video(show_overlay=c))
        self.library.changed.connect(self._library_changed)
        self.library.use_clicked.connect(lambda sid: self._video(single_shader=sid, mode="single"))

    def _build_actions(self):
        def act(text, slot, shortcut=None, glyph=None):
            a = QAction(text, self)
            if glyph:
                a.setIcon(theme.glyph_icon(glyph))
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            return a

        self.a_open = act("Open audio", self.open_audio_dialog, "Ctrl+O", "⏏")
        self.a_open_proj = act("Open project…", self.open_project_dialog, "Ctrl+Shift+O")
        self.a_save = act("Save project", lambda: self.save_project(), "Ctrl+S")
        self.a_save_as = act("Save project as…", lambda: self.save_project(True), "Ctrl+Shift+S")
        self.a_cue = act("Import cue sheet", self.import_cue, "Ctrl+I", "☰")
        self.a_cue_out = act("Save cue sheet…", self.export_cue)
        self.a_export = act("Export video", self.export_video, "Ctrl+E", "▣")
        self.a_undo = act("Undo", lambda: self._history(False), "Ctrl+Z")
        self.a_redo = act("Redo", lambda: self._history(True), "Ctrl+Shift+Z")
        self.a_mark = act("Add marker", lambda: self.add_marker(self.timeline.playhead), "M", "⚑")
        self.a_del = act("Remove selected marker", lambda: self.remove_marker(self.sel), "Delete")
        self.a_play = act("Play / pause", self.toggle_play, "Space", "▶")
        self.a_settings = act("Project settings…", self.project_settings, "Ctrl+Shift+G", "⚙")
        self.a_close = act("Close studio", self.close, "Ctrl+W")
        m = self.menuBar()
        fm = m.addMenu("&File")
        for a in (self.a_open, self.a_open_proj, self.a_save, self.a_save_as, None, self.a_cue, self.a_cue_out, None,
                  self.a_export, None, self.a_close):
            fm.addAction(a) if a else fm.addSeparator()
        em = m.addMenu("&Edit")
        for a in (self.a_undo, self.a_redo, None, self.a_settings, None, self.a_mark, self.a_del):
            em.addAction(a) if a else em.addSeparator()
        tb = QToolBar("Studio")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        tb.setIconSize(QSize(34, 34))
        self.addToolBar(tb)
        for a in (self.a_open, self.a_cue, None, self.a_play, self.a_mark, None, self.a_settings, self.a_export):
            tb.addAction(a) if a else tb.addSeparator()

    # ------------------------------------------------------------- loading
    def open_audio_dialog(self):
        if not self._maybe_save():
            return
        p, _ = QFileDialog.getOpenFileName(self, "Open a mixtape", str(self.settings.value("last_dir", "")), AUDIO_FILTER)
        if p:
            self.settings.setValue("last_dir", str(Path(p).parent))
            self.open_audio(p)

    def open_audio(self, path):
        path = Path(path)
        try:
            proj = st.new_project(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, APP, str(e))
            return
        self.player.pause()
        playback = self.tmp / f"playback_{len(list(self.tmp.glob('playback_*')))}.flac"
        cover = self.tmp / f"cover_{playback.stem}.jpg"

        def job(cb, cancel):
            cb("Reading the waveform…", 0.05)
            peaks, mono = st.overview(path)
            cb("Preparing the audio for playback…", 0.4)
            st.make_playback_copy(path, playback)
            has_cover = audio_io.extract_cover(path, cover)
            return peaks, mono, str(cover) if has_cover else None

        def done(res):
            self.peaks, self.mono, self.file_cover = res
            self.playback = str(playback)
            self.hist.reset(proj)
            self.file, self.dirty, self.sel = None, False, proj.markers[0].uid
            self.timeline.set_data(self.peaks, proj.duration)
            self.player.load(self.playback, 0.0)
            self.refresh(rebuild_lists=True)
            QTimer.singleShot(0, lambda: self.timeline.fit_to(self.scroll.viewport().width()))
            side = next((path.with_suffix(e) for e in (".cue", ".tracklist.txt") if path.with_suffix(e).exists()), None)
            if side and QMessageBox.question(self, APP, f"Found “{side.name}” next to the audio. Use it to mark where the songs change?") \
                    == QMessageBox.StandardButton.Yes:
                self._load_cue(side)

        self.run_task("Opening the mixtape…", job, done)

    def open_project_dialog(self):
        if not self._maybe_save():
            return
        p, _ = QFileDialog.getOpenFileName(self, "Open a project", str(self.settings.value("last_proj_dir", "")), PROJECT_FILTER)
        if p:
            self.open_project(p)

    def open_project(self, path):
        try:
            proj = st.load_project(path, self.shaders)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, APP, f"Couldn't open that project:\n{e}")
            return
        if not Path(proj.audio).is_file():
            d = QFileDialog.getExistingDirectory(self, "The audio file can't be found — choose the folder that has it",
                                                 str(self.settings.value("last_dir", "")))
            if not d or not st.relink_audio(proj, [d]):
                QMessageBox.warning(self, APP, "Couldn't find the audio for this project.")
                return
        self.settings.setValue("last_proj_dir", str(Path(path).parent))
        self.player.pause()
        playback = self.tmp / f"playback_{len(list(self.tmp.glob('playback_*')))}.flac"
        cover = self.tmp / f"cover_{playback.stem}.jpg"

        def job(cb, cancel):
            cb("Reading the waveform…", 0.05)
            peaks, mono = st.overview(proj.audio)
            cb("Preparing the audio for playback…", 0.4)
            st.make_playback_copy(proj.audio, playback)
            return peaks, mono, str(cover) if audio_io.extract_cover(proj.audio, cover) else None

        def done(res):
            self.peaks, self.mono, self.file_cover = res
            self.playback = str(playback)
            self.hist.reset(proj)
            self.file, self.dirty = Path(path), False
            self.sel = proj.markers[0].uid if proj.markers else ""
            self.timeline.set_data(self.peaks, proj.duration)
            self.player.load(self.playback, 0.0)
            self.refresh(rebuild_lists=True)
            QTimer.singleShot(0, lambda: self.timeline.fit_to(self.scroll.viewport().width()))

        self.run_task("Opening the project…", job, done)

    def import_cue(self):
        if not self._has_audio():
            QMessageBox.information(self, APP, "Open an audio file first.")
            return
        p, _ = QFileDialog.getOpenFileName(self, "Import a cue sheet or track list", str(self.settings.value("last_dir", "")), CUE_FILTER)
        if p:
            self._load_cue(p)

    def _load_cue(self, path):
        try:
            rows = st.import_cue_file(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, APP, str(e))
            return
        past = [r for r in rows if r["time"] > self.project.duration + 1]
        if past:
            QMessageBox.information(self, APP, f"{len(past)} entr{'y is' if len(past) == 1 else 'ies are'} later than the end of the audio "
                                               "and were moved to the end. Check that this cue sheet belongs to this file.")
        self._edit(lambda p: p.set_markers(rows))
        self.sel = self.project.markers[0].uid if self.project.markers else ""
        self.statusBar().showMessage(f"{len(rows)} songs marked from {Path(path).name}", 6000)
        self.refresh(rebuild_lists=True)

    def export_cue(self):
        if not self.project.markers:
            return
        d = str(self.settings.value("last_export_dir", ""))
        path, _ = QFileDialog.getSaveFileName(self, "Save cue sheet", str(Path(d) / (self.project.name + ".cue")), "Cue sheet (*.cue)")
        if not path:
            return
        esc = lambda s: s.replace('"', "'")
        lines = ['REM GENERATOR "Lazy Mixtape Maker"', f'TITLE "{esc(self.project.name)}"',
                 f'FILE "{esc(Path(self.project.audio).name)}" WAVE']
        for i, m in enumerate(self.project.markers, 1):
            fr = int(round(m.time * 75))
            lines += [f"  TRACK {i:02d} AUDIO", f'    TITLE "{esc(m.title)}"']
            if m.artist:
                lines.append(f'    PERFORMER "{esc(m.artist)}"')
            lines.append(f"    INDEX 01 {fr // 4500:02d}:{(fr // 75) % 60:02d}:{fr % 75:02d}")
        Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ------------------------------------------------------------- editing
    def _has_audio(self) -> bool:
        return bool(self.project.audio) and self.project.duration > 0

    def _edit(self, fn):
        self.hist.edit(fn)
        self.dirty = True
        self._preview_dirty = True

    def _after(self, rebuild=False):
        self.refresh(rebuild_lists=rebuild)

    def select(self, uid: str):
        if uid != self.sel:
            self.sel = uid
            self.refresh()

    def add_marker(self, t: float):
        if not self._has_audio():
            return
        holder = {}
        self._edit(lambda p: holder.setdefault("m", p.add_marker(t)))
        self.sel = holder["m"].uid
        self._after()

    def remove_marker(self, uid: str):
        if not uid or not self.project.find(uid):
            return
        self._edit(lambda p: p.remove_marker(uid))
        self.sel = self.project.markers[0].uid if self.project.markers else ""
        self._after()

    def _edit_sel(self, **fields):
        if self._busy or not self.sel or not self.project.find(self.sel):
            return
        cur = self.project.find(self.sel)
        if all(getattr(cur, k) == v for k, v in fields.items()):
            return
        self._edit(lambda p: p.update_marker(self.sel, **fields))
        self._after()

    def _dragged(self, uid, t):
        self.project.move_marker(uid, t)
        self.dirty = True
        self._preview_dirty = True
        self.refresh(rebuild_lists=False, light=True)

    def _drag_end(self):
        self.hist.end_gesture()
        self.refresh()

    def project_settings(self):
        """All the project's video settings in one window (the same ones are also in the side panel)."""
        dlg = StudioSettingsDialog(self.project.video, self.shaders, st.has_source_video(self.project), self)
        if dlg.exec():
            ch = dlg.changes()
            mode = ch.pop("mode", None)
            if mode == "per_song" and self.project.video.mode != "per_song":
                resolved = dict(st.resolved_visuals(self.project, self.shaders, self.project.duration))

                def fn(p):                            # "I choose per song" starts from what is shown now
                    for mk in p.markers:
                        if not st.has_source_video(p):
                            mk.shader = mk.shader or resolved.get(mk.uid, "")
                    for k, v in ch.items():
                        setattr(p.video, k, v)
                    p.video.mode = "per_song"
                self._edit(fn)
                self._after()
            elif mode or ch:
                if mode:
                    ch["mode"] = mode
                self._video(**ch)

    def _song_info(self):
        """The same song-info dialog as the mix window. The file's own information belongs to the first song."""
        m = self.project.find(self.sel) if self.sel else None
        if m is None:
            return
        first = self.project.markers[0].uid == m.uid
        tags = songinfo.file_info(self.project.audio) if first and self.project.audio and Path(self.project.audio).exists() \
            else {"artist": "", "title": ""}
        fc = self.file_cover if first else None
        cur = None if m.cover == "none" else (m.cover if m.cover and Path(m.cover).is_file() else fc)
        dlg = SongInfoDialog(m.artist, m.title, cur, tags["artist"], tags["title"], fc, self, "",
                             str(self.settings.value("last_dir", "")))
        if not dlg.exec():
            return
        v = dlg.values()
        cover = {"keep": m.cover, "file": "", "none": "none"}.get(v["cover"], v["cover"])
        self._edit_sel(artist=v["artist"], title=v["title"], cover=cover)

    def _choose_cover(self):
        if not self.sel:
            return
        p, _ = QFileDialog.getOpenFileName(self, "Cover art for this song", str(self.settings.value("last_dir", "")),
                                           "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if p:
            self._edit_sel(cover=p)

    def _pick_visual(self, _):
        sid = self.f_visual.currentData()
        if not self.sel or not sid:
            return
        uid = self.sel
        resolved = dict(st.resolved_visuals(self.project, self.shaders, self.project.duration))

        def fn(p):
            m = p.find(uid)
            if sid == "@clip":                       # back to the video placed on this song
                p.set_clip(uid, off=False)
                return
            if sid == "@video":                      # back to the audio file's own picture
                m.shader = ""
                if m.clip:
                    p.set_clip(uid, off=True)
                return
            if p.video.mode != "per_song":
                for mk in p.markers:
                    if not st.has_source_video(p):        # a video file keeps its own picture unless you pick a visual
                        mk.shader = resolved.get(mk.uid, mk.shader)
                p.video.mode = "per_song"
            m.shader = sid
            if m.clip:
                p.set_clip(uid, off=True)             # a visual replaces the video; the video is kept to switch back to
        self._edit(fn)
        self._after()

    def _fill_visual_combo(self, m):
        """The Visual list for a song: its own video choices first (when it has any), then every visual."""
        c = self.f_visual
        c.blockSignals(True)
        c.clear()
        if m is not None and m.clip.get("path"):
            c.addItem("▶ Video: " + Path(m.clip["path"]).name, "@clip")
        if st.has_source_video(self.project):
            c.addItem("▶ The file's own video", "@video")
        for sh in self.shaders.all():
            c.addItem(sh.name, sh.id)
        c.blockSignals(False)

    def _add_video(self):
        """Put a video on the selected song, then line it up with that song's music by sound."""
        if not self.sel:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Video for this song", str(self.settings.value("last_dir", "")),
                                              "Video (*.mp4 *.mkv *.mov *.webm *.avi *.m4v)")
        if not path:
            return
        self.settings.setValue("last_dir", str(Path(path).parent))
        uid = self.sel
        self._edit(lambda p: p.set_clip(uid, path))
        self._after()
        self._sync_video()

    def _remove_video(self):
        if not self.sel:
            return
        uid = self.sel
        self._edit(lambda p: p.clear_clip(uid))
        self._clip_notes.pop(uid, None)
        self._after()

    def _sync_video(self):
        m = self.project.find(self.sel)
        if not m or not m.clip.get("path"):
            return
        uid, path, audio = m.uid, m.clip["path"], self.project.audio
        t0, t1 = st.segment_bounds(self.project, uid)

        def job(cb, cancel):
            from .. import videosync
            return videosync.estimate_offset(audio, t0, t1, path, cb)

        def done(res):
            self._clip_notes[uid] = res.note
            if res.found and self.project.find(uid) and self.project.find(uid).clip.get("path") == path:
                self._edit(lambda p: p.set_clip(uid, start=t0 + res.offset))
            self._after()

        self.run_task("Lining the video up with the music…", job, done)

    def _clip_set(self, **fields):
        if self._busy or not self.sel:
            return
        m = self.project.find(self.sel)
        if not m or not m.clip:
            return
        if all(abs(float(m.clip.get(k, 0)) - float(v)) < 1e-9 for k, v in fields.items()):
            return
        uid = self.sel
        self._edit(lambda p: p.set_clip(uid, **fields))
        self._after()

    def _clip_dragged(self, uid, start):
        m = self.project.find(uid)
        if not m or not m.clip:
            return
        m.clip["start"] = float(start)
        self.dirty = True
        self._preview_dirty = True
        self._comp = None
        self._push_clips()
        self._busy = True
        self.c_start.setValue(float(start))
        self._busy = False

    def _push_clips(self):
        p = self.project
        out = []
        for i, m in enumerate(p.markers):
            ext = st.clip_extent(m)
            if not ext:
                continue
            start, end = ext
            if m.clip.get("loop") or end <= start:
                end = max(end, st.segment_bounds(p, m.uid)[1])
            out.append({"uid": m.uid, "start": start, "end": end, "label": Path(m.clip["path"]).name,
                        "color": COLORS[i % len(COLORS)]})
        self.timeline.set_clips(out)

    def _own_transition(self):
        if self._busy or not self.sel:
            return
        uid, val = self.sel, self.t_own.value()

        def fn(pr):
            if val is None:
                pr.video.transitions.pop(uid, None)
            else:
                pr.video.transitions[uid] = val
        self._edit(fn)
        self._after()

    def _video(self, **fields):
        if self._busy:
            return
        self._edit(lambda p: [setattr(p.video, k, v) for k, v in fields.items()])
        self._after()

    def _mode(self, btn, checked):
        if self._busy or not checked:
            return
        m = next(k for k, r in self.radios.items() if r is btn)
        if m == "per_song" and self.project.video.mode != "per_song":
            resolved = dict(st.resolved_visuals(self.project, self.shaders, self.project.duration))

            def fn(p):
                for mk in p.markers:
                    if not st.has_source_video(p):
                        mk.shader = mk.shader or resolved.get(mk.uid, "")
                p.video.mode = "per_song"
            self._edit(fn)
            self._after()
        else:
            self._video(mode=m)

    def _library_changed(self):
        self._preview_dirty = True
        self.refresh(rebuild_lists=True)

    def _history(self, redo: bool):
        (self.hist.redo if redo else self.hist.undo)()
        self.dirty = True
        self._preview_dirty = True
        if not self.project.find(self.sel):
            self.sel = self.project.markers[0].uid if self.project.markers else ""
        self.refresh(rebuild_lists=True)

    # -------------------------------------------------------------- refresh
    def _row_marker(self, row):
        ms = self.project.markers
        return ms[row] if 0 <= row < len(ms) else None

    def _table_sel(self):
        if self._busy:
            return
        rows = self.table.selectionModel().selectedRows()
        if rows:
            m = self._row_marker(rows[0].row())
            if m:
                self.select(m.uid)

    def refresh(self, rebuild_lists: bool = False, light: bool = False):
        p = self.project
        self._busy = True
        try:
            has = self._has_audio()
            self.timeline.set_markers(p.markers, self.sel)
            self._push_clips()
            if light:
                return
            resolved = dict(st.resolved_visuals(p, self.shaders, p.duration)) if has else {}
            names = {s.id: s.name for s in self.shaders.all()}
            labels = st.visual_labels(p, self.shaders) if has else {}
            self.table.setRowCount(len(p.markers))
            for r, m in enumerate(p.markers):
                vals = [clock(m.time), m.artist, m.title, labels.get(m.uid) or names.get(resolved.get(m.uid, ""), "")]
                for c, v in enumerate(vals):
                    self.table.setItem(r, c, QTableWidgetItem(v))
                if m.uid == self.sel:
                    self.table.selectRow(r)
            first = p.markers[0].time if p.markers else 0
            self.note.setText(f"Before the first marker the video shows “{p.file_title or p.name}”." if has and first > 1 else "")
            m = p.find(self.sel)
            for w in (self.f_time, self.f_artist, self.f_title, self.f_visual, self.b_clip, self.b_cover, self.b_nocover, self.b_del, self.b_info):
                w.setEnabled(m is not None)
            if rebuild_lists:
                self.single.clear()
                for sh in self.shaders.all():
                    self.single.addItem(sh.name, sh.id)
                self.library.rebuild()
            if m:
                first_marker = bool(p.markers) and p.markers[0].uid == m.uid
                self.f_time.setMaximum(max(1.0, p.duration))
                self.f_time.setValue(m.time)
                self.f_artist.setText(m.artist); self.f_title.setText(m.title)
                self.f_cover.setText("none" if m.cover == "none" else Path(m.cover).name if m.cover else ("file's cover" if first_marker and self.file_cover else "none"))
                self._fill_visual_combo(m)
                lab = labels.get(m.uid, "")
                shown = "@clip" if st.clip_active(m) else ("@video" if lab.startswith("Source video") else resolved.get(m.uid, ""))
                self.f_visual.blockSignals(True)
                self.f_visual.setCurrentIndex(max(0, self.f_visual.findData(shown)))
                self.f_visual.blockSignals(False)
                has_clip = bool(m.clip.get("path"))
                self.cbox.setVisible(has_clip)
                if has_clip:
                    self.c_name.setText("<b>" + Path(m.clip["path"]).name + "</b>"
                                        + ("" if Path(m.clip["path"]).is_file() else "  - file not found"))
                    self.c_start.setValue(float(m.clip.get("start", m.time)))
                    self.c_speed.setValue(float(m.clip.get("speed", 1.0)))
                    self.c_loop.setChecked(bool(m.clip.get("loop")))
                    self.c_note.setText(self._clip_notes.get(m.uid, "") if st.clip_active(m) else
                                        "Not shown right now: a visual is chosen for this song. Pick “▶ Video” in the Visual list to use it again.")
                self.f_visual_note.setText(lab if lab.startswith(("Source video", "Clip:", "Video:")) else "")
                first = bool(p.markers) and p.markers[0].uid == m.uid
                self.tbox.setEnabled(not first)
                self.t_own.set_value(None if first else p.video.transitions.get(m.uid))
            else:
                self.cbox.setVisible(False)
                self.f_artist.clear(); self.f_title.clear(); self.f_cover.setText("none")
            v = p.video
            self.radios[v.mode].setChecked(True)
            self.single.setCurrentIndex(max(0, self.single.findData(v.single_shader)))
            self.single.setEnabled(v.mode == "single")
            self.reroll.setEnabled(v.mode in ("random", "auto"))
            self.blend.setValue(v.blend)
            self.t_default.set_value(v.transition)
            self.use_video.setVisible(st.has_source_video(p))
            self.use_video.setChecked(v.use_video)
            self.res.setCurrentIndex(max(0, self.res.findData((v.width, v.height))))
            self.fps.setCurrentIndex(max(0, self.fps.findData(v.fps)))
            self.overlay.setChecked(v.show_overlay)
            self.overlay_note.setText("" if prefs.overlay_enabled() else
                                      "The card is switched off for every video in the main window's Settings menu.")
            for a in (self.a_save, self.a_save_as, self.a_cue_out, self.a_export, self.a_play, self.a_mark, self.a_cue):
                a.setEnabled(has)
            self.a_del.setEnabled(m is not None)
            self.a_undo.setEnabled(self.hist.can_undo())
            self.a_redo.setEnabled(self.hist.can_redo())
            self.b_add.setEnabled(has); self.b_cue.setEnabled(has); self.b_play.setEnabled(has)
            self.info.setText(f"{len(p.markers)} songs  ·  {clock(p.duration)}   " if has else "")
            self.setWindowTitle(f"{(self.file.name if self.file else p.name) + (' *' if self.dirty else '')} — Visualization Studio")
            self._comp = None
            self._preview_dirty = True
        finally:
            self._busy = False

    # -------------------------------------------------------------- playback
    def _seek(self, t: float):
        self.timeline.set_playhead(t)
        if self.player.loaded:
            self.player.seek(t)
        self._preview_dirty = True

    def toggle_play(self):
        if not self._has_audio() or not self.player.loaded:
            return
        if self.player.playing:
            self.player.pause()
            self.b_play.setText("▶ Play")
        else:
            self.player.seek(self.timeline.playhead)
            if not self.player.play():
                QMessageBox.information(self, APP, "This computer has no audio output available for playback.\n\n" + self.player.error)
            else:
                self.b_play.setText("❚❚ Pause")

    def _on_tick(self):
        if not self._has_audio():
            return
        playing = self.player.playing
        if playing:
            t = self.player.position()
            self.timeline.set_playhead(t)
            x = int(t * self.timeline.pps + 20)
            self.scroll.ensureVisible(x, 10, 160, 0)
        elif self.player.ended:
            self.player.ended = False
            self.b_play.setText("▶ Play")
            self.timeline.set_playhead(0.0)
            self.player.seek(0.0)
        t = self.timeline.playhead
        self.time.setText(f"{clock(t)} / {clock(self.project.duration)}")
        if playing or self._preview_dirty or t != self._last_t:
            self._submit_frame(t)
            self._last_t = t
            self._preview_dirty = False

    def _composer(self) -> FrameComposer | None:
        if self._comp is None and self._has_audio():
            p = self.project
            segs, wins = st.build_segments(p, self.shaders, p.duration,
                                           (self.mono, st.OVERVIEW_SR) if self.mono is not None else None, self.file_cover)
            self._comp = FrameComposer(segs, wins, p.duration, p.video, self.shaders)
        return self._comp

    def _submit_frame(self, t):
        comp = self._composer()
        if comp is None:
            return
        k = int(t * 30)
        self.worker.submit(lambda r: comp.draw(r, t, k))

    def _frame(self, img, _tag):
        self.screen.setPixmap(QPixmap.fromImage(img))

    # -------------------------------------------------------------- saving
    def _maybe_save(self) -> bool:
        if not self.dirty or not self._has_audio():
            return True
        b = QMessageBox.question(self, APP, "Save changes to this project first?",
                                 QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
                                 QMessageBox.StandardButton.Cancel)
        if b == QMessageBox.StandardButton.Cancel:
            return False
        if b == QMessageBox.StandardButton.Save:
            return self.save_project()
        return True

    def save_project(self, save_as: bool = False) -> bool:
        if not self._has_audio():
            return False
        path = self.file
        if save_as is True or path is None:
            d = str(self.settings.value("last_proj_dir", str(Path(self.project.audio).parent)))
            p, _ = QFileDialog.getSaveFileName(self, "Save project", str(Path(d) / (self.project.name + ".lmv")), PROJECT_FILTER)
            if not p:
                return False
            path = Path(p).with_suffix(".lmv")
            self.settings.setValue("last_proj_dir", str(path.parent))
        try:
            self.project.name = path.stem
            st.save_project(self.project, path, self.shaders)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, APP, f"Couldn't save:\n{e}")
            return False
        self.file, self.dirty = path, False
        self.refresh(rebuild_lists=False)
        self.statusBar().showMessage(f"Saved {path}", 4000)
        return True

    def export_video(self):
        if not self._has_audio():
            return
        try:
            make_context().release()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, APP, "Video export needs OpenGL 3.3, which isn't available here.\n\n" + str(e))
            return
        d = str(self.settings.value("last_export_dir", ""))
        path, _ = QFileDialog.getSaveFileName(self, "Export the video", str(Path(d) / (self.project.name + ".mp4")), "MP4 video (*.mp4)")
        if not path:
            return
        path = Path(path).with_suffix(".mp4")
        self.settings.setValue("last_export_dir", str(path.parent))
        proj = st.StudioProject.from_dict(self.project.to_dict())      # a copy: editing carries on meanwhile

        def job(cb, cancel):
            return st.render_studio(proj, path, self.shaders, progress=cb, cancel=cancel)

        def done(res):
            msg = f"Saved {res['video']}\nLength {fmt_time(res['seconds'])}"
            if res["warnings"]:
                msg += "\n\nNote:\n" + "\n".join(res["warnings"])
            QMessageBox.information(self, APP, msg)

        self.run_task("Rendering video…", job, done)

    # --------------------------------------------------------------- events
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            f = u.toLocalFile()
            low = f.lower()
            if low.endswith(".lmv") and self._maybe_save():
                self.open_project(f)
            elif low.endswith((".cue", ".txt")) and self._has_audio():
                self._load_cue(f)
            elif Path(f).suffix.lower() in audio_io.AUDIO_EXTS and self._maybe_save():
                self.open_audio(f)
            break

    def closeEvent(self, ev):
        if self.task is not None:
            self.task.cancel()
            self.task.wait(5000)
        if not self._maybe_save():
            ev.ignore()
            return
        self.tick.stop()
        self.player.close()
        self.library.shutdown()
        self.worker.stop()
        self.worker.wait(3000)
        if self._own_thumbs:
            self.thumbs.shutdown()
        shutil.rmtree(self.tmp, ignore_errors=True)
        ev.accept()
