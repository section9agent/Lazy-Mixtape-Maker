import os

os.environ["LMM_NO_UPDATE_CHECK"] = "1"      # tests never look for updates on GitHub

import pytest


@pytest.fixture(autouse=True)
def _stop_leftover_drawing_threads():
    """A test that fails half way can leave a live-preview drawing thread running; Qt aborts the whole run
    ("QThread: Destroyed while thread is still running") if one is still alive at exit. Stop them after every test."""
    yield
    try:
        from lazy_mixtape_maker.gui.workers import LIVE_FRAME_WORKERS
    except Exception:  # noqa: BLE001
        return
    for w in list(LIVE_FRAME_WORKERS):
        try:
            w.stop()
            w.wait(3000)
        except Exception:  # noqa: BLE001
            pass


def pytest_runtest_logreport(report):
    """On GitHub Actions, turn each failed test into an annotation so the reason is visible on the run's page."""
    import os
    if os.environ.get("GITHUB_ACTIONS") != "true" or not report.failed:
        return
    text = str(report.longreprtext)[-2500:]
    text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"\n::error title=FAILED {report.nodeid} ({report.when})::{text}", flush=True)


@pytest.fixture(autouse=True)
def _no_project_carried_over():
    """Each test starts with no current project (project.py keeps one for the whole app)."""
    from lazy_mixtape_maker import project
    project.set_current(None)
    yield
    project.set_current(None)


def pytest_sessionfinish(session, exitstatus):
    """Stop any Qt thread still running when the tests end: Qt aborts the whole process ("QThread: Destroyed
    while thread is still running") if one is alive at exit, which would turn a passing run into a crash."""
    import gc
    try:
        from PySide6.QtCore import QThread
    except Exception:  # noqa: BLE001
        return
    found = [o for o in gc.get_objects() if isinstance(o, QThread)]
    try:                                    # (and threads owned by windows, which Python may not be tracking)
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            for w in app.topLevelWidgets():
                found += w.findChildren(QThread)
            found += app.findChildren(QThread)
    except Exception:  # noqa: BLE001
        pass
    for o in found:
        try:
            if o.isRunning():
                print(f"\nstopping a leftover thread: {type(o).__name__}", flush=True)
                for name in ("stop", "cancel", "requestInterruption", "quit"):
                    fn = getattr(o, name, None)
                    if callable(fn):
                        try:
                            fn()
                        except Exception:  # noqa: BLE001
                            pass
                o.wait(5000)
        except (RuntimeError, ReferenceError):
            continue
