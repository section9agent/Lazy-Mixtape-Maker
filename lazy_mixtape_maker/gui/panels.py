"""Side panels: track / transition / effects / visual inspector, cue sheet, visuals library."""
from __future__ import annotations

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QListWidget, QListWidgetItem, QPushButton,
                               QRadioButton, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout,
                               QWidget, QButtonGroup)

from .. import cue as cuemod, effects as fxmod, plan as planmod
from ..audio_io import SR
from ..video import MODE_LABELS, MODES, resolve_assignments
from .state import AppState
from .workers import ThumbWorker

TRANSITION_LABELS = {
    "eq_swap": "Bass-swap blend (DJ style)",
    "crossfade": "Crossfade",
    "cut_fx": "Cut with an effect",
    "cut": "Hard cut",
}


def fmt_time(sec: float) -> str:
    sec = max(0, int(round(sec)))
    return f"{sec // 60}:{sec % 60:02d}"


def _spin(lo, hi, step, decimals=1, suffix=""):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setDecimals(decimals)
    if suffix:
        s.setSuffix(suffix)
    return s


class ThumbCache(QObject):
    updated = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pix: dict[str, QPixmap] = {}
        self.pending: set[str] = set()
        self.worker = ThumbWorker(self)
        self.worker.ready.connect(self._ready)
        self.error = ""
        self.worker.unavailable.connect(self._unavailable)
        self.worker.start()

    def _unavailable(self, msg):
        self.error = msg

    def _ready(self, sid, img):
        self.pix[sid] = QPixmap.fromImage(img)
        self.pending.discard(sid)
        self.updated.emit(sid)

    def get(self, shader) -> QPixmap | None:
        if shader.id in self.pix:
            return self.pix[shader.id]
        if shader.id not in self.pending and not self.error:
            self.pending.add(shader.id)
            self.worker.request(shader)
        return None

    def forget(self, sid):
        self.pix.pop(sid, None)

    def shutdown(self):
        self.worker.stop()
        self.worker.wait(3000)


# ====================================================================== inspector
class Inspector(QTabWidget):
    def __init__(self, state: AppState, thumbs: ThumbCache, parent=None):
        super().__init__(parent)
        self.state = state
        self.track_tab = TrackTab(state)
        self.trans_tab = TransitionTab(state)
        self.fx_tab = EffectsTab(state)
        self.vis_tab = TrackVisualTab(state, thumbs)
        self.addTab(self.track_tab, "Song")
        self.addTab(self.trans_tab, "Transition")
        self.addTab(self.fx_tab, "Effects")
        self.addTab(self.vis_tab, "Visual")
        state.selection.connect(self._on_selection)

    def _on_selection(self):
        if self.state.sel_fx:
            self.setCurrentWidget(self.fx_tab)


class _Tab(QWidget):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self._busy = False
        state.changed.connect(self.refresh)
        state.selection.connect(self.refresh)

    def idx(self) -> int:
        return self.state.sel

    def refresh(self):
        self._busy = True
        try:
            self._refresh()
        finally:
            self._busy = False

    def _refresh(self):
        pass


