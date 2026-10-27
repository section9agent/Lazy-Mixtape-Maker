"""The Lazy Mixtape Maker window."""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import soundfile as sf
from PySide6.QtCore import QSettings, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QMainWindow, QMessageBox, QProgressDialog, QPushButton, QScrollArea, QSplitter,
                               QTabWidget, QToolBar, QToolButton, QVBoxLayout, QWidget)

from .. import __version__, audio_io, cue as cuemod, plan as planmod, prefs
from ..audio_io import SR
from ..engine import analyze_library, export_both, export_session, transition_preview_plan
from ..render import MissingSongsError, render_mix
from ..video import render_video
from ..visuals import ShaderLibrary, make_context
from . import theme
from .player import AudioPlayer
from .dialogs import AddVisualDialog, GenerateDialog
from .shader_manager import ShaderManager
from .panels import CuePanel, Inspector, ThumbCache, VisualsPanel, fmt_hms, fmt_time
from .state import AppState
from .timeline import TimelineWidget, track_color
from .tasks import TaskMixin
from .workers import Worker

ORG, APP = "LazyMixtapeMaker", "Lazy Mixtape Maker"
SESSION_FILTER = "Lazy Mixtape session (*.lmm)"
AUDIO_FILTER = "Music (*.mp3 *.wav *.flac *.m4a)"


class TrackList(QListWidget):
    from PySide6.QtCore import Signal
    moved = Signal(int, int)
    files_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setIconSize(QSize(12, 12))
        self.setSpacing(1)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.source() is self:
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls() or e.source() is self:
            e.acceptProposedAction()

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            self.files_dropped.emit([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])
            e.acceptProposedAction()
        elif e.source() is self:
            src = self.currentRow()
            item = self.itemAt(e.position().toPoint())
            dst = self.row(item) if item else self.count() - 1
            e.setDropAction(Qt.DropAction.IgnoreAction)
            e.accept()
            QTimer.singleShot(0, lambda: self.moved.emit(src, dst))


