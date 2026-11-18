"""Mix > Deep analysis: compare the app's own analysis of each song with All-In-One's, and choose per song."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from .. import deep, plan as planmod, stems
from .tasks import APP

APP_A, DEEP_A = "app", "deep"


class DeepDialog(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.state = main.state
        self.setWindowTitle("Deep analysis (All-In-One)")
        self.resize(1180, 520)
        lay = QVBoxLayout(self)
        intro = QLabel(
            "All-In-One is a neural network that finds a song's tempo, beats, downbeats and parts (intro, verse, chorus, "
            "bridge, outro) from its stems. Analyse your songs, compare the two results, and choose per song which one the "
            "mix uses. The app's own analysis is kept, so you can always switch back (Undo works too).")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Song", "The app's analysis", "All-In-One", "The mix uses"])
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setWordWrap(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table, 1)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color:#8b93a1")
        lay.addWidget(self.note)
        row = QHBoxLayout()
        self.b_run = QPushButton("Analyse the songs")
        self.b_run.setToolTip("Splits songs into stems where needed, then runs All-In-One on each song not done yet")
        self.b_run.clicked.connect(self.run)
        self.b_all = QPushButton("Use All-In-One for every song")
        self.b_all.clicked.connect(lambda: self.use_all(True))
        self.b_none = QPushButton("Use the app's analysis for every song")
        self.b_none.clicked.connect(lambda: self.use_all(False))
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        for b in (self.b_run, self.b_all, self.b_none):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)
        self._boxes: dict[str, QComboBox] = {}
        self._ids: list[str] = []
        self.state.changed.connect(self._later)
        self.refresh()

    def _later(self):
        QTimer.singleShot(0, self.refresh)            # never rebuild the table from inside one of its own widgets

    def song_ids(self) -> list[str]:
        return list(dict.fromkeys(t.song_id for t in self.state.plan.tracks))

    def refresh(self):
        st = self.state
        ids = self.song_ids()
        if ids != self._ids:                           # the songs changed: new rows and new choosers
            self.table.setRowCount(0)
            self.table.setRowCount(len(ids))
            self._boxes = {}
            for r, sid in enumerate(ids):
                box = QComboBox()
                box.addItem("The app's analysis", APP_A)
                box.addItem("All-In-One", DEEP_A)
                box.currentIndexChanged.connect(lambda _i, sid=sid, box=box: self.choose(sid, box.currentData() == DEEP_A))
                self.table.setCellWidget(r, 3, box)
                self._boxes[sid] = box
            self._ids = list(ids)
        extra = st.session.extra
        todo = 0
        for r, sid in enumerate(ids):
            an = st.lib[sid]
            name = (an.title or Path(st.paths.get(sid, sid)).stem) + (f"\n{an.artist}" if an.artist else "")
            self.table.setItem(r, 0, QTableWidgetItem(name))
            res = deep.cached(sid)
            using = deep.in_use(extra, sid)
            if using:                                  # show the app's own analysis from what was kept
                o = extra["deep_orig"][sid]
                from ..analysis import Section
                mine = deep.summary(an, [Section(**s) for s in o["sections"]], o["bpm"], o["grid_origin"])
            else:
                mine = deep.summary(an)
            self.table.setItem(r, 1, QTableWidgetItem(mine))
            if res:
                f = deep.to_fields(an, res) if not using else {k: getattr(an, k) for k in deep.FIELDS}
                theirs = deep.summary(an, f["sections"], f["bpm"], f["grid_origin"])
            else:
                theirs = "not split into stems yet" if not stems.cached(sid) else "not analysed yet"
                todo += 1
            self.table.setItem(r, 2, QTableWidgetItem(theirs))
            box = self._boxes[sid]
            box.blockSignals(True)
            box.model().item(1).setEnabled(bool(res))
            box.setCurrentIndex(1 if using else 0)
            box.blockSignals(False)
        self.table.resizeRowsToContents()
        ok = deep.available()
        self.b_run.setEnabled(ok and todo > 0)
        self.b_all.setEnabled(any(deep.cached(s) for s in ids))
        self.b_none.setEnabled(bool(extra.get("deep_orig")))
        if not ok:
            self.note.setText("Deep analysis needs the \"with stems\" download of the app (LazyMixtapeMaker-…-Stems).")
        elif todo:
            self.note.setText(f"{todo} song{'s' if todo != 1 else ''} still to analyse. Without a graphics card, splitting "
                              "takes about as long as a song plays; the analysis itself is quicker.")
        else:
            self.note.setText("All songs analysed. Listen to the mix with each choice: the better analysis is the one "
                              "whose blends land on the beat and at the right moments.")

    def choose(self, sid: str, on: bool):
        self.use({sid: on})

    def use(self, wanted: dict):
        st = self.state
        extra = st.session.extra

        def fn(plan, lib):
            for sid, on in wanted.items():
                deep.use(lib, extra, sid, on)
            planmod.recompute(plan, lib)
        try:
            st.edit(fn)
        except deep.DeepError as e:
            QMessageBox.warning(self, APP, str(e))
        st.preview_path = None
        self.refresh()

    def use_all(self, on: bool):
        ids = [s for s in self.song_ids() if (deep.cached(s) or not on)]
        self.use({s: on for s in ids})

    def run(self):
        st = self.state
        ids = [s for s in self.song_ids() if not deep.cached(s)]
        if not ids:
            return
        lib, paths = st.lib, st.paths
        need_split = [s for s in ids if not stems.cached(s)]
        if need_split and QMessageBox.question(
                self, APP, f"{len(need_split)} of these songs must be split into stems first. Without a graphics card that "
                "takes about as long as the songs play. Go ahead?") != QMessageBox.StandardButton.Yes:
            return

        def job(cb, cancel):
            n = len(ids)
            done = 0
            for k, sid in enumerate(ids):
                name = lib[sid].title or Path(paths[sid]).name
                if not stems.cached(sid):
                    stems.split(paths[sid], sid, cancel=cancel,
                                progress=lambda f, k=k, name=name: cb(f"Splitting {name} ({k + 1}/{n})…", (k + 0.7 * f) / n))
                    stems.lag(sid, paths[sid])
                deep.run(paths[sid], sid, cancel=cancel,
                         progress=lambda f, k=k, name=name: cb(f"Analysing {name} ({k + 1}/{n})…", (k + 0.7 + 0.3 * f) / n))
                done += 1
            return done

        def finished(n):
            self.refresh()
            self.main.statusBar().showMessage(f"Deep analysis done for {n} song{'s' if n != 1 else ''}.", 8000)
        self.main.run_task("Deep analysis…", job, finished)