class TrackTab(_Tab):
    def __init__(self, state):
        super().__init__(state)
        lay = QVBoxLayout(self)
        self.title = QLabel("Select a song in the list or timeline")
        self.title.setWordWrap(True)
        f = self.title.font(); f.setBold(True); f.setPointSize(f.pointSize() + 2); self.title.setFont(f)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.title)
        lay.addWidget(self.info)
        box = QGroupBox("Which part of the song plays")
        form = QFormLayout(box)
        self.start = _spin(0, 99999, 0.5, 2, " s")
        self.end = _spin(0, 99999, 0.5, 2, " s")
        form.addRow("Starts at", self.start)
        form.addRow("Ends at", self.end)
        self.sections = QListWidget()
        self.sections.setMaximumHeight(130)
        form.addRow(self.sections)
        row = QHBoxLayout()
        self.b_start, self.b_end = QPushButton("Start here"), QPushButton("End here")
        row.addWidget(self.b_start); row.addWidget(self.b_end)
        form.addRow(row)
        self.b_auto = QPushButton("Back to the AI's choice")
        form.addRow(self.b_auto)
        lay.addWidget(box)
        lay.addStretch(1)
        self.start.editingFinished.connect(self._set_bounds)
        self.end.editingFinished.connect(self._set_bounds)
        self.b_start.clicked.connect(lambda: self._section_bound("start"))
        self.b_end.clicked.connect(lambda: self._section_bound("end"))
        self.b_auto.clicked.connect(self._auto)
        self._refresh()

    def _refresh(self):
        i = self.idx()
        t = self.state.selected_track()
        for w in (self.start, self.end, self.sections, self.b_start, self.b_end, self.b_auto):
            w.setEnabled(t is not None)
        self.sections.clear()
        if t is None:
            self.title.setText("Select a song in the list or timeline")
            self.info.setText("")
            return
        an = self.state.lib[t.song_id]
        self.title.setText(f"{i + 1}. {an.title}" + (f"\n{an.artist}" if an.artist else ""))
        tr_next = self.state.plan.transition_after(i)
        tr_prev = self.state.plan.transition_after(i - 1) if i > 0 else None
        shift = f", shifted {t.pitch:+d} semitone{'s' if abs(t.pitch) != 1 else ''} to fit the previous song" if t.pitch else ""
        parts = []
        if tr_prev is not None and tr_prev.matched and tr_prev.tempo > 0:
            parts.append(f"comes in at {tr_prev.tempo:.1f}")
        if tr_next is not None and tr_next.matched and tr_next.tempo > 0:
            parts.append(f"leaves at {tr_next.tempo:.1f}")
        blend = ("; " + ", ".join(parts) + " BPM to match its neighbours") if parts else ""
        stretch = ""
        if tr_next is not None and not tr_next.matched:
            stretch = " <span style='color:#e0a030'>(too far from the next song's tempo to beat-match; cut with an effect)</span>"
        self.info.setText(
            f"Tempo <b>{an.bpm:.1f} BPM</b> → plays at <b>{(t.bpm or an.bpm):.1f}</b>{blend}{stretch}<br>"
            f"Key <b>{an.key_name}</b> ({an.camelot}){shift}<br>"
            f"Length {fmt_time(an.duration)}, plays {fmt_time(self.state.slot_seconds(self.idx()))}"
            + ("" if t.auto_bounds else " <i>(trimmed by you)</i>"))
        self.start.setRange(0, an.duration); self.end.setRange(0, an.duration)
        self.start.setValue(t.src_start); self.end.setValue(t.src_end)
        for s in an.sections:
            QListWidgetItem(f"{fmt_time(s.start)}  {s.label}  ({fmt_time(s.end - s.start)})", self.sections)
        self.b_auto.setEnabled(not t.auto_bounds)

    def _set_bounds(self):
        if self._busy or self.idx() < 0:
            return
        i, a, b = self.idx(), self.start.value(), self.end.value()
        try:
            self.state.edit(lambda p, lib: planmod.set_track_bounds(p, lib, i, a, b))
        except ValueError as e:
            self.window().statusBar().showMessage(str(e), 5000)
            self.refresh()

    def _section_bound(self, which):
        r = self.sections.currentRow()
        t = self.state.selected_track()
        if r < 0 or t is None:
            return
        sec = self.state.lib[t.song_id].sections[r]
        i = self.idx()
        try:
            if which == "start":
                self.state.edit(lambda p, lib: planmod.set_track_bounds(p, lib, i, src_start=sec.start))
            else:
                self.state.edit(lambda p, lib: planmod.set_track_bounds(p, lib, i, src_end=sec.end))
        except ValueError as e:
            self.window().statusBar().showMessage(str(e), 5000)

    def _auto(self):
        i = self.idx()

        def fn(p, lib):
            p.tracks[i].auto_bounds = True
            planmod.recompute(p, lib)
        self.state.edit(fn)


