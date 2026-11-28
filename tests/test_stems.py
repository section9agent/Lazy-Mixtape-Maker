"""The optional stems add-on: cache, engine lookup and errors (with a stand-in for the real engine)."""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

sys.path.insert(0, str(Path(__file__).parent))
import synth  # noqa: E402
from test_videofiles import TINY  # noqa: E402

from lazy_mixtape_maker import stems  # noqa: E402


@pytest.fixture()
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("LMM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("LMM_STEMS_PYTHON", raising=False)
    synth.make_song(tmp_path / "song.wav", 120, 0, True, structure=TINY)
    return tmp_path


def fake_runner(calls, fail=None):
    def run(cmd, progress, cancel):
        calls.append(cmd)
        if fail:
            raise stems.StemsError(fail)
        out = Path(cmd[3])
        for i, s in enumerate(stems.STEMS):
            sf.write(str(out / f"{s}.flac"), np.full((2205, 2), 0.1 * (i + 1), np.float32), 22050)
        if progress:
            progress(1.0)
        return {"event": "done", "stems": {s: str(out / f"{s}.flac") for s in stems.STEMS}, "seconds": 1.0}
    return run


def test_without_the_engine_it_explains_how_to_get_it(data, monkeypatch):
    monkeypatch.setattr(stems, "engine_python", lambda: None)
    assert not stems.available()
    with pytest.raises(stems.StemsUnavailable) as e:
        stems.split(data / "song.wav")
    assert "audio-separator" in str(e.value)


def test_split_is_cached_per_song(data, monkeypatch):
    monkeypatch.setattr(stems, "engine_python", lambda: sys.executable)
    calls, seen = [], []
    got = stems.split(data / "song.wav", progress=seen.append, runner=fake_runner(calls))
    assert sorted(got) == sorted(stems.STEMS) and all(p.exists() for p in got.values()) and seen == [1.0]
    assert calls[0][1].endswith("stems_worker.py") and calls[0][2] == str(data / "song.wav")
    again = stems.split(data / "song.wav", runner=fake_runner(calls))
    assert again == got and len(calls) == 1                         # second time: straight from the cache
    moved = data / "renamed.wav"
    (data / "song.wav").rename(moved)
    assert stems.split(moved, runner=fake_runner(calls)) == got and len(calls) == 1   # found again after a rename
    stems.split(moved, runner=fake_runner(calls), force=True)
    assert len(calls) == 2
    from lazy_mixtape_maker.audio_io import file_id
    sid = file_id(moved)
    y = stems.load(sid, "bass", sr=44100)
    assert y.shape[1] == 2 and abs(len(y) - 4410) <= 2 and abs(float(y.mean()) - 0.2) < 0.02
    assert stems.cache_size() > 0
    stems.forget(sid)
    assert stems.cached(sid) is None


def test_a_failed_or_cancelled_split_leaves_nothing_behind(data, monkeypatch):
    monkeypatch.setattr(stems, "engine_python", lambda: sys.executable)
    with pytest.raises(stems.StemsError):
        stems.split(data / "song.wav", runner=fake_runner([], fail="boom"))
    assert not list(stems.cache_root().glob("*"))
    with pytest.raises(stems.StemsError):                              # the engine said "done" but wrote nothing
        stems.split(data / "song.wav", runner=lambda c, p, x: {"event": "done", "stems": {}})
    assert not list(stems.cache_root().glob("*"))


def test_worker_protocol_with_a_python_that_lacks_the_engine(data, monkeypatch):
    """The real worker, run for real: a Python without audio-separator reports a clear error."""
    import importlib.util
    if importlib.util.find_spec("audio_separator") is not None:
        pytest.skip("the engine is installed here")
    monkeypatch.setattr(stems, "engine_python", lambda: sys.executable)
    with pytest.raises(stems.StemsError) as e:
        stems.split(data / "song.wav")
    assert "isn't installed" in str(e.value)
    with pytest.raises(stems.StemsError):
        stems.set_engine_python(sys.executable)


def test_real_engine_if_present(data):
    py = os.environ.get("LMM_STEMS_TEST_PYTHON")
    if not py:
        pytest.skip("set LMM_STEMS_TEST_PYTHON to a Python with audio-separator to run the real engine")
    stems.set_engine_python(py)
    got = stems.split(data / "song.wav")
    assert sorted(got) == sorted(stems.STEMS)
    meta = json.loads((next(iter(got.values())).parent / "stems.json").read_text())
    assert meta["model"] == stems.MODEL


def _mp4(path, wav=None, audio=True):
    import subprocess
    from lazy_mixtape_maker import audio_io
    cmd = [audio_io.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=64x36:r=10:d=3"]
    if audio:
        cmd += ["-i", str(wav), "-shortest", "-c:a", "aac"]
    subprocess.run(cmd + ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def test_video_files_are_split_from_their_soundtrack(data, monkeypatch):
    """The stem engine can't open video files: it's given the soundtrack, taken out as a WAV file."""
    monkeypatch.setattr(stems, "engine_python", lambda: sys.executable)
    video = _mp4(data / "clip.mp4", data / "song.wav")
    calls = []
    got = stems.split(video, runner=fake_runner(calls))
    src = Path(calls[0][-5])
    assert src.suffix == ".wav" and src.name == "source.wav"
    assert set(got) == set(stems.STEMS)
    assert not any(p.name == "source.wav" for p in got.values())
    assert not (stems.song_dir(stems.file_id(video)) / "source.wav").exists()   # (not kept with the stems)
    calls.clear()
    stems.split(data / "song.wav", runner=fake_runner(calls))                     # an audio file goes in as it is
    assert Path(calls[0][-5]) == data / "song.wav"


def test_a_video_without_sound_says_so(data, monkeypatch):
    monkeypatch.setattr(stems, "engine_python", lambda: sys.executable)
    silent = _mp4(data / "silent.mp4", audio=False)
    with pytest.raises(stems.StemsError) as e:
        stems.split(silent, runner=fake_runner([]))
    assert "silent.mp4" in str(e.value)
