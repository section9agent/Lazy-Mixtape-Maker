import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

sys.path.insert(0, str(Path(__file__).parent))
import synth  # noqa: E402

from lazy_mixtape_maker import audio_io, cue, effects, plan as planmod  # noqa: E402
from lazy_mixtape_maker.analysis import analyze_file, camelot, camelot_number, key_cost  # noqa: E402
from lazy_mixtape_maker.engine import export_session, new_session  # noqa: E402
from lazy_mixtape_maker.plan import MixSettings  # noqa: E402
from lazy_mixtape_maker.render import render_mix  # noqa: E402
from lazy_mixtape_maker.session import load_session, save_session  # noqa: E402

SHORT = [("intro", 4), ("verse", 8), ("chorus", 8), ("verse", 8), ("chorus", 8), ("outro", 4)]
SPEC = [  # name, bpm, root, minor, fmt
    ("one", 120, 9, True, "mp3"),
    ("two", 126, 0, True, "flac"),
    ("three", 132, 7, False, "m4a"),
    ("four", 118, 2, True, "wav"),
]


@pytest.fixture(scope="module")
def songs(tmp_path_factory):
    d = tmp_path_factory.mktemp("songs")
    out = {}
    for name, bpm, root, minor, fmt in SPEC:
        p = d / f"Artist - {name}.{fmt}"
        synth.make_song(p, bpm, root, minor, structure=SHORT, fmt=fmt, tags={"title": name, "artist": "Artist"})
        out[name] = (p, bpm, root, minor)
    return d, out


@pytest.fixture(scope="module")
def session(songs, tmp_path_factory):
    d, _ = songs
    files = audio_io.list_audio_files([d])
    s, errors = new_session(files, MixSettings(seed=1, overlap_bars=4), name="Test")
    assert not errors
    return s


def test_camelot_wheel():
    assert camelot(0, "major") == "8B" and camelot(9, "minor") == "8A"
    assert camelot(7, "major") == "9B" and camelot(5, "major") == "7B"
    assert key_cost(0, "major", 9, "minor") == 0.5          # relative keys
    assert key_cost(0, "major", 7, "major") == 1            # neighbours
    assert key_cost(0, "major", 6, "major") == 6            # tritone clashes


def test_all_four_formats_listed(songs):
    d, _ = songs
    exts = {f.suffix for f in audio_io.list_audio_files([d])}
    assert exts == {".mp3", ".flac", ".m4a", ".wav"}


def test_analysis_matches_truth(songs, tmp_path):
    _, truth = songs
    for name, (path, bpm, root, minor) in truth.items():
        an = analyze_file(path, cache_dir=tmp_path)
        assert abs(an.bpm / bpm - 1) < 0.005, (name, an.bpm)
        want = camelot_number(root, "minor" if minor else "major")
        assert camelot_number(an.key_tonic, an.key_mode) == want, (name, an.camelot)
        assert an.title == name and an.artist == "Artist"
        assert 3 <= len(an.sections) <= 8
        assert an.sections[0].label in ("intro", "verse")
        # bar grid sits on the real downbeats (kick on beat one of every bar, track starts at 0)
        off = an.grid_origin % an.bar_length
        assert min(off, an.bar_length - off) < 0.06, (name, off)
    # cached second call is instant and identical
    again = analyze_file(truth["one"][0], cache_dir=tmp_path)
    assert again.bpm == analyze_file(truth["one"][0], cache_dir=tmp_path).bpm


@pytest.mark.parametrize("kind", list(effects.EFFECT_TYPES))
def test_effects_are_sane(kind):
    sr = 44100
    t = np.arange(sr * 4) / sr
    x = (0.4 * np.sin(2 * np.pi * 220 * t) + 0.2 * np.sin(2 * np.pi * 1760 * t)).astype(np.float32)
    buf = np.zeros((2, sr * 4 + int(effects.TAIL_SECONDS * sr)), np.float32)
    buf[:, : sr * 4] = x
    before = buf.copy()
    out = effects.apply_effect(buf, sr, 2 * sr, {"type": kind}, sr, 120.0)
    assert np.isfinite(out).all()
    assert np.abs(out).max() < 4.0
    assert not np.allclose(out, before), f"{kind} did nothing"
    assert np.allclose(out[:, :sr], before[:, :sr]), f"{kind} touched audio before its region"