class TransitionTab(_Tab):
    def __init__(self, state):
        super().__init__(state)
        lay = QVBoxLayout(self)
        self.head = QLabel("Select a song that has another one after it")
        self.head.setWordWrap(True)
        lay.addWidget(self.head)
        box = QGroupBox("How the next song comes in")
        form = QFormLayout(box)
        self.type = QComboBox()
        for k, v in TRANSITION_LABELS.items():
            self.type.addItem(v, k)
        self.beats = QSpinBox()
        self.beats.setRange(0, 128)
        self.beats.setSuffix(" beats")
        self.beats.setSingleStep(4)
        self.len_label = QLabel()
        self.auto_btn = QPushButton("Back to the AI's choice")
        form.addRow("Style", self.type)
        form.addRow("Blend length", self.beats)
        form.addRow("", self.len_label)
        form.addRow(self.auto_btn)
        lay.addWidget(box)
        hint = QLabel("Tip: you can also drag a song left or right in the timeline to change how long it "
                      "overlaps the one before it.")
        hint.setWordWrap(True); hint.setStyleSheet("color:#8b93a1")
        lay.addWidget(hint)
        lay.addStretch(1)
        self.type.currentIndexChanged.connect(self._apply)
        self.beats.editingFinished.connect(self._apply)
        self.auto_btn.clicked.connect(self._auto)
        self._refresh()

    def _tr(self):
        i = self.idx()
        return self.state.plan.transition_after(i) if i >= 0 else None

    def _refresh(self):
        tr = self._tr()
        for w in (self.type, self.beats, self.auto_btn):
            w.setEnabled(tr is not None)
        if tr is None:
            self.head.setText("Select a song that has another one after it")
            self.len_label.setText("")
            return
        i = self.idx()
        a, b = (self.state.lib[self.state.plan.tracks[k].song_id].title for k in (i, i + 1))
        self.head.setText(f"<b>{a}</b> → <b>{b}</b>")
        self.type.setCurrentIndex(self.type.findData(tr.type))
        self.beats.setValue(tr.overlap_beats)
        secs = planmod.overlap_seconds(self.state.plan, tr)
        self.len_label.setText(f"{tr.overlap_beats / 4:g} bars ≈ {secs:.1f} s" + ("" if tr.auto else "  (set by you)"))
        self.auto_btn.setEnabled(not tr.auto)

    def _apply(self):
        if self._busy or self._tr() is None:
            return
        i, ty, bt = self.idx(), self.type.currentData(), self.beats.value()
        if ty in ("cut", "cut_fx"):
            bt = 0
        elif bt == 0:
            bt = 8
        self.state.edit(lambda p, lib: planmod.set_transition(p, lib, i, ty, bt))

    def _auto(self):
        tr = self._tr()
        if tr is None:
            return

        def fn(p, lib):
            tr.auto = True
            planmod.recompute(p, lib)
        self.state.edit(fn)


