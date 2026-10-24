import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

sys.path.insert(0, str(Path(__file__).parent))
import synth  # noqa: E402

from lazy_mixtape_maker import audio_io, cue, prefs, studio  # noqa: E402
from lazy_mixtape_maker.studio import (StudioHistory, StudioProject, build_segments, fade_windows,  # noqa: E402
                                       import_cue_file, load_project, new_project, parse_cue, parse_tracklist,
                                       render_studio, save_project)
from lazy_mixtape_maker.video import VideoSettings  # noqa: E402
from lazy_mixtape_maker.visuals import ShaderLibrary, make_context  # noqa: E402

CUE = '''REM GENERATOR "something"
PERFORMER "Various Artists"
TITLE "My Mixtape"
FILE "mix.mp3" MP3
  TRACK 01 AUDIO
    TITLE "First one"
    PERFORMER "Alpha"
    INDEX 01 00:00:00
  TRACK 02 AUDIO
    TITLE "Second, with ""quote"""
    INDEX 00 01:29:50
    INDEX 01 01:30:37
  TRACK 03 AUDIO
    TITLE "Third"
    PERFORMER "Gamma"
    INDEX 01 62:05:15
'''


@pytest.fixture()
def lib(tmp_path, monkeypatch):
    monkeypatch.setenv("LMM_DATA_DIR", str(tmp_path / "data"))
    return ShaderLibrary()


@pytest.fixture(scope="module")
def mixtape(tmp_path_factory):
    """A 30 s 'mixtape made elsewhere': a quiet part, a loud part, a medium part."""
    d = tmp_path_factory.mktemp("studio")
    synth.make_song(d / "a.wav", 120, 9, True, structure=[("verse", 8), ("chorus", 8)], tags={"title": "T", "artist": "A"})
    x, sr = sf.read(str(d / "a.wav"), dtype="float32")
    x = x[: 30 * sr]
    path = d / "Some DJ - Old Mix.mp3"
    audio_io.write_audio(path, x.T, sr, metadata={"title": "Old Mix", "artist": "Some DJ"})
    return path


# ----------------------------------------------------------------------- parsing
def test_parse_cue_sheet():
    rows = parse_cue(CUE)
    assert [r["title"] for r in rows] == ["First one", 'Second, with "quote"', "Third"]
    assert rows[0]["artist"] == "Alpha" and rows[1]["artist"] == ""     # "Various Artists" isn't a track artist
    assert rows[1]["time"] == pytest.approx(90 + 37 / 75)               # INDEX 01 wins over INDEX 00
    assert rows[2]["time"] == pytest.approx(62 * 60 + 5 + 15 / 75)


def test_parse_tracklists():
    txt = ("  0:00  Alpha - First\n"
           "[3:45] Beta – Second [8A / 124 BPM]\n"
           "1:02:03 - Gamma - Third\n"
           "garbage line\n"
           "04. 7:10 Just a title\n")
    rows = parse_tracklist(txt)
    assert [(r["time"], r["artist"], r["title"]) for r in rows] == [
        (0, "Alpha", "First"), (225, "Beta", "Second"), (430, "", "Just a title"), (3723, "Gamma", "Third")]


def test_our_own_cue_and_tracklist_files_import(tmp_path):
    from lazy_mixtape_maker.engine import new_session
    from lazy_mixtape_maker.plan import MixSettings
    d = tmp_path / "s"
    d.mkdir()
    for n, bpm, root in (("a", 120, 9), ("b", 124, 0)):
        synth.make_song(d / f"Band - {n}.wav", bpm, root, True, structure=[("verse", 8), ("chorus", 8)],
                        tags={"title": n, "artist": "Band"})
    s, _ = new_session(audio_io.list_audio_files([d]), MixSettings(seed=1, overlap_bars=4), name="x")
    cue.write_cue(tmp_path / "m.cue", s.plan, s.library, "m.mp3", "x")
    cue.write_tracklist_txt(tmp_path / "m.txt", s.plan, s.library)
    a = import_cue_file(tmp_path / "m.cue")
    b = import_cue_file(tmp_path / "m.txt")
    assert len(a) == len(b) == 2
    assert [r["title"] for r in a] == [r["title"] for r in b]
    assert abs(a[1]["time"] - b[1]["time"]) < 1.0
    with pytest.raises(ValueError):
        (tmp_path / "bad.txt").write_text("nothing useful here")
        import_cue_file(tmp_path / "bad.txt")


