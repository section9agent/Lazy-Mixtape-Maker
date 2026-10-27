"""Live video preview: a window that shows the mix's visuals in real time, following the main timeline.

It draws with the very same code as the video exporter (FrameComposer), so what you see here -
the visuals, their blends, the cover/artist/title card - is what the exported video will show.
It is driven by the timeline's playhead: press Play and it plays, drag the timeline and it scrubs."""
from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .. import audio_io
from ..plan import SR, timeline as build_timeline
from ..video import AudioTexture, FrameComposer, Segment, frame_schedule, resolve_assignments
from .panels import fmt_time
from .workers import FrameWorker

TEXTURE_SR = 11025


def _decimated_mono(path: str, out: list, stop: threading.Event):
    """Read the rendered preview and keep a small mono copy for the music-reactive shaders."""
    import soundfile as sf
    try:
        chunks = []
        with sf.SoundFile(path) as f:
            for block in f.blocks(blocksize=SR * 20, dtype="float32", always_2d=True):
                if stop.is_set():
                    return
                m = block.mean(axis=1)
                n = len(m) // 4 * 4
                chunks.append(m[:n].reshape(-1, 4).mean(axis=1))
        out.append(np.concatenate(chunks) if chunks else np.zeros(1, np.float32))
    except Exception:  # noqa: BLE001
        out.append(None)


class VideoPreviewWindow(QWidget):
    def __init__(self, main):
        super().__init__(None, Qt.WindowType.Window)
        self.main = main
        self.setWindowTitle("Video preview")
        self.resize(720, 470)
        self._comp: FrameComposer | None = None
        self._audio = AudioTexture(None)
        self._audio_path: str | None = None
        self._mono_out: list = []
        self._stop = threading.Event()
        self._last = None
        self._dirty = True
        self._covers: dict[str, str | None] = {}

        lay = QVBoxLayout(self)
        self.screen = QLabel("Starting…")
        self.screen.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.screen.setMinimumSize(320, 180)
        self.screen.setStyleSheet("background:#0b0b10;border-radius:6px;color:#8b93a1")
        lay.addWidget(self.screen, 1)
        row = QHBoxLayout()
        self.b_play = QPushButton("▶ Play")
        self.b_play.setFixedHeight(34)
        self.b_play.clicked.connect(main.toggle_play)
        self.time = QLabel("0:00")
        self.note = QLabel()
        self.note.setStyleSheet("color:#8b93a1")
        self.note.setWordWrap(True)
        self.overlay = QCheckBox("Cover, artist and title")
        self.overlay.setChecked(bool(main.state.video.show_overlay))
        self.overlay.toggled.connect(lambda on: main.state.edit_video(lambda v: setattr(v, "show_overlay", bool(on))))
        row.addWidget(self.b_play); row.addWidget(self.time); row.addWidget(self.note, 1); row.addWidget(self.overlay)
        lay.addLayout(row)

        self.worker = FrameWorker(480, 270, self)
        self.worker.frame.connect(self._frame)
        self.worker.unavailable.connect(lambda m: self.screen.setText("The live preview needs OpenGL 3.3.\n" + m[:240]))
        self.worker.failed.connect(lambda m, _t: self.note.setText("Couldn't draw a frame: " + m[-120:]))
        self.worker.start()
        main.state.changed.connect(self._invalidate)
        main.state.library_changed.connect(self._invalidate)
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    # -------------------------------------------------------------- state
    def _invalidate(self):
        self._comp = None
        self._dirty = True
        self.overlay.blockSignals(True)
        self.overlay.setChecked(bool(self.main.state.video.show_overlay))
        self.overlay.blockSignals(False)

    def _duration(self) -> float:
        slots = build_timeline(self.main.state.plan) if self.main.state.plan.tracks else []
        return slots[-1].end / SR if slots else 0.0

    def _composer(self) -> FrameComposer | None:
        st = self.main.state
        if not st.plan.tracks:
            return None
        if self._comp is None:
            seconds = self._duration()
            starts, wins = frame_schedule(st.plan, seconds)
            chosen = resolve_assignments(st.plan, st.lib, st.video, st.shaders)
            segs = []
            for t, sid, s0 in zip(st.plan.tracks, chosen, starts):
                if t.song_id not in self._covers:
                    cover = None
                    p = st.paths.get(t.song_id)
                    if p:
                        out = self.main.tmp / f"pv_cover_{len(self._covers)}.jpg"
                        try:
                            cover = str(out) if audio_io.extract_cover(p, out) else None
                        except Exception:  # noqa: BLE001
                            cover = None
                    self._covers[t.song_id] = cover
                an = st.lib[t.song_id]
                segs.append(Segment(t.uid, s0, sid, an.artist, an.title, self._covers[t.song_id]))
            self._comp = FrameComposer(segs, wins, seconds, st.video, st.shaders)
        return self._comp

    def _sync_audio(self):
        """Once the mix has been rendered for playback, feed its sound to music-reactive shaders."""
        path = self.main.state.preview_path
        if self._mono_out:
            mono = self._mono_out.pop()
            self._mono_out.clear()
            if mono is not None and path == self._audio_path:
                self._audio = AudioTexture(mono[None, :], TEXTURE_SR)
                self._dirty = True
        if path != self._audio_path:
            self._audio_path = path
            self._stop.set()
            self._stop = threading.Event()
            self._audio = AudioTexture(None)
            self._dirty = True
            if path and Path(path).exists():
                threading.Thread(target=_decimated_mono, args=(path, self._mono_out, self._stop), daemon=True).start()

    # --------------------------------------------------------------- loop
    def _tick(self):
        if not self.isVisible():
            return
        m = self.main
        self._sync_audio()
        playing = m._playing()
        self.b_play.setText("❚❚ Pause" if playing else "▶ Play")
        t = m.timeline.playhead
        self.time.setText(f"{fmt_time(t)} / {fmt_time(self._duration())}")
        reactive = self._audio_path is not None and self._audio.mono is not None
        self.note.setText("" if reactive else "Press Play once: the mix is rendered and the visuals then react to your music.")
        if not (playing or self._dirty or t != self._last):
            return
        comp = self._composer()
        if comp is None:
            self.screen.setText("Add songs to see the visuals")
            return
        self._last, self._dirty = t, False
        audio, k = self._audio, int(t * 30)

        def job(r):
            if r.audio is not audio:
                r.audio, r.last_t = audio, -1.0
            return comp.draw(r, t, k)
        self.worker.submit(job)

    def _frame(self, img, _tag):
        pm = QPixmap.fromImage(img)
        self.screen.setPixmap(pm.scaled(self.screen.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._dirty = True

    def showEvent(self, e):
        super().showEvent(e)
        self._dirty = True

    def closeEvent(self, e):
        self._shutdown()
        super().closeEvent(e)

    def _shutdown(self):
        self.timer.stop()
        self._stop.set()
        self.worker.stop()
        self.worker.wait(3000)