class EffectsTab(_Tab):
    def __init__(self, state):
        super().__init__(state)
        lay = QVBoxLayout(self)
        self.head = QLabel("Select a song to add effects to it")
        lay.addWidget(self.head)
        self.list = QListWidget()
        self.list.setMaximumHeight(120)
        lay.addWidget(self.list)
        row = QHBoxLayout()
        self.kind = QComboBox()
        for k, v in fxmod.EFFECT_TYPES.items():
            self.kind.addItem(v["label"], k)
        self.add_start = QPushButton("Add at start")
        self.add_end = QPushButton("Add at end")
        row.addWidget(self.kind, 1); row.addWidget(self.add_start); row.addWidget(self.add_end)
        lay.addLayout(row)
        self.box = QGroupBox("Selected effect")
        self.form = QFormLayout(self.box)
        self.anchor = QComboBox()
        self.anchor.addItem("Relative to the start of the song", "start")
        self.anchor.addItem("Relative to the end of the song", "end")
        self.offset = _spin(-600, 600, 0.25, 2, " s")
        self.duration = _spin(0.1, 120, 0.25, 2, " s")
        self.form.addRow("Timing", self.anchor)
        self.form.addRow("Offset", self.offset)
        self.form.addRow("Length", self.duration)
        self.param_widgets: dict[str, QWidget] = {}
        self.param_form = QFormLayout()
        self.form.addRow(self.param_form)
        self.remove = QPushButton("Remove effect")
        self.form.addRow(self.remove)
        lay.addWidget(self.box)
        lay.addStretch(1)
        self.list.currentRowChanged.connect(self._pick)
        self.add_start.clicked.connect(lambda: self._add("start"))
        self.add_end.clicked.connect(lambda: self._add("end"))
        self.anchor.currentIndexChanged.connect(self._timing_changed)
        self.offset.editingFinished.connect(self._timing_changed)
        self.duration.editingFinished.connect(self._timing_changed)
        self.remove.clicked.connect(self._remove)
        self._built_for = None
        self._refresh()

    def _cur(self):
        t = self.state.selected_track()
        if t is None or not self.state.sel_fx:
            return None
        return next((e for e in t.effects if e.id == self.state.sel_fx), None)

    def _refresh(self):
        t = self.state.selected_track()
        for w in (self.kind, self.add_start, self.add_end):
            w.setEnabled(t is not None)
        self.list.blockSignals(True)
        self.list.clear()
        if t is None:
            self.head.setText("Select a song to add effects to it")
            self.list.blockSignals(False)
            self.box.setVisible(False)
            return
        an = self.state.lib[t.song_id]
        self.head.setText(f"Effects on <b>{an.title}</b>")
        cur_row = -1
        for r, e in enumerate(t.effects):
            where = "start" if e.anchor == "start" else "end"
            QListWidgetItem(f"{fxmod.EFFECT_TYPES[e.type]['label']} — {where} {e.offset:+.1f}s, {e.duration:.1f}s"
                            + ("  (AI)" if e.auto else ""), self.list)
            if e.id == self.state.sel_fx:
                cur_row = r
        self.list.setCurrentRow(cur_row)
        self.list.blockSignals(False)
        e = self._cur()
        self.box.setVisible(e is not None)
        if e is None:
            return
        self.anchor.setCurrentIndex(self.anchor.findData(e.anchor))
        self.offset.setValue(e.offset)
        self.duration.setValue(e.duration)
        self._build_params(e)

    def _build_params(self, e):
        key = (e.id, e.type)
        params = fxmod.default_params(e.type)
        params.update(e.params)
        if self._built_for != key:
            while self.param_form.rowCount():
                self.param_form.removeRow(0)
            self.param_widgets = {}
            for name, default in fxmod.EFFECT_TYPES[e.type]["defaults"].items():
                if isinstance(default, str):
                    w = QComboBox()
                    w.addItems(["lowpass", "highpass"] if name == "mode" else [default])
                    w.currentTextChanged.connect(lambda _v, n=name: self._param_changed(n))
                else:
                    w = _spin(0, 30000, 0.05 if default < 10 else 50.0, 2 if default < 10 else 0)
                    w.editingFinished.connect(lambda n=name: self._param_changed(n))
                self.param_widgets[name] = w
                self.param_form.addRow(name.replace("_", " "), w)
            self._built_for = key
        for name, w in self.param_widgets.items():
            if isinstance(w, QComboBox):
                w.blockSignals(True); w.setCurrentText(str(params[name])); w.blockSignals(False)
            else:
                w.setValue(float(params[name]))

    def _pick(self, row):
        if self._busy:
            return
        t = self.state.selected_track()
        if t is not None and 0 <= row < len(t.effects):
            self.state.select(self.state.sel, t.effects[row].id)

    def _add(self, anchor):
        i = self.idx()
        kind = self.kind.currentData()
        beat = 60.0 / (self.state.selected_track().bpm or self.state.plan.master_bpm)
        dur = 8 * beat if kind != "backspin" else 1.6
        holder = {}

        def fn(p, lib):
            holder["e"] = planmod.add_effect(p, i, kind, anchor, None, dur, fxmod.default_params(kind))
        self.state.edit(fn)
        self._built_for = None
        self.state.select(i, holder["e"].id)

    def _timing_changed(self):
        e = self._cur()
        if self._busy or e is None:
            return
        i = self.idx()
        ch = dict(anchor=self.anchor.currentData(), offset=self.offset.value(), duration=self.duration.value())
        self.state.edit(lambda p, lib: planmod.update_effect(p, i, e.id, **ch))

    def _param_changed(self, name):
        e = self._cur()
        if self._busy or e is None:
            return
        w = self.param_widgets[name]
        val = w.currentText() if isinstance(w, QComboBox) else w.value()
        i = self.idx()
        self.state.edit(lambda p, lib: planmod.update_effect(p, i, e.id, params={name: val}))

    def _remove(self):
        e = self._cur()
        if e is None:
            return
        i = self.idx()
        self.state.edit(lambda p, lib: planmod.remove_effect(p, i, e.id))
        self.state.select(i, None)


