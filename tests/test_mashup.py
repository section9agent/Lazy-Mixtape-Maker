"""The mashup engine, checked with test songs whose "bass" and "vocals" stems are steady tones of known
frequencies (as in test_stem_transitions), so what plays where can be measured in the rendered audio."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_stem_transitions import TONES, level, make  # noqa: E402

from lazy_mixtape_maker import mashup as mm  # noqa: E402
from lazy_mixtape_maker.audio_io import SR  # noqa: E402
from lazy_mixtape_maker.engine import analyze_library  # noqa: E402

LONG = [("intro", 8), ("verse", 16), ("chorus", 8), ("outro", 8)]


@pytest.fixture()
def songs(tmp_path, monkeypatch):
    monkeypatch.setenv("LMM_DATA_DIR", str(tmp_path / "data"))
    a = make(tmp_path, "a", 120.0, shape=LONG)
    b = make(tmp_path, "b", 126.0, shape=LONG)
    lib, paths, err = analyze_library([a, b])
    assert not err
    ids = {Path(p).stem: sid for sid, p in paths.items()}
    m = mm.Mashup()
    m.songs = [mm.MashupSong(paths[ids["a"]], ids["a"]), mm.MashupSong(paths[ids["b"]], ids["b"])]
    return m, lib, paths


def tone(audio, song, which, t0, t1):
    f = TONES[song][0 if which == "bass" else 1]
    return level(audio, f, int(t0 * SR), int(t1 * SR))


def test_tempo_rate_and_key(songs):
    m, lib, _ = songs
    a, b = (lib[s.song_id] for s in m.songs)
    assert mm.tempo(m, lib) == pytest.approx(a.bpm)
    assert mm.rate(m, lib, 0) == pytest.approx(1.0) and mm.rate(m, lib, 1) == pytest.approx(a.bpm / b.bpm, rel=1e-6)
    m.tempo_from = "b"
    assert mm.rate(m, lib, 0) == pytest.approx(b.bpm / a.bpm, rel=1e-6) and mm.rate(m, lib, 1) == pytest.approx(1.0)
    m.tempo_from, m.custom_bpm = "custom", 100.0
    assert mm.tempo(m, lib) == 100.0
    m.beat_match = False
    assert mm.rate(m, lib, 0) == mm.rate(m, lib, 1) == 1.0
    assert mm._octave(70.0, 140.0) == 140.0 and mm._octave(150.0, 75.0) == 75.0
    # key matching: the song that moves ends up in a key that goes with the other; a hand-set shift wins
    from lazy_mixtape_maker.analysis import key_cost
    m.key_from = "a"
    assert mm.pitch(m, lib, 0) == 0
    p = mm.pitch(m, lib, 1)
    assert abs(p) <= mm.MAX_PITCH
    assert key_cost(a.key_tonic, a.key_mode, (b.key_tonic + p) % 12, b.key_mode) <= key_cost(a.key_tonic, a.key_mode, b.key_tonic, b.key_mode)
    m.songs[1].pitch = -3
    assert mm.pitch(m, lib, 1) == -3
    m.key_match, m.songs[1].pitch = False, None
    assert mm.pitch(m, lib, 1) == 0


def test_one_song_as_it_is(songs):
    """All four stems of a song, unstretched, give back the song (its pilot tones at full level)."""
    m, lib, paths = songs
    m.key_match = False
    mm.full_song(m, lib, 0)
    audio = mm.Renderer().render(m, lib, paths)
    a = lib[m.songs[0].song_id]
    assert audio.shape[1] / SR == pytest.approx(a.duration - mm.first_bar(a), abs=0.05)
    assert tone(audio, "a", "bass", 5, 15) == pytest.approx(0.1, rel=0.1)
    assert tone(audio, "a", "vocals", 5, 15) == pytest.approx(0.1, rel=0.1)
    assert tone(audio, "b", "vocals", 5, 15) < 0.01


def test_vocals_over_music_by_the_ai(songs):
    m, lib, paths = songs
    used = mm.auto_mashup(m, lib, "b_over_a")
    assert used == "b_over_a" and m.tempo_from == "a" and m.key_from == "a" and m.beat_match
    music = [c for c in m.clips if c.song == 0]
    voice = [c for c in m.clips if c.song == 1]
    assert sorted(c.stem for c in music) == ["bass", "drums", "other"] and [c.stem for c in voice] == ["vocals"]
    bar = mm.bar_seconds(m, lib)
    v = voice[0]
    assert v.start == pytest.approx(mm._intro_bars(lib[m.songs[0].song_id]) * bar)
    bars = mm.clip_length(m, lib, v) / bar
    assert bars == pytest.approx(round(bars), abs=1e-6) and round(bars) % 4 == 0          # whole phrases
    m.key_match = False                                                                 # keep the tones where they are
    audio = mm.Renderer().render(m, lib, paths)
    t0, t1 = v.start + 2 * bar, v.start + mm.clip_length(m, lib, v) - 2 * bar
    assert tone(audio, "a", "bass", t0, t1) > 0.08         # song A's music ...
    assert tone(audio, "a", "vocals", t0, t1) < 0.01       # ... without its singer
    assert tone(audio, "b", "vocals", t0, t1) > 0.07       # song B's singer over it
    assert tone(audio, "b", "bass", t0, t1) < 0.02         # without B's music
    assert tone(audio, "b", "vocals", 0.5, v.start - 0.5) < 0.01                       # the intro is A's music alone


def test_stretched_song_keeps_its_length_and_pitch(songs):
    m, lib, paths = songs
    m.key_match = False
    c = mm.add_clip(m, lib, 1, "vocals", 2.0, bars=8)
    r = mm.rate(m, lib, 1)
    assert mm.clip_length(m, lib, c) == pytest.approx(8 * mm.bar_seconds(m, lib), rel=1e-6)
    assert c.src_end - c.src_start == pytest.approx(8 * mm.bar_seconds(m, lib) * r, rel=1e-6)
    audio = mm.Renderer().render(m, lib, paths)
    assert audio.shape[1] / SR == pytest.approx(2.0 + 8 * mm.bar_seconds(m, lib), abs=0.01)
    assert tone(audio, "b", "vocals", 3, 10) > 0.07                                     # same note, new tempo


def test_key_shift_moves_the_notes(songs):
    m, lib, paths = songs
    m.key_match = False
    m.songs[1].pitch = 2
    mm.add_clip(m, lib, 1, "vocals", 0.0, bars=8)
    audio = mm.Renderer().render(m, lib, paths)
    f = TONES["b"][1]
    moved = level(audio, f * 2 ** (2 / 12), SR, 8 * SR)
    assert moved > 0.07 and level(audio, f, SR, 8 * SR) < 0.02


def test_trade_back_and_forth(songs):
    m, lib, paths = songs
    assert mm.auto_mashup(m, lib, "trade") == "trade"
    bar = mm.bar_seconds(m, lib)
    blocks = sorted({round(c.start / bar) for c in m.clips})
    assert blocks[:3] == [0, 8, 24]
    def who(start_bar, stem):
        return {c.song for c in m.clips if round(c.start / bar) == start_bar and c.stem == stem}
    assert who(0, "drums") == {0} and not who(0, "vocals")
    assert who(8, "drums") == {0} and who(8, "vocals") == {1}
    assert who(24, "drums") == {1} and who(24, "vocals") == {0}


def test_edit_and_save(songs, tmp_path):
    m, lib, _ = songs
    c = mm.add_clip(m, lib, 0, "drums", 4.0, bars=8)
    L = mm.clip_length(m, lib, c)
    d = mm.split_clip(m, lib, c.id, 4.0 + L / 2)
    assert d is not None and mm.clip_length(m, lib, c) + mm.clip_length(m, lib, d) == pytest.approx(L)
    assert d.src_start == pytest.approx(c.src_end) and d.start == pytest.approx(c.start + L / 2)
    assert mm.split_clip(m, lib, c.id, 0.0) is None
    e = mm.duplicate_clip(m, lib, d.id)
    assert e.start == pytest.approx(d.start + mm.clip_length(m, lib, d)) and e.src_start == d.src_start
    m.songs[1].pitch = -2
    f = tmp_path / "x.lmmash"
    m.save(f)
    again = mm.Mashup.load(f)
    assert again.to_dict() == m.to_dict()
    with pytest.raises(mm.MashupError):
        f.write_text(json.dumps({"format": "something-else"}))
        mm.Mashup.load(f)


def test_needs_stems(songs):
    m, lib, paths = songs
    from lazy_mixtape_maker import stems
    mm.add_clip(m, lib, 0, "drums", 0.0)
    stems.forget(m.songs[0].song_id)
    with pytest.raises(mm.MashupError):
        mm.Renderer().render(m, lib, paths)
