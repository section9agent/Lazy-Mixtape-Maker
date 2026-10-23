import sys
from pathlib import Path

import numpy as np
import pytest
from scipy.signal import butter, sosfilt

sys.path.insert(0, str(Path(__file__).parent))
import synth  # noqa: E402

from lazy_mixtape_maker import audio_io, plan as planmod  # noqa: E402
from lazy_mixtape_maker.engine import new_session  # noqa: E402
from lazy_mixtape_maker.plan import MixSettings  # noqa: E402
from lazy_mixtape_maker.render import render_track_audio  # noqa: E402
from lazy_mixtape_maker.tempo import RateCurve, build_curve, time_warp  # noqa: E402

SR = 44100


def test_rate_curve_roundtrip_and_length():
    c = build_curve(10.0, 100.0, 1.1, 1.0, 0.92, hold_in=8, hold_out=8, ramp=20)
    s = np.linspace(10, 100, 50)
    assert np.allclose(c.src_time(c.mix_time(s)), s, atol=2e-3)
    assert np.all(np.diff(c.mix_time(s)) > 0)
    flat = RateCurve([0, 10], [1.25, 1.25])
    assert abs(flat.total - 8.0) < 1e-9


def test_identity_warp_is_exact():
    x = np.random.default_rng(0).standard_normal((2, SR * 3)).astype(np.float32) * 0.1
    y = time_warp(x, lambda u: u, x.shape[1])
    assert np.abs(y[:, 4000:-4000] - x[:, 4000:-4000]).max() < 1e-5


def _kicks(y, thr=0.25):
    sos = butter(4, 120, "low", fs=SR, output="sos")
    e = np.abs(sosfilt(sos, y[0]))
    e = np.convolve(e, np.ones(200) / 200, "same")
    d = np.diff(e, prepend=0)
    peaks, i = [], 0
    lim = thr * d.max()
    while i < len(d):
        if d[i] > lim:
            peaks.append(i / SR)
            i += int(0.25 * SR)
        else:
            i += 1
    return np.array(peaks)


@pytest.fixture(scope="module")
def drift_session(tmp_path_factory):
    d = tmp_path_factory.mktemp("drift")
    st = [("verse", 24)]
    synth.make_song(d / "Band - slow.wav", 100, 9, True, structure=st, tags={"title": "slow", "artist": "Band"})
    synth.make_song(d / "Band - fast.wav", 116, 0, True, structure=st, tags={"title": "fast", "artist": "Band"})
    s, errs = new_session(audio_io.list_audio_files([d]), MixSettings(seed=1, overlap_bars=4, use_effects=False))
    assert not errs
    return s


def test_tempos_drift_and_every_pair_blends(drift_session):
    p = drift_session.plan
    tr = p.transitions[0]
    assert tr.matched and tr.type in ("eq_swap", "crossfade") and tr.overlap_beats > 0
    a, b = p.tracks
    assert 100 < tr.tempo < 116
    assert abs(a.rate_out * a.bpm - tr.tempo) < 0.01 and abs(b.rate_in * b.bpm - tr.tempo) < 0.01
    assert a.rate == b.rate == 1.0


def test_beats_coincide_during_blend(drift_session):
    s = drift_session
    slots = planmod.timeline(s.plan)
    stems = []
    for t, sl in zip(s.plan.tracks, slots):
        y = render_track_audio(s.paths[t.song_id], t, sl.curve, s.library[t.song_id])
        assert y.shape[1] == sl.length
        stems.append((sl.start / SR + _kicks(y), t, sl))
    (ka, ta, sa), (kb, tb, sb) = stems
    lo, hi = sb.start / SR + 0.5, sa.end / SR - 0.5          # inside the overlap
    a = ka[(ka > lo) & (ka < hi)]
    b = kb[(kb > lo) & (kb < hi)]
    assert len(a) >= 5 and len(b) >= 5
    err = [np.min(np.abs(b - x)) for x in a]
    assert np.median(err) < 0.012 and np.max(err) < 0.03, (np.median(err), np.max(err))
    # and each song's kicks sit on the grid the speed curve promises
    an = s.library[ta.song_id]
    beats = an.grid_origin + an.beat_period * np.arange(0, 400)
    beats = beats[(beats > ta.src_start + 1) & (beats < ta.src_end - 1)]
    pred = sa.start / SR + sa.curve.mix_time(beats)
    got = ka
    e2 = np.array([np.min(np.abs(got - x)) for x in pred[: len(pred) // 2]])
    assert np.median(e2) < 0.012


def test_locked_mode_and_edits_keep_blends(tmp_path):
    d = tmp_path / "s"
    d.mkdir()
    for n, bpm, root in (("a", 120, 9), ("b", 124, 0), ("c", 128, 7)):
        synth.make_song(d / f"B - {n}.wav", bpm, root, True,
                        structure=[("intro", 2), ("verse", 4), ("chorus", 4), ("outro", 2)],
                        tags={"title": n, "artist": "B"})
    from lazy_mixtape_maker.session import load_session, save_session
    s, _ = new_session(audio_io.list_audio_files([d]), MixSettings(seed=2, tempo_mode="locked"))
    p = s.plan
    assert {round(t.bpm, 3) for t in p.tracks} == {round(p.master_bpm, 3)}     # one tempo throughout
    assert all(t.rate_in == 0 and t.rate_out == 0 for t in p.tracks)
    s.plan.settings.tempo_mode = "drift"
    planmod.recompute(p, s.library)
    assert all(tr.matched for tr in p.transitions) and p.tracks[0].rate_out > 0
    planmod.remove_track(p, s.library, 1)                                      # neighbours get re-blended
    assert len(p.tracks) == 2 and p.transitions[0].matched and p.transitions[0].tempo > 0
    planmod.move_track(p, s.library, 0, 1)
    save_session(s, tmp_path / "x.lmm")
    s2 = load_session(tmp_path / "x.lmm", [d])
    assert s2.plan.to_dict() == s.plan.to_dict()
    assert [round(sl.length) for sl in planmod.timeline(s2.plan)] == [round(sl.length) for sl in planmod.timeline(p)]