class TrackVisualTab(_Tab):
    def __init__(self, state, thumbs: ThumbCache):
        super().__init__(state)
        self.thumbs = thumbs
        lay = QVBoxLayout(self)
        self.head = QLabel("Select a song to choose its visual")
        self.head.setWordWrap(True)
        lay.addWidget(self.head)
        self.combo = QComboBox()
        lay.addWidget(self.combo)
        self.pic = QLabel()
        self.pic.setFixedSize(256, 144)
        self.pic.setStyleSheet("background:#111;border-radius:6px")
        lay.addWidget(self.pic)
        self.note = QLabel()
        self.note.setWordWrap(True); self.note.setStyleSheet("color:#8b93a1")
        lay.addWidget(self.note)
        lay.addStretch(1)
        self.combo.currentIndexChanged.connect(self._choose)
        thumbs.updated.connect(lambda _s: self.refresh())
        state.library_changed.connect(self.refresh)
        self._refresh()

    def _resolved(self):
        return resolve_assignments(self.state.plan, self.state.lib, self.state.video, self.state.shaders)

    def _refresh(self):
        t = self.state.selected_track()
        self.combo.setEnabled(t is not None)
        self.combo.blockSignals(True)
        self.combo.clear()
        for sh in self.state.shaders.all():
            self.combo.addItem(sh.name, sh.id)
        self.combo.blockSignals(False)
        if t is None:
            self.head.setText("Select a song to choose its visual")
            self.pic.clear()
            return
        res = self._resolved()
        sid = res[self.idx()] if self.idx() < len(res) else ""
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(max(0, self.combo.findData(sid)))
        self.combo.blockSignals(False)
        self.head.setText(f"Visual while <b>{self.state.lib[t.song_id].title}</b> plays")
        sh = self.state.shaders.get(sid)
        if sh:
            pm = self.thumbs.get(sh)
            if pm:
                self.pic.setPixmap(pm)
            else:
                self.pic.setText("…")
        mode = self.state.video.mode
        self.note.setText("" if mode == "per_song" else
                          f"Video mode is “{MODE_LABELS[mode]}”. Picking a visual here switches to “I choose per song” "
                          "and keeps everyone else's visual as it is now.")

    def _choose(self, _):
        if self._busy or self.idx() < 0:
            return
        sid = self.combo.currentData()
        res = self._resolved()
        i = self.idx()
        uids = [t.uid for t in self.state.plan.tracks]

        def fn(v):
            if v.mode != "per_song":
                v.assignments = {u: s for u, s in zip(uids, res)}
                v.mode = "per_song"
            v.assignments[uids[i]] = sid
        self.state.edit_video(fn)


