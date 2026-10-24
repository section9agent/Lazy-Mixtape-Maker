"""run_task(): do a long job on a worker thread behind a progress dialog (shared by the windows)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from .workers import Worker

APP = "Lazy Mixtape Maker"


class TaskMixin:
    task = None

    def run_task(self, title, fn, on_done, on_fail=None):
        if self.task is not None:
            self.statusBar().showMessage("Please wait for the current job to finish.", 4000)
            return
        w = Worker(fn, self)
        dlg = QProgressDialog(title, "Cancel", 0, 1000, self)
        dlg.setWindowTitle(APP)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False); dlg.setAutoReset(False)
        dlg.setMinimumWidth(460)
        dlg.canceled.connect(w.cancel)
        w.progress.connect(lambda msg, f: (dlg.setLabelText(msg), dlg.setValue(int(max(0, min(1, f)) * 1000))))

        def finish():
            dlg.close(); dlg.deleteLater()
            self.task = None
            w.deleteLater()

        def ok(res):
            finish()
            try:
                on_done(res)
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(self, APP, str(e))

        def bad(msg):
            finish()
            if on_fail and on_fail(msg):
                return
            QMessageBox.warning(self, APP, msg)

        w.finished_ok.connect(ok)
        w.failed.connect(bad)
        w.cancelled.connect(lambda: (finish(), self.statusBar().showMessage("Cancelled", 3000)))
        self.task = w
        dlg.setValue(0)
        w.start()
