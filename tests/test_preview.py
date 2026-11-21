"""Short previews: rendering just one transition, or four songs, and placing them on the mix's timeline."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
import synth  # noqa: E402

from lazy_mixtape_maker import audio_io  # noqa: E402
from lazy_mixtape_maker.audio_io import SR  # noqa: E402
from lazy_mixtape_maker.engine import new_session, preview_songs, preview_window  # noqa: E402
from lazy_mixtape_maker.plan import MixSettings, timeline  # noqa: E402
from lazy_mixtape_maker.render import render_mix  # noqa: E402

SHORT = [("intro", 4), ("verse", 8), ("chorus", 8), ("verse", 8), ("chorus", 8), ("outro", 4)]


@pytest.fixture(scope="module")
def session(tmp_path_factory):
    d = tmp_path_factory.mktemp("songs")
    for name, bpm, root, minor in (("one", 120, 9, True), ("two", 124, 0, True), ("three", 122, 7, False),
                                   ("four", 118, 2, True), ("five", 121, 4, True)):
        synth.make_song(d / f"Artist - {name}.wav", bpm, root, minor, structure=SHORT, fmt="wav",
                        tags={"title": name, "artist": "Artist"})
    s, errors = new_session(audio_io.list_audio_files([d]), MixSettings(seed=1, overlap_bars=4), name="Prev")
    assert not errors
    return s


def test_which_songs_a_preview_covers(session):
    plan = session.plan
    slots = timeline(plan)
    n = len(plan.tracks)
    assert preview_songs(plan, "mix", 30.0) is None
    for i in range(n - 1):
        mid = (slots[i + 1].start + slots[i + 1].overlap_in / 2) / SR
        assert preview_songs(plan, "transition", mid + 1.0) == (i, i + 1)
        first, last = preview_songs(plan, "four", mid)
        assert last - first == 3 and first <= i and i + 1 <= last          # four songs around that transition
    assert preview_songs(plan, "four", 0.0) == (0, 3)
    assert preview_songs(plan, "four", 1e6) == (n - 4, n - 1)


@pytest.mark.parametrize("scope", ["transition", "four"])
def test_window_sounds_exactly_like_that_part_of_the_mix(session, scope):
    plan, lib, paths = session.plan, session.library, session.paths
    slots = timeline(plan)
    at = (slots[2].start + slots[2].overlap_in / 2) / SR             # the transition from song 2 into song 3
    t0, t1 = preview_window(plan, scope, at)
    assert t0 < at < t1
    full = render_mix(plan, lib, paths)
    part = render_mix(plan, lib, paths, window=(t0, t1))
    assert part.shape == (2, int(t1 * SR) - int(t0 * SR))
    assert part.shape[1] < full.shape[1] * (0.6 if scope == "transition" else 0.95)   # much shorter than the mix
    ref = full[:, int(t0 * SR):int(t0 * SR) + part.shape[1]]
    for k in range(0, part.shape[1] - SR, SR):                      # every second of it, blend included
        a, b = part[:, k:k + SR].mean(axis=0), ref[:, k:k + SR].mean(axis=0)
        if np.std(b) > 1e-3:
            assert float(np.corrcoef(a, b)[0, 1]) > 0.97, (k / SR, scope)


def test_window_is_quicker_to_render(session):
    import time
    plan, lib, paths = session.plan, session.library, session.paths
    t = time.monotonic()
    render_mix(plan, lib, paths)
    whole = time.monotonic() - t
    t = time.monotonic()
    render_mix(plan, lib, paths, window=preview_window(plan, "transition", 60.0))
    assert time.monotonic() - t < whole * 0.6


def test_play_button_previews_just_a_transition(session, tmp_path, monkeypatch):
    import os
    import time
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("LMM_AUDIO_BACKEND", "null")
    monkeypatch.setenv("LMM_DATA_DIR", str(tmp_path / "data"))
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from lazy_mixtape_maker.gui.main_window import MainWindow
    from lazy_mixtape_maker.session import save_session
    save_session(session, tmp_path / "p.lmm")
    w = MainWindow()
    w.show()
    w.load_session(tmp_path / "p.lmm")

    def wait_for(cond, secs=120):
        end = time.monotonic() + secs
        while time.monotonic() < end and not cond():
            app.processEvents()
            time.sleep(0.03)
        return cond()

    slots = timeline(w.state.plan)
    at = (slots[3].start + slots[3].overlap_in / 2) / SR
    w.scope.setCurrentIndex(w.scope.findData("transition"))
    w._seek(at)
    w.toggle_play()
    assert wait_for(lambda: w._pv is not None)
    pv = w._pv
    assert pv["scope"] == "transition" and pv["t0"] < at < pv["t1"] and pv["t1"] - pv["t0"] < 60
    assert w.state.preview_path is None                    # (a short preview isn't the whole mix)
    import soundfile as sf
    assert abs(sf.info(pv["path"]).duration - (pv["t1"] - pv["t0"])) < 0.2
    # the playhead follows along on the mix's own timeline
    if w._player.loaded:
        w._player.seek(5.0)
        w._on_tick() if w._playing() else None
        w._seek(pv["t0"] + 5.0)
        assert w.timeline.playhead == pytest.approx(pv["t0"] + 5.0)
    # pressing Play again inside it reuses it; changing the mix makes it out of date
    assert w._player.loaded, w._player.error
    first = pv["path"]
    w._player.pause()
    w.toggle_play()
    assert w._pv["path"] == first
    w._player.pause()
    w.state.preview_path = None
    assert not w._pv_valid("transition")
    # the whole mix still works the old way
    w.scope.setCurrentIndex(w.scope.findData("mix"))
    w._player.pause()
    w.toggle_play()
    assert wait_for(lambda: w._pv is not None and w._pv["scope"] == "mix")
    assert w.state.preview_path and w._pv["t0"] == 0.0
    w._player.pause()
    w.state.dirty = False
    w.close()
