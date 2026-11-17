"""Stem transitions, checked by ear-free arithmetic: each test song carries a steady "bass" tone and a steady
"vocal" tone of its own frequency, stored as its bass and vocal stems, so the level of every stem can be read
straight off the rendered mix."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

sys.path.insert(0, str(Path(__file__).parent))
import synth  # noqa: E402

from lazy_mixtape_maker import plan as planmod, render, stems  # noqa: E402
from lazy_mixtape_maker.audio_io import SR, file_id  # noqa: E402
from lazy_mixtape_maker.engine import new_session  # noqa: E402
from lazy_mixtape_maker.plan import MixSettings, timeline  # noqa: E402

SHAPE = [("intro", 4), ("verse", 8), ("chorus", 8), ("outro", 4)]
TONES = {"a": (43.0, 1234.5), "b": (67.0, 1567.8)}
QUIET_BASS = 0.2        # "gone", for a bass tone: the synthetic music's own bass leaks about 0.12 into the reading          # (bass, vocal) pilot tones of each song


def make(tmp, name, bpm, delay=0.0, with_lag=True, shape=SHAPE):
    """A song = synthetic music + its two pilot tones; its stems go straight into the stems cache."""
    f = tmp / f"{name}.wav"
    synth.make_song(f, bpm, 0 if name == "a" else 7, True, structure=shape)
    base, sr = sf.read(str(f), always_2d=True)
    t = np.arange(len(base)) / sr
    bass = (0.1 * np.sin(2 * np.pi * TONES[name][0] * t))[:, None].repeat(base.shape[1], 1)
    vox = (0.1 * np.sin(2 * np.pi * TONES[name][1] * t))[:, None].repeat(base.shape[1], 1)
    sf.write(str(f), base + bass + vox, sr, subtype="FLOAT")
    d = stems.song_dir(file_id(f))
    d.mkdir(parents=True)
    pad = np.zeros((int(round(delay * sr)), base.shape[1]))
    for stem, audio in (("bass", bass), ("vocals", vox), ("other", base), ("drums", np.zeros_like(base))):
        sf.write(str(d / f"{stem}.flac"), np.concatenate([pad, audio]), sr)
    meta = {"stems": ["bass", "drums", "other", "vocals"]}
    if with_lag:
        meta["lag"] = delay
    (d / "stems.json").write_text(json.dumps(meta))
    return f


def level(mix, freq, a, b):
    """Amplitude of a steady tone of `freq` between samples a and b of the mix (averaged over short windows, so
    the tiny phase steps of a time-stretched song don't count against it)."""
    win = 32768 if freq < 200 else 8192          # low tones need a long look to be told from the music's own bass
    x = mix[:, a:b].mean(axis=0)
    w = np.hanning(win)
    probe = np.exp(-2j * np.pi * freq * np.arange(win) / SR) * w
    amps = [2 * abs(np.sum(x[i:i + win] * probe)) / w.sum() for i in range(0, len(x) - win, win // 2)]
    return float(np.mean(amps))


def mixdown(tmp, kind, bpm_b=120.0, **kw):
    a, b = make(tmp, "a", 120.0, **kw), make(tmp, "b", bpm_b, **kw)
    s, _ = new_session([a, b], MixSettings(order="given", key_match=False, transition_style="eq_swap", use_effects=False))
    planmod.set_transition(s.plan, s.library, 0, kind, 32)
    notes = []
    mix = render.render_mix(s.plan, s.library, s.paths, notes=notes)
    sl = timeline(s.plan)
    start, L = sl[1].start, sl[1].overlap_in
    assert L > 6 * SR                                                   # a real overlap to measure in

    def at(u0, u1, song, which):                                        # level of a pilot tone, relative to its solo level
        f = TONES[song][0 if which == "bass" else 1]
        solo = (start - 5 * SR, start - SR) if song == "a" else (start + L + SR, start + L + 5 * SR)
        return level(mix, f, start + int(u0 * L), start + int(u1 * L)) / level(mix, f, *solo)
    return at, notes, s


@pytest.fixture()
def tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("LMM_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def test_curves_are_sane():
    for kind in render.STEM_KINDS:
        out, inn = render.stem_curves(kind, 1000)
        assert set(out) == set(inn) == set(render.STEM_NAMES)
        for s in render.STEM_NAMES:
            assert out[s][0] == pytest.approx(1) and out[s][-1] == pytest.approx(0, abs=1e-6)
            assert inn[s][0] == pytest.approx(0, abs=1e-6) and inn[s][-1] == pytest.approx(1)
            assert np.all(np.diff(out[s]) <= 1e-9) and np.all(np.diff(inn[s]) >= -1e-9)
    for kind in planmod.STEM_TYPES:
        assert kind in render.STEM_KINDS and kind in planmod.TRANSITION_TYPES


def test_bass_swap_uses_the_real_bass(tmp):
    at, notes, _ = mixdown(tmp, "stem_bass")
    assert not notes
    assert at(0.05, 0.4, "a", "bass") > 0.9 and at(0.05, 0.4, "b", "bass") < QUIET_BASS     # first half: only the old bass
    assert at(0.6, 0.95, "a", "bass") < QUIET_BASS and at(0.6, 0.95, "b", "bass") > 0.9     # second half: only the new bass
    assert at(0.05, 0.4, "a", "vocals") > 0.9 and 0.3 < at(0.1, 0.4, "b", "vocals") < 0.9   # the rest simply blends


def test_stem_blend_keeps_one_singer_at_a_time(tmp):
    at, _, _ = mixdown(tmp, "stem_blend")
    assert at(0.05, 0.38, "a", "vocals") > 0.9 and at(0.05, 0.38, "b", "vocals") < 0.08
    assert at(0.62, 0.95, "a", "vocals") < 0.08 and at(0.62, 0.95, "b", "vocals") > 0.9
    assert at(0.6, 0.95, "a", "bass") < QUIET_BASS and at(0.6, 0.95, "b", "bass") > 0.9


def test_mashup_old_singer_over_new_music(tmp):
    at, _, _ = mixdown(tmp, "stem_mashup")
    assert at(0.35, 0.8, "a", "vocals") > 0.9          # the old singer carries on ...
    assert at(0.35, 0.8, "a", "bass") < QUIET_BASS           # ... without the old bass
    assert at(0.35, 0.8, "b", "bass") > 0.9            # over the new song's bass
    assert at(0.35, 0.8, "b", "vocals") < 0.08         # while the new singer waits


def test_new_singer_over_old_music(tmp):
    at, _, _ = mixdown(tmp, "stem_vocal_in")
    assert at(0.25, 0.65, "b", "vocals") > 0.9 and at(0.25, 0.65, "a", "vocals") < 0.08
    assert at(0.25, 0.65, "a", "bass") > 0.9 and at(0.25, 0.65, "b", "bass") < QUIET_BASS


def test_stems_follow_a_stretched_song(tmp):
    """Different tempos: the songs are time-stretched, and their stems must stay in step with them to cancel.
    (Stretching blurs these steady test tones, so each reading is compared with the same mix as a crossfade.)"""
    a, b = make(tmp, "a", 120.0), make(tmp, "b", 126.0)
    s, _ = new_session([a, b], MixSettings(order="given", key_match=False, transition_style="eq_swap", use_effects=False))
    assert any(abs(r - 1) > 0.005 for t in s.plan.tracks for r in (t.rate, t.rate_in or t.rate, t.rate_out or t.rate))
    planmod.set_transition(s.plan, s.library, 0, "crossfade", 32)
    ref = render.render_mix(s.plan, s.library, s.paths)
    planmod.set_transition(s.plan, s.library, 0, "stem_mashup", 32)
    mix = render.render_mix(s.plan, s.library, s.paths)
    sl = timeline(s.plan)
    start, L = sl[1].start, sl[1].overlap_in
    lo, hi = start + int(0.4 * L), start + int(0.6 * L)             # mid-overlap: a crossfade has both songs at ~0.7
    for song, which in (("a", 0), ("b", 1)):                         # the old bass and the new singer are taken out
        f = TONES[song][which]
        assert level(mix, f, lo, hi) < 0.25 * level(ref, f, lo, hi)
    for song, which in (("a", 1), ("b", 0)):                         # the old singer and the new bass are at full level
        f = TONES[song][which]
        assert level(mix, f, lo, hi) > 1.2 * level(ref, f, lo, hi)


def test_stems_that_run_late_are_lined_up(tmp):
    """Stems decoded 20 ms later than the song (as with some MP3s) are measured and shifted back."""
    at, _, s = mixdown(tmp, "stem_mashup", delay=0.02, with_lag=False)
    for t in s.plan.tracks:
        assert stems.lag(t.song_id, s.paths[t.song_id]) == pytest.approx(0.02, abs=2 / SR)
    assert at(0.35, 0.8, "a", "bass") < QUIET_BASS and at(0.35, 0.8, "b", "vocals") < 0.08


def test_without_stems_it_plays_as_a_normal_blend(tmp):
    a = tmp / "a.wav"
    b = tmp / "b.wav"
    synth.make_song(a, 120, 0, True, structure=SHAPE)
    synth.make_song(b, 120, 7, True, structure=SHAPE)
    s, _ = new_session([a, b], MixSettings(order="given", key_match=False, transition_style="eq_swap", use_effects=False))
    plain = render.render_mix(s.plan, s.library, s.paths)
    planmod.set_transition(s.plan, s.library, 0, "stem_blend", s.plan.transitions[0].overlap_beats)
    notes = []
    fallback = render.render_mix(s.plan, s.library, s.paths, notes=notes)
    assert len(notes) == 1 and "stems" in notes[0]
    assert fallback.shape == plain.shape and np.allclose(fallback, plain, atol=1e-6)


def test_outside_the_overlap_the_song_is_untouched(tmp):
    """A stem transition must not change a single sample of the song away from the blend."""
    a, b = make(tmp, "a", 120.0), make(tmp, "b", 120.0)
    s, _ = new_session([a, b], MixSettings(order="given", key_match=False, transition_style="eq_swap", use_effects=False))
    planmod.set_transition(s.plan, s.library, 0, "crossfade", 32)
    ref = render.render_mix(s.plan, s.library, s.paths)
    planmod.set_transition(s.plan, s.library, 0, "stem_mashup", 32)
    mix = render.render_mix(s.plan, s.library, s.paths)
    sl = timeline(s.plan)
    start, L = sl[1].start, sl[1].overlap_in
    n = min(mix.shape[1], ref.shape[1])
    assert np.allclose(mix[:, SR:start - 100], ref[:, SR:start - 100], atol=2e-4)
    assert np.allclose(mix[:, start + L + 100:n - SR], ref[:, start + L + 100:n - SR], atol=2e-4)
    assert not np.allclose(mix[:, start:start + L], ref[:, start:start + L], atol=1e-3)


def test_auto_style_and_session_roundtrip(tmp):
    long = [("intro", 8), ("verse", 8), ("chorus", 8), ("outro", 8)]
    a, b = make(tmp, "a", 120.0, shape=long), make(tmp, "b", 120.0, shape=long)
    s, _ = new_session([a, b], MixSettings(order="given", transition_style="stem_blend"))
    assert s.plan.transitions[0].type == "stem_blend"
    again = planmod.MixPlan.from_dict(json.loads(json.dumps(s.plan.to_dict())))
    assert again.transitions[0].type == "stem_blend"
    with pytest.raises(ValueError):
        planmod.set_transition(s.plan, s.library, 0, "stem_nonsense")


def test_gui_offers_stem_styles_and_splitting(tmp, monkeypatch):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("LMM_AUDIO_BACKEND", "null")
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])  # noqa: F841
    from lazy_mixtape_maker.gui import panels
    from test_oct30 import _mix_window
    w, _ = _mix_window(tmp)
    tab = w.findChild(panels.TransitionTab)
    st = w.state
    st.select(0)
    for kind in planmod.STEM_TYPES:
        assert tab.type.findData(kind) >= 0
    assert tab.stems_note.isHidden() and tab.stems_btn.isHidden()            # a normal blend: nothing about stems
    tab.type.setCurrentIndex(tab.type.findData("stem_blend"))
    assert st.plan.transitions[0].type == "stem_blend"
    assert not tab.stems_note.isHidden() and not tab.stems_btn.isHidden() and "normal bass-swap" in tab.stems_note.text()

    # without the engine: an explanation, nothing else
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    monkeypatch.setattr(stems, "available", lambda: False)
    tab.stems_btn.click()
    assert shown and "audio-separator" in shown[0]

    # with the engine (a stand-in): both songs are split, the note changes, and the preview is rendered afresh
    def fake_split(path, song_id=None, progress=None, cancel=None, **k):
        d = stems.song_dir(song_id)
        d.mkdir(parents=True, exist_ok=True)
        for s in stems.STEMS:
            sf.write(str(d / f"{s}.flac"), np.zeros((2205, 2), np.float32), 44100)
        (d / "stems.json").write_text(json.dumps({"stems": sorted(stems.STEMS), "lag": 0.0}))
        if progress:
            progress(1.0)
        return stems.cached(song_id)
    monkeypatch.setattr(stems, "available", lambda: True)
    monkeypatch.setattr(stems, "split", fake_split)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    st.preview_path = "old.wav"
    tab.stems_btn.click()
    import time
    end = time.time() + 20
    while w.task is not None and time.time() < end:
        QApplication.processEvents()
        time.sleep(0.01)
    pair = [t.song_id for t in st.plan.tracks[:2]]
    assert all(stems.cached(s) for s in pair) and not stems.cached(st.plan.tracks[2].song_id)
    assert st.preview_path is None
    assert tab.stems_btn.isHidden() and "have been split" in tab.stems_note.text()
    st.dirty = False
    w.close()