# =================================================================== cue sheet
class CuePanel(QWidget):
    export_clicked = Signal()

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Track breaks in the finished mix (written next to your export as a .cue and a text list)"))
        top.addStretch(1)
        self.btn = QPushButton("Save cue sheet…")
        self.copy = QPushButton("Copy track list")
        top.addWidget(self.copy); top.addWidget(self.btn)
        lay.addLayout(top)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Time", "Artist", "Title", "BPM", "Key", "Comes in with"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().hide()
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        h.setStretchLastSection(True)
        for c, w in enumerate((70, 180, 280, 60, 60)):
            self.table.setColumnWidth(c, w)
        lay.addWidget(self.table)
        self.btn.clicked.connect(self.export_clicked)
        self.copy.clicked.connect(self._copy)
        self.table.cellClicked.connect(lambda r, c: state.select(r))
        state.changed.connect(self.refresh)
        state.selection.connect(self._sel)
        self.refresh()

    def refresh(self):
        rows = cuemod.tracklist(self.state.plan, self.state.lib) if self.state.plan.tracks else []
        self.table.setRowCount(len(rows))
        for r, d in enumerate(rows):
            vals = [fmt_time(d["cue"]), d["artist"], d["title"], f"{d['bpm']:g}", d["key"],
                    TRANSITION_LABELS.get(d["transition_in"], "start of the mix" if r == 0 else "")]
            for c, v in enumerate(vals):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self._sel()

    def _sel(self):
        if 0 <= self.state.sel < self.table.rowCount():
            self.table.selectRow(self.state.sel)

    def _copy(self):
        from PySide6.QtWidgets import QApplication

        lines = []
        for r in range(self.table.rowCount()):
            who = self.table.item(r, 1).text()
            lines.append(f"{self.table.item(r, 0).text()}  {who + ' - ' if who else ''}{self.table.item(r, 2).text()}")
        QApplication.clipboard().setText("\n".join(lines))


