"""The update check and installer, as a mixin for the main window."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from .. import __version__, updater


class CheckThread(QThread):
    done = Signal(object)          # Update or None
    failed = Signal(str)

    def run(self):
        try:
            self.done.emit(updater.check())
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class InstallThread(QThread):
    progress = Signal(int, int)
    ready = Signal(str, str)       # new version's folder, work folder
    failed = Signal(str)

    def __init__(self, up, work: Path, parent=None):
        super().__init__(parent)
        self.up, self.work, self.cancelled = up, work, False

    def run(self):
        try:
            arc = updater.download(self.up, self.work, lambda d, t: self.progress.emit(d, t), lambda: self.cancelled)
            new_root = updater.extract(arc, self.work / "new")
            self.ready.emit(str(new_root), str(self.work))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class UpdateMixin:
    def init_updates(self):
        self._upd_thread = None
        self._upd_manual = False
        QTimer.singleShot(5000, self._auto_update_check)

    def _auto_update_check(self):
        if updater.due():
            self.check_updates(False)

    def check_updates(self, manual: bool = True):
        if self._upd_thread is not None and self._upd_thread.isRunning():
            return
        self._upd_manual = manual
        t = self._upd_thread = CheckThread(self)
        t.done.connect(self._update_result)
        t.failed.connect(self._update_failed)
        t.start()

    def _update_failed(self, msg):
        if self._upd_manual:
            QMessageBox.information(self, "Updates", msg + "\n\nCheck your internet connection and try again.")

    def _update_result(self, up):
        updater.mark_checked()
        if up is None:
            if self._upd_manual:
                QMessageBox.information(self, "Updates", f"You're up to date (version {__version__}).")
            return
        if not self._upd_manual and updater.skipped(up.tag):
            return
        self._offer_update(up)

    def _offer_update(self, up):
        can = bool(up.asset_url) and updater.install_target() is not None
        box = QMessageBox(self)
        box.setWindowTitle("Update available")
        box.setText(f"<b>{up.name}</b> is available (you have version {__version__}).")
        if up.notes.strip():
            box.setDetailedText(up.notes)
        b_inst = box.addButton("Install and restart" if can else "Open download page", QMessageBox.ButtonRole.AcceptRole)
        b_later = box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        b_skip = box.addButton("Skip this version", QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(b_inst)
        box.exec()
        c = box.clickedButton()
        if c is b_skip:
            updater.skip(up.tag)
        elif c is b_inst:
            if can:
                self.install_update(up)
            else:
                QDesktopServices.openUrl(QUrl(up.page or updater.RELEASES_PAGE))

    def install_update(self, up):
        if not self._maybe_save():
            return
        work = Path(tempfile.mkdtemp(prefix="lmm_update_"))
        dlg = self._upd_dlg = QProgressDialog("Downloading the update…", "Cancel", 0, 100, self)
        dlg.setWindowTitle("Updating")
        dlg.setMinimumDuration(0)
        t = self._upd_install = InstallThread(up, work, self)
        t.progress.connect(lambda d, tot: dlg.setValue(int(d * 100 / tot)) if tot else dlg.setValue(0))
        dlg.canceled.connect(lambda: setattr(t, "cancelled", True))
        t.ready.connect(lambda new, w: self._finish_install(new, w, dlg))
        t.failed.connect(lambda m: self._install_failed(m, dlg, work))
        t.start()

    def _install_failed(self, msg, dlg, work):
        dlg.close()
        shutil.rmtree(work, ignore_errors=True)
        if msg != "Cancelled":
            QMessageBox.warning(self, "Update", f"The update couldn't be installed:\n{msg}\n\n"
                                                f"You can download it yourself from {updater.RELEASES_PAGE}")

    def _finish_install(self, new_root, work, dlg):
        dlg.close()
        target = updater.install_target()
        try:
            _, cmd = updater.helper_script(Path(new_root), target, os.getpid(), Path(work))
            updater.launch_helper(cmd)
        except Exception as e:  # noqa: BLE001
            self._install_failed(str(e), dlg, Path(work))
            return
        self.state.dirty = False
        QTimer.singleShot(0, self.close)           # the helper swaps the files once this window has gone
