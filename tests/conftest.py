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