# ================================================================ visuals library
class VisualsPanel(QWidget):
    add_clicked = Signal()

    def __init__(self, state: AppState, thumbs: ThumbCache):
        super().__init__()
        self.state, self.thumbs = state, thumbs
        self._busy = False
        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        row = QHBoxLayout()
        row.addWidget(QLabel("<b>Visuals</b> — saved on this computer, ready to use offline"))
        row.addStretch(1)
        self.b_add = QPushButton("Add from Shadertoy…")
        self.b_remove = QPushButton("Remove")
        row.addWidget(self.b_add); row.addWidget(self.b_remove)
        left.addLayout(row)
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(QSize(160, 90))
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setSpacing(8)
        self.list.setWordWrap(True)
        self.list.setGridSize(QSize(180, 128))
        left.addWidget(self.list, 1)
        lay.addLayout(left, 3)

        box = QGroupBox("Video")
        form = QVBoxLayout(box)
        self.group = QButtonGroup(self)
        self.radios = {}
        for m in MODES:
            rb = QRadioButton(MODE_LABELS[m])
            self.group.addButton(rb)
            self.radios[m] = rb
            form.addWidget(rb)
        self.single = QComboBox()
        form.addWidget(QLabel("The one visual (for “One visual for the whole video”):"))
        form.addWidget(self.single)
        self.reroll = QPushButton("Pick different random visuals")
        form.addWidget(self.reroll)
        f2 = QFormLayout()
        self.res = QComboBox()
        for label, wh in (("1280 × 720 (HD)", (1280, 720)), ("1920 × 1080 (Full HD)", (1920, 1080)),
                          ("854 × 480", (854, 480)), ("1080 × 1080 (square)", (1080, 1080))):
            self.res.addItem(label, wh)
        self.fps = QComboBox()
        for v in (24, 30, 60):
            self.fps.addItem(f"{v} fps", v)
        self.overlay = QCheckBox("Show cover art, artist and title (lower left)")
        f2.addRow("Size", self.res)
        f2.addRow("Frame rate", self.fps)
        form.addLayout(f2)
        form.addWidget(self.overlay)
        form.addStretch(1)
        lay.addWidget(box, 2)

        self.b_add.clicked.connect(self.add_clicked)
        self.b_remove.clicked.connect(self._remove)
        self.group.buttonToggled.connect(self._mode)
        self.single.currentIndexChanged.connect(self._single)
        self.reroll.clicked.connect(lambda: state.edit_video(lambda v: setattr(v, "seed", v.seed + 1)))
        self.res.currentIndexChanged.connect(self._size)
        self.fps.currentIndexChanged.connect(self._fps)
        self.overlay.toggled.connect(lambda c: None if self._busy else state.edit_video(lambda v: setattr(v, "show_overlay", c)))
        thumbs.updated.connect(self._thumb)
        state.changed.connect(self.refresh)
        state.library_changed.connect(self.rebuild)
        self.rebuild()

    def rebuild(self):
        self._busy = True
        self.list.clear()
        self.single.clear()
        for sh in self.state.shaders.all():
            it = QListWidgetItem(sh.name + (" ⚠" if sh.warnings else ""), self.list)
            it.setData(Qt.ItemDataRole.UserRole, sh.id)
            tip = [f"{sh.name}" + (f" by {sh.author}" if sh.author else "")]
            tip += sh.warnings
            if sh.url:
                tip.append(sh.url)
            it.setToolTip("\n".join(tip))
            pm = self.thumbs.get(sh)
            if pm:
                it.setIcon(QIcon(pm))
            self.single.addItem(sh.name, sh.id)
        self._busy = False
        self.refresh()

    def _thumb(self, sid):
        for r in range(self.list.count()):
            it = self.list.item(r)
            if it.data(Qt.ItemDataRole.UserRole) == sid:
                pm = self.thumbs.pix.get(sid)
                if pm:
                    it.setIcon(QIcon(pm))

    def refresh(self):
        v = self.state.video
        self._busy = True
        self.radios[v.mode].setChecked(True)
        self.single.setCurrentIndex(max(0, self.single.findData(v.single_shader)))
        self.single.setEnabled(v.mode == "single")
        self.reroll.setEnabled(v.mode == "random")
        self.res.setCurrentIndex(max(0, self.res.findData((v.width, v.height))))
        self.fps.setCurrentIndex(max(0, self.fps.findData(v.fps)))
        self.overlay.setChecked(v.show_overlay)
        self._busy = False

    def _mode(self, btn, checked):
        if self._busy or not checked:
            return
        m = next(k for k, r in self.radios.items() if r is btn)
        self.state.edit_video(lambda v: setattr(v, "mode", m))

    def _single(self, _):
        if self._busy:
            return
        sid = self.single.currentData()
        if sid:
            self.state.edit_video(lambda v: setattr(v, "single_shader", sid))

    def _size(self, _):
        if self._busy:
            return
        w, h = self.res.currentData()
        self.state.edit_video(lambda v: (setattr(v, "width", w), setattr(v, "height", h)))

    def _fps(self, _):
        if self._busy:
            return
        self.state.edit_video(lambda v: setattr(v, "fps", self.fps.currentData()))

    def _remove(self):
        it = self.list.currentItem()
        if not it:
            return
        sid = it.data(Qt.ItemDataRole.UserRole)
        try:
            self.state.shaders.remove(sid)
        except ValueError as e:
            self.window().statusBar().showMessage(str(e), 5000)
            return
        self.thumbs.forget(sid)

        def fn(v):
            v.assignments = {k: x for k, x in v.assignments.items() if x != sid}
            if v.single_shader == sid:
                v.single_shader = "builtin:plasma"
        self.state.edit_video(fn)
        self.rebuild()