def test_plan_is_beat_aligned(session):
    p = session.plan
    slots = planmod.timeline(p)
    assert abs(p.master_bpm - 124) < 12
    for a, b in zip(slots, slots[1:]):
        assert b.start == a.end - a.overlap_out
    # every track's start is exactly on a bar line of its own grid
    for t in p.tracks:
        an = session.library[t.song_id]
        off = ((t.src_start - an.grid_origin) / an.bar_length) % 1.0
        assert min(off, 1 - off) < 1e-6


def test_edit_operations(session):
    s = session
    p = planmod.MixPlan.from_dict(json.loads(json.dumps(s.plan.to_dict())))
    lib = s.library
    ids = [t.song_id for t in p.tracks]
    planmod.move_track(p, lib, 0, 3)
    assert [t.song_id for t in p.tracks] == ids[1:] + ids[:1]
    # hand-edited transition survives a re-plan, automatic ones are rebuilt
    planmod.set_transition(p, lib, 0, "crossfade", 16)
    e = planmod.add_effect(p, 1, "reverb", "end", -3.0, 3.0)
    planmod.recompute(p, lib)
    assert p.transition_after(0).type == "crossfade" and p.transition_after(0).overlap_beats == 16
    assert any(x.id == e.id for x in p.tracks[1].effects)
    planmod.update_effect(p, 1, e.id, offset=-2.0)
    assert [x for x in p.tracks[1].effects if x.id == e.id][0].offset == -2.0
    planmod.set_track_bounds(p, lib, 2, src_start=p.tracks[2].src_start + 4)
    assert not p.tracks[2].auto_bounds
    planmod.remove_track(p, lib, 3)
    assert len(p.tracks) == 3 and len(p.transitions) == 2
    planmod.remove_effect(p, 1, e.id)
    with pytest.raises(KeyError):
        planmod.remove_effect(p, 1, e.id)


def test_render_and_exports(session, tmp_path):
    audio = render_mix(session.plan, session.library, session.paths)
    assert audio.shape[0] == 2 and np.isfinite(audio).all() and np.abs(audio).max() <= 0.9
    slots = planmod.timeline(session.plan)
    assert abs(audio.shape[1] - slots[-1].end) < 8 * 44100  # + short tail

    res = export_session(session, tmp_path / "mix.flac")
    info = sf.info(res["audio"])
    assert info.format == "FLAC" and info.subtype == "PCM_24" and info.samplerate == 44100

    res = export_session(session, tmp_path / "mix.mp3", write_cue=False)
    from mutagen.mp3 import MP3
    info3 = MP3(res["audio"]).info
    assert 315000 <= info3.bitrate <= 325000 and info3.sample_rate == 44100

    res = export_session(session, tmp_path / "mix.wav", write_cue=False)
    assert sf.info(res["audio"]).subtype == "PCM_24"


def test_cue_sheet(session, tmp_path):
    cue.write_cue(tmp_path / "m.cue", session.plan, session.library, "m.flac", "Test")
    text = (tmp_path / "m.cue").read_text()
    assert text.count("TRACK ") == len(session.plan.tracks) and 'FILE "m.flac" FLAC' in text
    times = [r["cue"] for r in cue.tracklist(session.plan, session.library)]
    assert times[0] == 0 and times == sorted(times)


def test_session_roundtrip_and_sharing(session, songs, tmp_path):
    """A friend with the same songs in a different folder (and renamed files) gets the same mix."""
    save_session(session, tmp_path / "mix.lmm")
    friend = tmp_path / "friend" / "My Music" / "mixes"
    friend.mkdir(parents=True)
    for i, f in enumerate(audio_io.list_audio_files([songs[0]])):
        shutil.copy(f, friend / f"renamed_{i}{f.suffix}")
    shared = tmp_path / "shared"
    shared.mkdir()
    shutil.copy(tmp_path / "mix.lmm", shared / "mix.lmm")
    s2 = load_session(shared / "mix.lmm", [tmp_path / "friend"])
    assert not s2.missing()
    assert s2.plan.to_dict() == session.plan.to_dict()
    a = render_mix(session.plan, session.library, session.paths)
    b = render_mix(s2.plan, s2.library, s2.paths)
    assert a.shape == b.shape and np.abs(a - b).max() < 1e-6
    # without the songs it reports what is missing instead of crashing
    s3 = load_session(shared / "mix.lmm")
    assert len(s3.missing()) == 4
    with pytest.raises(Exception, match="Cannot find"):
        render_mix(s3.plan, s3.library, s3.paths)