class MainWindow(TaskMixin, QMainWindow):
    def __init__(self, shaders: ShaderLibrary | None = None):
        super().__init__()
        self.settings = QSettings(ORG, APP)
        self.state = AppState(shaders)
        self.thumbs = ThumbCache(self)
        self.task: Worker | None = None
        self.progress: QProgressDialog | None = None
        self.tmp = Path(tempfile.mkdtemp(prefix="lmm_preview_"))
        self._preview_n = 0
        self._player = None
        self._preview_is_full = False
        self.setAcceptDrops(True)
        self.resize(1360, 860)
        self._build_ui()
        self._build_actions()
        self._init_player()
        s = self.state
        s.changed.connect(self._on_changed)
        s.selection.connect(self._on_selection)
        s.library_changed.connect(self._on_changed)
        s.title_changed.connect(self._update_title)
        self._on_changed()
        self._update_title()

    # ------------------------------------------------------------------- layout
    def _build_ui(self):
        s = self.state
        # left: the songs in the mix
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(8, 8, 4, 4)
        ll.addWidget(QLabel("<b>Songs in the mix</b>"))
        self.list = TrackList()
        ll.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.b_up, self.b_down, self.b_remove = QPushButton("↑"), QPushButton("↓"), QPushButton("Remove")
        self.b_up.setToolTip("Move up"); self.b_down.setToolTip("Move down")
        self.b_up.setFixedSize(52, 38); self.b_down.setFixedSize(52, 38)
        for b in (self.b_up, self.b_down):
            b.setStyleSheet("font-size: 20px; padding: 0")
        row.addWidget(self.b_up); row.addWidget(self.b_down); row.addStretch(1); row.addWidget(self.b_remove)
        ll.addLayout(row)
        hint = QLabel("Drag songs to reorder. Drop music files here to add them.")
        hint.setStyleSheet("color:#8b93a1"); hint.setWordWrap(True)
        ll.addWidget(hint)
        # right: inspector
        self.inspector = Inspector(s, self.thumbs)
        top = QSplitter(Qt.Orientation.Horizontal)
        top.addWidget(left); top.addWidget(self.inspector)
        top.setSizes([480, 620])
        # bottom: timeline / cue sheet / visuals
        self.timeline = TimelineWidget(s)
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.timeline)
        self.scroll.setWidgetResizable(False)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        tl = QWidget()
        tv = QVBoxLayout(tl)
        tv.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.setContentsMargins(8, 4, 8, 0)
        self.time_label = QLabel("0:00")
        bar.addWidget(self.time_label)
        bar.addStretch(1)
        for txt, tip, fn in (("−", "Zoom out", lambda: self.timeline.set_zoom(self.timeline.pps / 1.3)),
                             ("+", "Zoom in", lambda: self.timeline.set_zoom(self.timeline.pps * 1.3)),
                             ("Fit", "Fit the whole mix", lambda: self.timeline.fit_to(self.scroll.viewport().width()))):
            b = QPushButton(txt); b.setToolTip(tip); b.setFixedSize(56, 34); b.setStyleSheet("font-size: 18px; padding: 0"); b.clicked.connect(fn); bar.addWidget(b)
        tv.addLayout(bar)
        tv.addWidget(self.scroll, 1)
        self.cue = CuePanel(s)
        self.visuals = VisualsPanel(s, self.thumbs)
        self.bottom = QTabWidget()
        self.bottom.addTab(tl, "Timeline")
        self.bottom.addTab(self.cue, "Cue sheet")
        self.bottom.addTab(self.visuals, "Visuals")
        self.library = ShaderManager(s.shaders, self.thumbs, "Use for the whole video")
        self.bottom.addTab(self.library, "Shader library")
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(top); split.addWidget(self.bottom)
        split.setSizes([440, 360])
        self.setCentralWidget(split)
        self.info = QLabel()
        self.statusBar().addPermanentWidget(self.info)
        # wiring
        self.list.currentRowChanged.connect(lambda r: s.select(r) if r >= 0 else None)
        self.list.moved.connect(self._reorder)
        self.list.files_dropped.connect(lambda ps: self.add_files(ps, ask_options=any(Path(p).is_dir() for p in ps)))
        self.b_up.clicked.connect(lambda: self._nudge(-1))
        self.b_down.clicked.connect(lambda: self._nudge(1))
        self.b_remove.clicked.connect(self.remove_selected)
        self.timeline.seek.connect(self._seek)
        self.cue.export_clicked.connect(self.export_cue)
        self.visuals.add_clicked.connect(self.add_visual)
        self.library.changed.connect(lambda: (s.library_changed.emit(), s.changed.emit()))
        self.library.use_clicked.connect(self._use_for_all)

    def _build_actions(self):
        def act(text, slot, shortcut=None, tip=None, glyph=None):
            a = QAction(text, self)
            if glyph:
                a.setIcon(theme.glyph_icon(glyph))
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            if tip:
                a.setToolTip(tip)
            return a

        self.a_new = act("New", self.new_session, "Ctrl+N")
        self.a_open = act("Open session…", self.open_session, "Ctrl+O")
        self.a_save = act("Save session", self.save_session, "Ctrl+S")
        self.a_save_as = act("Save session as…", lambda: self.save_session(True), "Ctrl+Shift+S")
        self.a_add = act("Add songs", self.add_songs_dialog, "Ctrl+I", "Add songs to the mix", "＋")
        self.a_add_folder = act("Add folder", self.add_folder_dialog, "Ctrl+Shift+I", "Add every song in a folder", "▤")
        self.a_locate = act("Find missing songs…", self.locate_songs)
        self.a_gen = act("Generate mix", self.generate, "Ctrl+G", "Let the AI build (or rebuild) the mix", "✦")
        self.a_refresh = act("Refresh AI suggestions", self.refresh_ai, None, "Re-pick everything you haven't changed by hand")
        self.a_play = act("Play", self.toggle_play, "Space", None, "▶")
        self.a_stop = act("Stop", self.stop, None, None, "■")
        self.a_audio = act("Export audio", self.export_audio, "Ctrl+E", "Save the mix as WAV, MP3 or FLAC", "♪")
        self.a_both = act("Export mix + video", self.export_both_files, "Ctrl+Alt+E",
                          "Save the audio and the video in one go (the mix is only rendered once)", "⧉")
        self.a_video = act("Export video", self.export_video, "Ctrl+Shift+E", "Save the mix as an MP4 video", "▣")
        self.a_cue = act("Save cue sheet…", self.export_cue)
        self.a_undo = act("Undo", self.state.undo, "Ctrl+Z")
        self.a_redo = act("Redo", self.state.redo, "Ctrl+Shift+Z")
        self.a_del = act("Remove selected song", self.remove_selected, "Delete")
        self.a_vpreview = act("Preview video", self.open_video_preview, "Ctrl+Shift+P",
                              "Watch the visuals in real time, in sync with the timeline", "◐")
        self.a_studio = act("Visualization Studio", self.open_studio, "Ctrl+Shift+V", "Make a video for a mixtape you already have", "◉")
        self.a_overlay = act("Show cover art, artist and title on videos", self.toggle_overlay)
        self.a_overlay.setCheckable(True)
        self.a_overlay.setChecked(prefs.overlay_enabled())
        self.a_overlay.setToolTip("On by default. Turn off to leave the card out of every video (mix videos and the studio).")
        self.a_quit = act("Quit", self.close, "Ctrl+Q")
        self.a_about = act("About", self.about)
        m = self.menuBar()
        f = m.addMenu("&File")
        for a in (self.a_new, self.a_open, self.a_save, self.a_save_as, None, self.a_add, self.a_add_folder, self.a_locate,
                  None, self.a_audio, self.a_video, self.a_both, self.a_cue, None, self.a_quit):
            f.addAction(a) if a else f.addSeparator()
        e = m.addMenu("&Edit")
        for a in (self.a_undo, self.a_redo, None, self.a_del):
            e.addAction(a) if a else e.addSeparator()
        mx = m.addMenu("&Mix")
        for a in (self.a_gen, self.a_refresh, None, self.a_play, self.a_stop):
            mx.addAction(a) if a else mx.addSeparator()
        tm = m.addMenu("&Tools")
        tm.addAction(self.a_vpreview)
        tm.addAction(self.a_studio)
        sm = m.addMenu("&Settings")
        sm.addAction(self.a_overlay)
        m.addMenu("&Help").addAction(self.a_about)
        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        tb.setIconSize(QSize(34, 34))
        self.addToolBar(tb)
        for a in (self.a_add, self.a_add_folder, None, self.a_gen, None, self.a_play, self.a_stop, None,
                  self.a_audio, self.a_video, self.a_both, None, self.a_vpreview, self.a_studio):
            tb.addAction(a) if a else tb.addSeparator()

    # ------------------------------------------------------------------- playback
    def _init_player(self):
        self._player = AudioPlayer()
        self._tick = QTimer(self)
        self._tick.setInterval(33)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start()
        self._was_playing = False

    def _playing(self) -> bool:
        return bool(self._player and self._player.playing)

    def _on_tick(self):
        p = self._player
        playing = p.playing
        if self._preview_is_full and (playing or p.ended):
            t = p.position()
            self.timeline.set_playhead(t)
            self.time_label.setText(fmt_time(t))
            if playing:
                self.scroll.ensureVisible(int(t * self.timeline.pps + 20), 10, 120, 0)
        if p.ended:
            p.ended = False
            if self._preview_is_full:
                self.timeline.set_playhead(0.0)
                self.time_label.setText("0:00")
        if playing != self._was_playing:
            self._was_playing = playing
            self._update_actions()

    def _seek(self, t: float):
        self.timeline.set_playhead(t)
        self.time_label.setText(fmt_time(t))
        if self._preview_is_full and self._player.loaded and self.state.preview_path:
            self._player.seek(t)

    def _start_audio(self, path, full: bool, at: float = 0.0):
        self._preview_is_full = full
        try:
            ok = self._player.load(path, at) and self._player.play()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, APP, f"Couldn't play the preview:\n{e}")
            return
        if not ok:
            QMessageBox.information(self, APP, "The preview was made, but this computer has no audio output "
                                               f"available for playback.\n\n{self._player.error}\n\nExporting still works.")

    def _render_preview(self, plan, full: bool, then_at: float = 0.0):
        if self._missing_check():
            return
        lib, paths = self.state.lib, self.state.paths
        self._preview_n += 1
        out = self.tmp / f"preview_{self._preview_n}.wav"

        def job(cb, cancel):
            audio = render_mix(plan, lib, paths, progress=lambda m, f: cb(m, f * 0.95))
            sf.write(str(out), audio.T, SR, subtype="PCM_16")
            return str(out)

        def done(path):
            if full:
                self.state.preview_path = path
            self._start_audio(path, full, then_at)

        self.run_task("Rendering preview…", job, done)

    def toggle_play(self):
        if not self.state.plan.tracks:
            return
        if self._playing() and self._preview_is_full:
            self._player.pause()
            self._update_actions()
            return
        if self._preview_is_full and self._player.loaded and self.state.preview_path and Path(self.state.preview_path).exists():
            self._player.play()
            self._update_actions()
            return
        self._render_preview(self.state.plan, True, self.timeline.playhead)

    def stop(self):
        self._player.pause()
        if self._player.loaded:
            self._player.seek(0.0)
        self.timeline.set_playhead(0.0)
        self.time_label.setText("0:00")

    # ------------------------------------------------------------------ tasks
    def run_task(self, title, fn, on_done):
        def on_fail(msg):
            if "Cannot find these songs" in msg:
                self._missing_check(force=True)
                return True
            return False
        TaskMixin.run_task(self, title, fn, on_done, on_fail)

    # --------------------------------------------------------------- songs
    def add_songs_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Add songs", str(self.settings.value("last_dir", "")), AUDIO_FILTER)
        if files:
            self.settings.setValue("last_dir", str(Path(files[0]).parent))
            self.add_files(files)

    def add_folder_dialog(self):
        d = QFileDialog.getExistingDirectory(self, "Add a folder of songs", str(self.settings.value("last_dir", "")))
        if d:
            self.settings.setValue("last_dir", d)
            self.add_files([d], ask_options=True)

    def add_files(self, paths, ask_options: bool = False):
        files = audio_io.list_audio_files(paths)
        if not files:
            self.statusBar().showMessage("No mp3, wav, flac or m4a files found.", 5000)
            return
        chosen = None
        if ask_options and not self.state.plan.tracks:       # a folder starts the mix: ask how to make it first
            dlg = GenerateDialog(self.state.plan.settings, False, self)
            if not dlg.exec():
                return
            chosen = dlg.result_settings()

        def done(res):
            lib, found, errors = res
            self.state.add_songs(lib, found, chosen)
            if self.state.plan.tracks and self.state.sel < 0:
                self.state.select(0)
            if errors:
                QMessageBox.warning(self, APP, "These files couldn't be analysed and were skipped:\n\n" +
                                    "\n".join(f"{Path(k).name}: {v}" for k, v in errors.items()))

        self.run_task(f"Analysing {len(files)} song{'s' if len(files) != 1 else ''}…",
                      lambda cb, cancel: analyze_library(files, progress=cb), done)

    def remove_selected(self):
        i = self.state.sel
        if i < 0:
            return
        self.state.edit(lambda p, lib: planmod.remove_track(p, lib, i))
        self.state.select(min(i, len(self.state.plan.tracks) - 1))

    def _reorder(self, src, dst):
        if src < 0 or dst < 0 or src == dst:
            return
        self.state.edit(lambda p, lib: planmod.move_track(p, lib, src, dst))
        self.state.select(dst)

    def _nudge(self, d):
        i = self.state.sel
        j = i + d
        if i < 0 or not 0 <= j < len(self.state.plan.tracks):
            return
        self.state.edit(lambda p, lib: planmod.move_track(p, lib, i, j))
        self.state.select(j)

    def _missing_check(self, force=False) -> bool:
        """True if songs are missing (after offering to look for them)."""
        miss = self.state.session.missing()
        if not miss and not force:
            return False
        d = QFileDialog.getExistingDirectory(
            self, f"{len(miss) or 'Some'} song(s) can't be found - choose the folder that has them",
            str(self.settings.value("last_dir", "")))
        if d:
            self.settings.setValue("last_dir", d)
            self.state.relink(d)
        return bool(self.state.session.missing())

    def locate_songs(self):
        if not self.state.session.missing():
            QMessageBox.information(self, APP, "All songs in this mix were found.")
            return
        if not self._missing_check(force=True):
            QMessageBox.information(self, APP, "Found them all.")
        else:
            names = ", ".join(a.title for a in self.state.session.missing())
            QMessageBox.warning(self, APP, "Still missing: " + names)

    # ---------------------------------------------------------------- the mix
    def _has_hand_edits(self) -> bool:
        p = self.state.plan
        return any((not t.auto_bounds) or any(not e.auto for e in t.effects) for t in p.tracks) or \
            any(not tr.auto for tr in p.transitions)

    def generate(self):
        if not self.state.plan.tracks:
            QMessageBox.information(self, APP, "Add some songs first (Add songs… or drag them onto the window).")
            return
        dlg = GenerateDialog(self.state.plan.settings, self._has_hand_edits(), self)
        if dlg.exec():
            self.state.generate(dlg.result_settings())
            self.state.select(0)

    def refresh_ai(self):
        self.state.edit(lambda p, lib: planmod.recompute(p, lib))

    # --------------------------------------------------------------- exporting
    def _ask_save(self, title, filters, default_name):
        d = str(self.settings.value("last_export_dir", ""))
        path, chosen = QFileDialog.getSaveFileName(self, title, str(Path(d) / default_name), filters)
        if not path:
            return None
        self.settings.setValue("last_export_dir", str(Path(path).parent))
        return Path(path), chosen

    def _mix_name(self) -> str:
        return (self.state.file.stem if self.state.file else self.state.session.name).replace("/", "-")

    def export_audio(self):
        if not self.state.plan.tracks or self._missing_check():
            return
        r = self._ask_save("Export the mix", "WAV (*.wav);;MP3 320 kbps (*.mp3);;FLAC, best quality (*.flac)",
                           self._mix_name() + ".wav")
        if not r:
            return
        path, chosen = r
        if path.suffix.lower() not in (".wav", ".mp3", ".flac"):
            path = path.with_suffix({"MP3": ".mp3", "FLAC": ".flac"}.get(chosen.split()[0], ".wav"))
        session = self.state.session
        session.name = self._mix_name()

        def done(res):
            msg = f"Saved {res['audio']}\nLength {fmt_time(res['seconds'])}"
            if "cue" in res:
                msg += f"\n\nCue sheet: {res['cue']}\nTrack list: {res['tracklist']}"
            QMessageBox.information(self, APP, msg)

        self.run_task("Exporting audio…", lambda cb, cancel: export_session(session, path, cb), done)

    def export_cue(self):
        if not self.state.plan.tracks:
            return
        r = self._ask_save("Save cue sheet", "Cue sheet (*.cue)", self._mix_name() + ".cue")
        if not r:
            return
        path = r[0].with_suffix(".cue")
        audio_name = path.with_suffix(".wav").name
        cuemod.write_cue(path, self.state.plan, self.state.lib, audio_name, title=self._mix_name())
        cuemod.write_tracklist_txt(path.with_suffix(".tracklist.txt"), self.state.plan, self.state.lib)
        self.statusBar().showMessage(f"Saved {path}  (it points at “{audio_name}” - rename the audio to match)", 8000)

    def export_video(self):
        if not self.state.plan.tracks or self._missing_check():
            return
        try:
            make_context().release()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, APP, "Video export needs OpenGL 3.3, which isn't available here.\n\n" + str(e))
            return
        r = self._ask_save("Export the video", "MP4 video (*.mp4)", self._mix_name() + ".mp4")
        if not r:
            return
        path = r[0].with_suffix(".mp4")
        st = self.state

        def job(cb, cancel):
            return render_video(st.plan, st.lib, st.paths, path, st.video, st.shaders, progress=cb, cancel=cancel)

        def done(res):
            msg = f"Saved {res['video']}\nLength {fmt_time(res['seconds'])}"
            if res["warnings"]:
                msg += "\n\nNote:\n" + "\n".join(res["warnings"])
            QMessageBox.information(self, APP, msg)

        self.run_task("Rendering video…", job, done)

    def open_video_preview(self):
        from .video_preview import VideoPreviewWindow
        w = getattr(self, "_vpreview", None)
        if w is None:
            w = self._vpreview = VideoPreviewWindow(self)
        w.show(); w.raise_(); w.activateWindow()

    def export_both_files(self):
        if not self.state.plan.tracks or self._missing_check():
            return
        try:
            make_context().release()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, APP, "Video export needs OpenGL 3.3, which isn't available here.\n\n" + str(e))
            return
        r = self._ask_save("Export the mix and the video (pick the audio file name)",
                           "WAV (*.wav);;MP3 320 kbps (*.mp3);;FLAC, best quality (*.flac)", self._mix_name() + ".wav")
        if not r:
            return
        apath, chosen = r
        if apath.suffix.lower() not in (".wav", ".mp3", ".flac"):
            apath = apath.with_suffix({"MP3": ".mp3", "FLAC": ".flac"}.get(chosen.split()[0], ".wav"))
        vpath = apath.with_suffix(".mp4")
        st = self.state
        st.session.name = self._mix_name()

        def job(cb, cancel):
            return export_both(st.session, apath, vpath, st.video, st.shaders, progress=cb, cancel=cancel)

        def done(res):
            msg = (f"Saved {res['audio']}\nSaved {res['video']}\nLength {fmt_time(res['seconds'])}")
            if "cue" in res:
                msg += f"\n\nCue sheet: {res['cue']}\nTrack list: {res['tracklist']}"
            if res["warnings"]:
                msg += "\n\nNote:\n" + "\n".join(res["warnings"])
            QMessageBox.information(self, APP, msg)

        self.run_task("Rendering the mix and the video…", job, done)

    def _use_for_all(self, sid):
        self.state.edit_video(lambda v: (setattr(v, "single_shader", sid), setattr(v, "mode", "single")))
        self.statusBar().showMessage("The whole video will use this visual.", 4000)

    def open_studio(self, path=None):
        from .studio_window import StudioWindow
        w = getattr(self, "_studio", None)
        if w is None or not w.isVisible():
            w = self._studio = StudioWindow(self.state.shaders, self.thumbs)
            w.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
            w.show()
        w.raise_(); w.activateWindow()
        if path:
            w.open_audio(path)

    def toggle_overlay(self, on: bool):
        prefs.set("show_overlay", bool(on))
        self.statusBar().showMessage("Cover art, artist and title " + ("will appear on videos." if on else "are switched off for every video."), 5000)

    def add_visual(self):
        dlg = AddVisualDialog(self.state.shaders, self)
        if dlg.exec() and dlg.added:
            self.state.library_changed.emit()
            self.bottom.setCurrentWidget(self.visuals)
            if dlg.added.warnings:
                QMessageBox.information(self, APP, "Added, with a note:\n\n" + "\n".join(dlg.added.warnings))

    # ----------------------------------------------------------------- sessions
    def _maybe_save(self) -> bool:
        if not self.state.dirty or not self.state.plan.tracks:
            return True
        b = QMessageBox.question(self, APP, "Save changes to this mix first?",
                                 QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
                                 QMessageBox.StandardButton.Cancel)
        if b == QMessageBox.StandardButton.Cancel:
            return False
        if b == QMessageBox.StandardButton.Save:
            return self.save_session()
        return True

    def new_session(self):
        if self._maybe_save():
            self.stop()
            self.state.new()

    def open_session(self):
        if not self._maybe_save():
            return
        p, _ = QFileDialog.getOpenFileName(self, "Open a session", str(self.settings.value("last_session_dir", "")),
                                           SESSION_FILTER)
        if p:
            self.load_session(p)

    def load_session(self, path):
        try:
            self.stop()
            self.state.open(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, APP, f"Couldn't open that session:\n{e}")
            return
        self.settings.setValue("last_session_dir", str(Path(path).parent))
        if self.state.session.missing():
            QMessageBox.information(self, APP, "Some of this session's songs weren't found next to the file. "
                                               "Choose the folder that has your copy of them.")
            self._missing_check(force=True)
        if self.state.plan.tracks:
            self.state.select(0)
            QTimer.singleShot(0, lambda: self.timeline.fit_to(self.scroll.viewport().width()))

    def save_session(self, save_as: bool = False) -> bool:
        path = self.state.file
        if save_as is True or path is None:
            d = str(self.settings.value("last_session_dir", ""))
            p, _ = QFileDialog.getSaveFileName(self, "Save session", str(Path(d) / (self._mix_name() + ".lmm")), SESSION_FILTER)
            if not p:
                return False
            path = Path(p).with_suffix(".lmm")
            self.settings.setValue("last_session_dir", str(path.parent))
        try:
            self.state.save(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, APP, f"Couldn't save:\n{e}")
            return False
        self.statusBar().showMessage(f"Saved {path}", 4000)
        return True

    # -------------------------------------------------------------- refreshing
    def _on_changed(self):
        st = self.state
        self.list.blockSignals(True)
        self.list.clear()
        slots = planmod.timeline(st.plan) if st.plan.tracks else []
        for i, t in enumerate(st.plan.tracks):
            an = st.lib[t.song_id]
            start = slots[i].start / SR
            it = QListWidgetItem(f"{i + 1}.  {an.title}\n      {an.artist + '  ·  ' if an.artist else ''}"
                                 f"{an.camelot}  ·  {an.bpm:.0f} BPM  ·  at {fmt_time(start)}"
                                 + ("" if t.song_id in st.paths else "   — FILE NOT FOUND"))
            pm = QPixmap(12, 12)
            pm.fill(track_color(i, False))
            it.setIcon(QIcon(pm))
            self.list.addItem(it)
        if 0 <= st.sel < self.list.count():
            self.list.setCurrentRow(st.sel)
        self.list.blockSignals(False)
        total = slots[-1].end / SR if slots else 0
        bpms = [t.bpm for t in st.plan.tracks if t.bpm]
        tempo = (f"{min(bpms):.0f}–{max(bpms):.0f} BPM" if bpms and max(bpms) - min(bpms) > 1
                 else f"{st.plan.master_bpm:.0f} BPM")
        n = len(st.plan.tracks)
        self.info.setText(f"{n} song{'s' if n != 1 else ''}  ·  mix length {fmt_hms(total)}  ·  {tempo}   ")
        self._update_actions()

    def _on_selection(self):
        self.list.blockSignals(True)
        if 0 <= self.state.sel < self.list.count():
            self.list.setCurrentRow(self.state.sel)
        self.list.blockSignals(False)
        self._update_actions()

    def _update_actions(self):
        st = self.state
        has = bool(st.plan.tracks)
        for a in (self.a_gen, self.a_play, self.a_audio, self.a_video, self.a_both, self.a_vpreview, self.a_cue, self.a_save_as, self.a_refresh):
            a.setEnabled(has)
        self.a_stop.setEnabled(has)
        self.a_undo.setEnabled(st.can_undo())
        self.a_redo.setEnabled(st.can_redo())
        self.a_del.setEnabled(st.sel >= 0)
        self.b_remove.setEnabled(st.sel >= 0)
        self.b_up.setEnabled(st.sel > 0)
        self.b_down.setEnabled(0 <= st.sel < len(st.plan.tracks) - 1)
        self.a_locate.setEnabled(has)
        pl = self._playing() and self._preview_is_full
        self.a_play.setText("Pause" if pl else "Play")
        self.a_play.setIcon(theme.glyph_icon("❚❚" if pl else "▶"))

    def _update_title(self):
        self.setWindowTitle(f"{self.state.title()} — {APP}")

    def about(self):
        QMessageBox.about(self, APP, f"<b>{APP}</b> {__version__}<br>An offline auto-DJ: analyses your own music "
                                     "(tempo, key, song parts), beat-matches and blends it into one mixtape, and can "
                                     "make a video with Shadertoy visuals.<br><br>Everything runs on this computer; "
                                     "nothing is uploaded.")

    # ------------------------------------------------------------------ events
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        sess = [p for p in paths if p.lower().endswith(".lmm")]
        vis = [p for p in paths if p.lower().endswith(".lmv")]
        if vis:
            self.open_studio()
            self._studio.open_project(vis[0])
        elif sess and self._maybe_save():
            self.load_session(sess[0])
        elif paths:
            self.add_files(paths, ask_options=any(Path(p).is_dir() for p in paths))

    def closeEvent(self, ev):
        if self.task is not None:
            self.task.cancel()
            self.task.wait(5000)
        if not self._maybe_save():
            ev.ignore()
            return
        st_win = getattr(self, "_studio", None)
        if st_win is not None and st_win.isVisible() and not st_win.close():
            ev.ignore()
            return
        self._tick.stop()
        vp = getattr(self, "_vpreview", None)
        if vp is not None:
            vp.close()
        self.library.shutdown()
        self._player.close()
        self.thumbs.shutdown()
        shutil.rmtree(self.tmp, ignore_errors=True)
        ev.accept()


def run(argv):
    app = QApplication(argv)
    app.setApplicationName(APP)
    app.setOrganizationName(ORG)
    theme.apply_dark(app)
    icon = Path(__file__).resolve().parent.parent / "assets" / "icon.png"
    if getattr(sys, "_MEIPASS", None):
        icon = Path(sys._MEIPASS) / "assets" / "icon.png"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    w = MainWindow()
    w.show()
    for a in argv[1:]:
        if a.lower().endswith(".lmm") and Path(a).exists():
            w.load_session(a)
        elif a.lower().endswith(".lmv") and Path(a).exists():
            w.open_studio()
            w._studio.open_project(a)
        elif Path(a).exists():
            w.add_files([a])
    return app.exec()
