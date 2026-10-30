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