# ------------------------------------------------------------------- editing
def test_project_editing_undo_and_persistence(mixtape, lib, tmp_path):
    p = new_project(mixtape)
    assert p.duration == pytest.approx(30, abs=1) and p.markers[0].title == "Old Mix" and p.markers[0].artist == "Some DJ"
    h = StudioHistory(p)
    h.edit(lambda q: q.set_markers([{"time": 0, "title": "One"}, {"time": 12.5, "artist": "X", "title": "Two"}]))
    m2 = h.project.markers[1]
    h.edit(lambda q: q.add_marker(20, "Y", "Three"))
    h.begin_gesture()
    for t in (21, 22, 23.5):
        h.project.move_marker(h.project.markers[-1].uid, t)
    h.end_gesture()
    assert [m.time for m in h.project.markers] == [0, 12.5, 23.5]
    h.undo()                                                  # the whole drag in one step
    assert [m.time for m in h.project.markers] == [0, 12.5, 20]
    h.undo(); h.undo()
    assert h.project.markers[0].title == "Old Mix"
    h.redo()
    assert h.project.markers[0].title == "One"
    h.edit(lambda q: q.update_marker(m2.uid, shader="builtin:aurora"))
    h.edit(lambda q: q.remove_marker(q.markers[0].uid))
    assert len(h.project.markers) == 1
    h.edit(lambda q: q.add_marker(20, "Y", "Three"))
    f = tmp_path / "x.lmv"
    sh = lib.add_from_text("void mainImage(out vec4 c, in vec2 p){ c = vec4(p/iResolution.xy, 0.3, 1.0); }", "Mine")
    h.project.update_marker(h.project.markers[0].uid, shader=sh.id)
    save_project(h.project, f, lib)
    friend_dir = tmp_path / "friend"
    friend_dir.mkdir()
    (friend_dir / "renamed.mp3").write_bytes(Path(mixtape).read_bytes())
    import os
    os.environ["LMM_DATA_DIR"] = str(tmp_path / "friend_data")
    friend_lib = ShaderLibrary()
    q = load_project(f, friend_lib, search_dirs=[friend_dir])
    assert friend_lib.get(sh.id) is not None                  # the visual travelled in the file
    assert q.markers[0].shader == sh.id and [m.time for m in q.markers] == [12.5, 20]
    assert Path(q.audio).name in ("Some DJ - Old Mix.mp3", "renamed.mp3") and Path(q.audio).is_file()


def test_fade_windows_never_overlap():
    w = fade_windows([0, 3, 4, 100], 20)
    for (a0, a1), (b0, b1) in zip(w, w[1:]):
        assert a1 <= b0 + 1e-9
    assert all(a < b for a, b in w)


# ------------------------------------------------------------------ the video
@pytest.fixture(scope="module")
def need_gl():
    try:
        make_context().release()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"no OpenGL available: {e}")


def _first_frame(path, at=8.0, size=(320, 180)):
    raw = subprocess.run([audio_io.ffmpeg(), "-v", "error", "-ss", str(at), "-i", str(path), "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(size[1], size[0], 3).astype(float)


@pytest.mark.parametrize("mode", ["single", "random", "per_song", "auto"])
def test_studio_video_modes(mode, mixtape, lib, tmp_path, need_gl):
    p = new_project(mixtape)
    p.set_markers([{"time": 0, "artist": "A", "title": "One"}, {"time": 10, "artist": "B", "title": "Two"},
                   {"time": 20, "artist": "C", "title": "Three"}])
    p.markers[1].shader = "builtin:tunnel"
    p.video = VideoSettings(mode=mode, single_shader="builtin:aurora", width=256, height=144, fps=8, crf=34,
                            preset="ultrafast", blend=4.0, seed=5)
    out = tmp_path / f"{mode}.mp4"
    res = render_studio(p, out, lib)
    assert out.exists() and not res["warnings"]
    assert res["seconds"] == pytest.approx(30, abs=1.2)
    probe = subprocess.run([audio_io.ffmpeg(), "-hide_banner", "-i", str(out)], capture_output=True, text=True).stderr
    assert "Video: h264" in probe and "Audio: aac" in probe
    names = res["visuals"]
    assert len(names) == 3
    if mode == "single":
        assert set(names) == {"Aurora"}
    if mode == "per_song":
        assert names[1] == "Neon Tunnel"
    if mode in ("random", "auto"):
        assert len(set(names)) == 3


def test_studio_overlay_options(mixtape, lib, tmp_path, need_gl):
    """Per-video switch and the app-wide switch; on by default."""
    assert prefs.overlay_enabled() is True
    p = new_project(mixtape)
    p.markers[0].title, p.markers[0].artist = "A Fairly Long Title", "Somebody"
    base = dict(mode="single", single_shader="builtin:plasma", width=320, height=180, fps=8, crf=18, preset="ultrafast")
    frames = {}
    for label, per_video, app_wide in (("on", True, True), ("off_video", False, True), ("off_app", True, False)):
        prefs.set("show_overlay", app_wide)
        p.video = VideoSettings(show_overlay=per_video, **base)
        out = tmp_path / f"{label}.mp4"
        render_studio(p, out, lib)
        frames[label] = _first_frame(out)
    prefs.set("show_overlay", True)

    def card_pixels(a, b):
        d = np.abs(a - b).sum(axis=2)
        ys, xs = np.nonzero(d > 40)
        return len(ys), (ys.mean() if len(ys) else 0), (xs.mean() if len(xs) else 999)

    n, my, mx = card_pixels(frames["on"], frames["off_video"])
    assert n > 200 and my > 180 * 0.6 and mx < 320 * 0.5, "card should be in the lower left"
    assert card_pixels(frames["off_video"], frames["off_app"])[0] < 50, "app-wide switch must hide it too"


def test_build_segments_blends_follow_markers(mixtape, lib):
    p = new_project(mixtape)
    p.set_markers([{"time": 5, "title": "x"}, {"time": 15, "title": "y"}])     # nothing at 0:00
    segs, wins = build_segments(p, lib, 30.0)
    assert [s.start for s in segs] == [0.0, 5.0, 15.0] and segs[0].title == "Old Mix"
    assert len(wins) == 2 and wins[0][0] < 5 < wins[0][1] and wins[1][0] < 15 < wins[1][1]
