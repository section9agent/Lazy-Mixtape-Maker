"""Run long jobs (analysis, rendering, exporting) off the UI thread."""
from __future__ import annotations

import queue
import threading
import traceback

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from ..video import Cancelled


class Worker(QThread):
    progress = Signal(str, float)
    finished_ok = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def is_cancelled(self) -> bool:
        return self._cancel

    def _cb(self, msg, frac):
        if self._cancel:
            raise Cancelled("Cancelled")
        self.progress.emit(str(msg), float(frac))

    def run(self):
        try:
            res = self.fn(self._cb, self.is_cancelled)
            if self._cancel:
                self.cancelled.emit()
            else:
                self.finished_ok.emit(res)
        except Cancelled:
            self.cancelled.emit()
        except Exception as e:  # noqa: BLE001 - shown to the user
            self.failed.emit(f"{e}\n\n{traceback.format_exc(limit=3)}" if not str(e) else str(e))


class ThumbWorker(QThread):
    """Draws a small preview frame of each visual on a thread of its own (it owns
    its own OpenGL context), so the window never freezes on a heavy shader."""
    ready = Signal(str, QImage)
    unavailable = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.q: queue.Queue = queue.Queue()
        self._stop = False

    def request(self, shader):
        self.q.put(shader)

    def stop(self):
        self._stop = True
        self.q.put(None)

    def run(self):
        renderer = None
        try:
            from ..video import GLRenderer, preview_frame

            renderer = GLRenderer(256, 144)
        except Exception as e:  # noqa: BLE001
            self.unavailable.emit(str(e))
            return
        try:
            while not self._stop:
                sh = self.q.get()
                if sh is None:
                    break
                try:
                    fr = preview_frame(sh, 4.0, renderer=renderer)
                    img = QImage(fr.data, fr.shape[1], fr.shape[0], fr.shape[1] * 3, QImage.Format.Format_RGB888).copy()
                    self.ready.emit(sh.id, img)
                except Exception:  # noqa: BLE001
                    continue
        finally:
            if renderer:
                renderer.release()


import weakref

LIVE_FRAME_WORKERS: "weakref.WeakSet" = weakref.WeakSet()      # so a test (or shutdown) can stop any that are left


class FrameWorker(QThread):
    """Live preview: owns an OpenGL renderer on its own thread and draws only the *latest*
    requested picture, so a heavy shader slows the preview down instead of freezing the window.

    submit(fn, tag): fn(renderer) -> RGB bytes, bottom row first (as GLRenderer.composite returns)."""
    frame = Signal(QImage, object)
    unavailable = Signal(str)
    failed = Signal(str, object)

    def __init__(self, width: int = 480, height: int = 270, parent=None):
        super().__init__(parent)
        self.size = (width, height)
        self._job = None
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = False
        LIVE_FRAME_WORKERS.add(self)

    def submit(self, fn, tag=None):
        with self._lock:
            self._job = (fn, tag)
        self._wake.set()

    def stop(self):
        self._stop = True
        self._wake.set()

    def run(self):
        try:
            from ..video import GLRenderer
            r = GLRenderer(*self.size)
        except Exception as e:  # noqa: BLE001
            self.unavailable.emit(str(e))
            return
        w, h = self.size
        try:
            while not self._stop:
                self._wake.wait()
                self._wake.clear()
                if self._stop:
                    break
                with self._lock:
                    job, self._job = self._job, None
                if job is None:
                    continue
                fn, tag = job
                try:
                    raw = fn(r)
                    import numpy as np
                    arr = np.ascontiguousarray(np.frombuffer(raw, np.uint8).reshape(h, w, 3)[::-1])
                    img = QImage(arr.data, w, h, w * 3, QImage.Format.Format_RGB888).copy()
                    self.frame.emit(img, tag)
                except Exception as e:  # noqa: BLE001
                    self.failed.emit(str(e), tag)
        finally:
            r.release()