def test_clips_mode(songs):
    d, _ = songs
    s, _ = new_session(audio_io.list_audio_files([d]), MixSettings(mode="clips", clip_seconds=15, overlap_bars=2))
    for t in s.plan.tracks:
        assert 8 <= t.src_end - t.src_start <= 20
    audio = render_mix(s.plan, s.library, s.paths)
    assert audio.shape[1] / 44100 < 4 * 20


def _noise_buf(sr=44100, secs=4):
    rng = np.random.default_rng(3)
    buf = np.zeros((2, sr * secs + int(effects.TAIL_SECONDS * sr)), np.float32)
    buf[:, : sr * secs] = rng.uniform(-0.5, 0.5, (2, sr * secs)).astype(np.float32)
    return buf


def test_cut_chops_in_time():
    sr = 44100
    buf = _noise_buf()
    out = effects.apply_effect(buf.copy(), sr, 2 * sr, {"type": "cut", "params": {"mode": "gate", "division": 0.5, "duty": 0.5}}, sr, 120.0)
    seg = np.abs(out[0, sr + 2000: 3 * sr - 2000])
    quiet = (seg < 1e-4).mean()
    assert 0.35 < quiet < 0.65, quiet                      # about half of the time the fader is closed
    # gate slices follow the tempo: one beat at 120 bpm = 22050 samples, half-beat open/closed => 11025 period
    env = (np.convolve(np.abs(out[0, 2 * sr: 2 * sr + 44100]), np.ones(200) / 200, "same") > 0.05).astype(int)
    edges = np.nonzero(np.diff(env) == 1)[0]
    assert len(edges) >= 3 and abs(np.median(np.diff(edges)) - 11025) < 300     # an 8th note at 120 bpm
    # bass kill keeps the highs but removes lows on the closed slices
    kill = effects.apply_effect(buf.copy(), sr, 2 * sr, {"type": "cut", "params": {"mode": "bass_kill"}}, sr, 120.0)
    assert np.abs(kill[:, 2 * sr: 4 * sr]).mean() > 0.1
    assert np.abs(kill[:, 2 * sr: 4 * sr] - buf[:, 2 * sr: 4 * sr]).mean() > 0.002


def test_stutter_repeats_the_first_slice():
    sr = 44100
    buf = _noise_buf()
    out = effects.apply_effect(buf.copy(), sr, sr, {"type": "stutter", "params": {"beats": 0.5, "roll": "no"}}, sr, 120.0)
    D = int(0.5 * 60.0 / 120.0 * sr)
    a = out[0, sr + 200: sr + D - 200]
    b = out[0, sr + D + 200: sr + 2 * D - 200]
    assert np.corrcoef(a, b)[0, 1] > 0.99                  # the same slice, again
    assert not np.allclose(buf[0, sr + D: sr + 2 * D], out[0, sr + D: sr + 2 * D])


def test_ai_can_choose_the_new_effects():
    import random
    from lazy_mixtape_maker.plan import MixSettings, MixPlan, TrackPlan, Transition, _auto_effects
    seen = set()
    for seed in range(300):
        rng = random.Random(seed)
        a = TrackPlan(song_id="a", src_start=0, src_end=200); b = TrackPlan(song_id="b", src_start=0, src_end=200)
        a.bpm = b.bpm = 120.0
        tr = Transition(a.uid, b.uid, type="eq_swap" if seed % 3 else "cut_fx", overlap_beats=32 if seed % 3 else 0)
        plan = MixPlan(tracks=[a, b], transitions=[tr], settings=MixSettings())
        plan.master_bpm = 120.0
        tr.tempo = 120.0
        _auto_effects(a, b, tr, plan, rng)
        seen |= {e.type for e in a.effects + b.effects}
    assert {"cut", "stutter"} <= seen
