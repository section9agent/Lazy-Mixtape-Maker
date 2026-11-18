"""The loudness meter and voice leveler ported from LUFS Lab."""
import sys
from pathlib import Path

import numpy as np
import pytest

from lazy_mixtape_maker import loudness

SR = 44100


def tone(seconds, amp, f=440.0):
    t = np.arange(int(seconds * SR)) / SR
    return amp * np.sin(2 * np.pi * f * t)


def test_meter_agrees_with_pyloudnorm():
    import pyloudnorm
    rng = np.random.default_rng(3)
    x = np.stack([tone(8, 0.3) + 0.05 * rng.standard_normal(8 * SR), tone(8, 0.2, 660)])
    ours = loudness.lufs(x, SR)
    ref = pyloudnorm.Meter(SR).integrated_loudness(x.T)
    assert ours == pytest.approx(ref, abs=0.1)
    assert loudness.lufs(np.zeros((2, SR * 2)), SR) == -np.inf


def test_voice_leveler_evens_out_and_hits_the_target():
    # a "singer" who is loud for 4 s, quiet (-14 dB) for 4 s, with a silent gap that must stay silent
    loud, quiet = tone(4, 0.5), tone(4, 0.1)
    gap = np.zeros(2 * SR)
    x = np.stack([np.concatenate([loud, gap, quiet])] * 2)
    y = loudness.level_voice(x, SR, "strong", -18.0)
    assert loudness.lufs(y, SR) == pytest.approx(-18.0, abs=0.3)
    seg = lambda a, b: 20 * np.log10(np.sqrt(np.mean(y[0, int(a * SR):int(b * SR)] ** 2)) + 1e-12)
    before = 20 * np.log10(0.5 / 0.1)
    after = seg(1.5, 3.0) - seg(7.5, 9.0)
    assert after < before - 6                          # the quiet line was brought up a lot
    assert np.max(np.abs(y[:, int(4.6 * SR):int(5.4 * SR)])) < 1e-6   # silence stays silent
    gentle = loudness.level_voice(x, SR, "gentle", -18.0)
    g_after = 20 * np.log10(np.sqrt(np.mean(gentle[0, int(1.5 * SR):3 * SR] ** 2)) /
                            np.sqrt(np.mean(gentle[0, int(7.5 * SR):9 * SR] ** 2)))
    assert after < g_after < before                    # gentle does less than strong
    same = loudness.level_voice(np.zeros((2, SR)), SR)
    assert not same.any()


def test_mashup_vocals_are_leveled(tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).parent))
    from test_mashup import songs as _songs  # noqa: F401
    from test_mashup import LONG
    from test_stem_transitions import make
    from lazy_mixtape_maker import mashup as mm
    from lazy_mixtape_maker.engine import analyze_library
    monkeypatch.setenv("LMM_DATA_DIR", str(tmp_path / "data"))
    a = make(tmp_path, "a", 120.0, shape=LONG)
    lib, paths, _ = analyze_library([a])
    sid = next(iter(lib))
    m = mm.Mashup()
    m.songs = [mm.MashupSong(paths[sid], sid), mm.MashupSong()]
    m.key_match = False
    mm.add_clip(m, lib, 0, "vocals", 0.0, bars=8)
    r = mm.Renderer()
    raw = r.render(m, lib, paths)
    m.vocal_level, m.vocal_lufs = "medium", -24.0
    lev = r.render(m, lib, paths)
    assert loudness.lufs(lev, SR) == pytest.approx(-24.0, abs=0.5)
    assert abs(loudness.lufs(raw, SR) - loudness.lufs(lev, SR)) > 1.0
    m.vocal_lufs = -20.0                               # changing only the level re-levels from the raw vocals
    assert loudness.lufs(r.render(m, lib, paths), SR) == pytest.approx(-20.0, abs=0.5)
    m.vocal_level = "off"
    assert np.allclose(r.render(m, lib, paths), raw, atol=1e-5)
    again = mm.Mashup.from_dict({**m.to_dict(), "vocal_level": "strong", "vocal_lufs": -16})
    assert again.vocal_level == "strong" and again.vocal_lufs == -16
    w = mm.stem_waves(sid)
    assert set(w) == {"bass", "drums", "other", "vocals"} and float(w["other"].max()) == pytest.approx(1.0)
    assert 0.2 < float(w["vocals"].max()) < 0.6           # the vocal tone is quieter than the music
    assert float(w["drums"].max()) == 0.0              # the test songs' drum stems are silent
    assert len(w["vocals"]) == pytest.approx(lib[sid].duration / mm.WAVE_STEP, abs=2)
