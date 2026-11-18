"""Deep analysis (All-In-One): turning its result into the app's terms, choosing per song, undo, the window.
The neural network itself only runs in the packaged "with stems" build (checked there by the smoke test);
here a stand-in writes the kind of result it gives."""
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LMM_AUDIO_BACKEND", "null")
sys.path.insert(0, str(Path(__file__).parent))

from lazy_mixtape_maker import deep, stems  # noqa: E402
from lazy_mixtape_maker.analysis import Section, SongAnalysis  # noqa: E402


def fake_result(bpm=123.0, first_down=0.37, dur=120.0):
    beat = 60.0 / bpm
    beats = list(np.arange(first_down - beat, dur, beat))
    downs = [b for i, b in enumerate(beats) if (i - 1) % 4 == 0]
    segs = [("start", 0, first_down), ("intro", first_down, 16), ("verse", 16, 40), ("verse", 40, 60), ("chorus", 60, 80),
            ("inst", 80, 90), ("outro", 90, 118), ("end", 118, dur)]
    return {"bpm": bpm, "beats": beats, "downbeats": downs, "beat_positions": [],
            "segments": [{"start": a, "end": b, "label": l} for l, a, b in segs]}


def test_to_fields():
    an = SongAnalysis(id="x", duration=120.0, bpm=100.0, beat_period=0.6, grid_origin=0.1, bar_energy=[0.2, 0.9] * 40,
                      bar_energy_origin=0.0)
    f = deep.to_fields(an, fake_result())
    assert f["bpm"] == pytest.approx(123.0, abs=0.05) and f["beat_period"] == pytest.approx(60 / 123.0, rel=1e-3)
    bar = 4 * f["beat_period"]
    assert (f["grid_origin"] - 0.37) % bar == pytest.approx(0, abs=0.01) or (0.37 - f["grid_origin"]) % bar < 0.01
    labels = [(s.label, round(s.start), round(s.end)) for s in f["sections"]]
    assert labels == [("intro", 0, 16), ("verse", 16, 60), ("chorus", 60, 80), ("bridge", 80, 90), ("outro", 90, 118)]
    assert all(0 <= s.energy <= 1 for s in f["sections"])
    slow = deep.to_fields(an, fake_result(bpm=68.0))                  # folded into the app's 80-160 range
    assert slow["bpm"] == pytest.approx(136.0, abs=0.1)
    assert "123.0 BPM" in deep.summary(an, f["sections"], f["bpm"], f["grid_origin"]) and "chorus 1:00" in \
        deep.summary(an, f["sections"], f["bpm"], f["grid_origin"])


@pytest.fixture()
def mixwin(tmp_path, monkeypatch):
    monkeypatch.setenv("LMM_DATA_DIR", str(tmp_path / "data"))
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from test_oct30 import _mix_window
    w, _ = _mix_window(tmp_path)
    return w


def fake_split(path, song_id=None, progress=None, cancel=None, **k):
    d = stems.song_dir(song_id)
    d.mkdir(parents=True, exist_ok=True)
    for s in stems.STEMS:
        sf.write(str(d / f"{s}.flac"), np.zeros((2205, 2), np.float32), 44100)
    (d / "stems.json").write_text(json.dumps({"stems": sorted(stems.STEMS), "lag": 0.0}))
    return stems.cached(song_id)


def test_choose_per_song_with_undo_and_the_window(mixwin, monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox
    from lazy_mixtape_maker.gui.deep_dialog import DeepDialog
    w = mixwin
    st = w.state
    ids = list(dict.fromkeys(t.song_id for t in st.plan.tracks))
    calls = []

    def fake_worker(cmd, progress, cancel, status=None):
        calls.append(cmd)
        assert cmd[-4] == "deep" and Path(cmd[-3]).is_dir()
        sid = Path(cmd[-3]).name
        Path(cmd[-2]).write_text(json.dumps(fake_result(bpm=st.lib[sid].bpm + 3.0, dur=st.lib[sid].duration)))
        if progress:
            progress(1.0)
        return {"event": "done"}
    monkeypatch.setattr(stems, "_run_worker", fake_worker)
    monkeypatch.setattr(stems, "engine_python", lambda: sys.executable)
    monkeypatch.setattr(stems, "split", fake_split)
    monkeypatch.setattr(deep, "available", lambda: True)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)

    dlg = DeepDialog(w)
    assert dlg.table.rowCount() == len(ids) and "not split" in dlg.table.item(0, 2).text()
    assert dlg.b_run.isEnabled() and not dlg.b_all.isEnabled()
    dlg.b_run.click()
    end = time.time() + 30
    while w.task is not None and time.time() < end:
        QApplication.processEvents()
        time.sleep(0.01)
    assert len(calls) == len(ids) and all(deep.cached(s) for s in ids)
    assert "BPM" in dlg.table.item(0, 2).text() and not dlg.b_run.isEnabled() and dlg.b_all.isEnabled()

    sid = ids[0]
    before = (st.lib[sid].bpm, [s.label for s in st.lib[sid].sections])
    rate_before = st.plan.tracks[0].rate
    box = dlg.table.cellWidget(0, 3)
    box.setCurrentIndex(1)                                           # use All-In-One for the first song
    assert deep.in_use(st.session.extra, sid)
    assert st.lib[sid].bpm == pytest.approx(before[0] + 3.0, abs=0.05)
    assert [s.label for s in st.lib[sid].sections][:2] == ["intro", "verse"]
    assert st.plan.tracks[0].rate != rate_before or st.plan.tracks[0].bpm != pytest.approx(before[0])  # the mix follows
    st.undo()                                                        # Undo switches it back
    assert not deep.in_use(st.session.extra, sid) and st.lib[sid].bpm == pytest.approx(before[0])
    assert [s.label for s in st.lib[sid].sections] == before[1]
    st.redo()
    assert deep.in_use(st.session.extra, sid)
    dlg.b_none.click()
    assert not st.session.extra.get("deep_orig") and st.lib[sid].bpm == pytest.approx(before[0])
    dlg.b_all.click()
    assert all(deep.in_use(st.session.extra, s) for s in ids)

    # it survives saving and opening the session again
    f = Path(st.paths[sid]).parent / "deep-test.lmm"
    st.save(f)
    bpm_now = st.lib[sid].bpm
    st.new()
    st.open(f)
    assert deep.in_use(st.session.extra, sid) and st.lib[sid].bpm == pytest.approx(bpm_now)
    st.undo() if st._undo else None
    dlg.close()
    st.dirty = False
    w.close()


def test_not_available_explains(mixwin, monkeypatch):
    from lazy_mixtape_maker.gui.deep_dialog import DeepDialog
    monkeypatch.setattr(deep, "available", lambda: False)
    dlg = DeepDialog(mixwin)
    assert not dlg.b_run.isEnabled() and "with stems" in dlg.note.text()
    with pytest.raises(deep.DeepError):
        deep.run(mixwin.state.paths[mixwin.state.plan.tracks[0].song_id], mixwin.state.plan.tracks[0].song_id)
    dlg.close()
    mixwin.state.dirty = False
    mixwin.close()
