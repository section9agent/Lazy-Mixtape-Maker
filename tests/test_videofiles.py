"""Video files as inputs, and the 20 video transitions."""
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LMM_AUDIO_BACKEND", "null")
sys.path.insert(0, str(Path(__file__).parent))
import synth  # noqa: E402

from lazy_mixtape_maker import audio_io, transitions as tr  # noqa: E402
from lazy_mixtape_maker.engine import new_session  # noqa: E402
from lazy_mixtape_maker.plan import MixSettings  # noqa: E402
from lazy_mixtape_maker.video import (AudioTexture, FrameComposer, GLRenderer, Segment, VideoSettings,  # noqa: E402
                                      attach_to_session, render_video, restore_from_session)
from lazy_mixtape_maker.visuals import ShaderLibrary, make_context  # noqa: E402

TINY = [("intro", 2), ("verse", 4), ("chorus", 4), ("outro", 2)]


@pytest.fixture(scope="module", autouse=True)
def need_gl():
    try:
        make_context().release()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"no OpenGL available: {e}")


@pytest.fixture()
def lib(tmp_path, monkeypatch):
    monkeypatch.setenv("LMM_DATA_DIR", str(tmp_path / "data"))
    return ShaderLibrary()


def make_video(path: Path, wav: Path, color="red"):
    subprocess.run([audio_io.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=96x54:r=15:d=40",
                    "-i", str(wav), "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)],
                   check=True)


def frame_at(video, t):
    raw = subprocess.run([audio_io.ffmpeg(), "-v", "error", "-ss", str(t), "-i", str(video), "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, 3).mean(axis=0)


def test_there_are_twenty_transitions():
    assert len(tr.TRANSITIONS) == 20 and len(set(tr.KEYS)) == 20
    kinds = [k for *_, k, _ in [(t[0], t[2], t[3]) for t in tr.TRANSITIONS]]
    assert kinds.count("standard") == 12 and kinds.count("rhythm") == 8
    assert sorted(tr.GL_ID.values()) == list(range(20))
    p = tr.TransitionParams.from_dict({"type": "nope", "intensity": 9, "duration": -2})
    assert p.type == "crossfade" and p.intensity == 2.0 and p.duration == 0.0
    # random choices are stable per seed, valid, and never repeat back to back
    base = tr.TransitionParams(type="random")
    picks = [tr.resolve(base, 5, i).type for i in range(12)]
    assert picks == [tr.resolve(base, 5, i).type for i in range(12)]
    assert all(p in tr.KEYS for p in picks) and all(a != b for a, b in zip(picks, picks[1:]))
    assert all(tr.KIND[tr.resolve(tr.TransitionParams(type="random_rhythm"), 1, i).type] == "rhythm" for i in range(8))


def test_every_transition_starts_on_one_picture_and_ends_on_the_other(lib):
    red = lib.add("Static A", "void mainImage(out vec4 c,in vec2 p){ vec2 u=p/iResolution.xy; c=vec4(0.9,u.x*0.5,u.y*0.4,1.0);}")
    blue = lib.add("Static B", "void mainImage(out vec4 c,in vec2 p){ vec2 u=p/iResolution.xy; c=vec4(u.y*0.4,0.3,0.95,1.0);}")
    ids = [red.id, blue.id]
    sr = 11025
    loud = np.random.default_rng(0).uniform(-.6, .6, (1, sr * 10)).astype(np.float32)
    segs = [Segment("a", 0, ids[0], "", ""), Segment("b", 5, ids[1], "", "")]
    r = GLRenderer(96, 54, AudioTexture(loud, sr))
    try:
        for k in tr.KEYS:
            vs = VideoSettings(width=96, height=54, show_overlay=False, transition=tr.TransitionParams(type=k).to_dict())
            comp = FrameComposer(segs, [(4, 6)], 10, vs, lib, bpm=120)
            before = np.frombuffer(comp.draw(r, 3.0, 0), np.uint8).astype(float)
            start = np.frombuffer(comp.draw(r, 4.0, 0), np.uint8).astype(float)
            end = np.frombuffer(comp.draw(r, 6.0, 0), np.uint8).astype(float)
            after = np.frombuffer(comp.draw(r, 6.5, 0), np.uint8).astype(float)
            mid = np.frombuffer(comp.draw(r, 5.0, 0), np.uint8).astype(float)
            assert np.abs(start - before).mean() < 4, f"{k}: the transition should begin on the outgoing picture"
            assert np.abs(end - after).mean() < 4, f"{k}: the transition should end on the incoming picture"
            assert np.abs(mid - before).mean() > 3, f"{k}: nothing happens in the middle"
    finally:
        r.release()


def test_rhythm_transitions_react_to_the_music(lib):
    sr = 11025
    quiet = np.zeros((1, sr * 10), np.float32)
    kicks = np.zeros((1, sr * 10), np.float32)
    t = np.arange(int(0.12 * sr)) / sr
    for b in np.arange(0.0, 10.0, 0.5):                   # a kick every half second
        i = int(b * sr)
        kicks[0, i:i + len(t)] += (np.sin(2 * np.pi * 55 * t) * np.exp(-t * 18) * 0.9).astype(np.float32)
    sa = lib.add("Static A", "void mainImage(out vec4 c,in vec2 p){ vec2 u=p/iResolution.xy; c=vec4(0.9,fract(u.x*6.0)*0.5,u.y*0.4,1.0);}")
    sb = lib.add("Static B", "void mainImage(out vec4 c,in vec2 p){ vec2 u=p/iResolution.xy; c=vec4(u.y*0.4,fract(u.y*8.0)*0.5,0.95,1.0);}")
    segs = [Segment("a", 0, sa.id, "", ""), Segment("b", 5, sb.id, "", "")]
    for k in ("beat_zoom", "beat_flash", "glitch", "beat_shake"):
        out = {}
        for name, audio, sens in (("quiet", quiet, 1.0), ("kick", kicks, 1.0), ("ignored", kicks, 0.0)):
            vs = VideoSettings(width=96, height=54, show_overlay=False,
                               transition=tr.TransitionParams(type=k, sensitivity=sens, intensity=1.5).to_dict())
            comp = FrameComposer(segs, [(3, 7)], 10, vs, lib)
            r = GLRenderer(96, 54, AudioTexture(audio, sr))
            try:
                # a moment just after a kick vs. the same transition with silence
                out[name] = np.frombuffer(comp.draw(r, 5.02, 0), np.uint8).astype(float)
            finally:
                r.release()
        assert np.abs(out["kick"] - out["quiet"]).mean() > 1.0, f"{k} should react to a kick"
        assert np.abs(out["ignored"] - out["quiet"]).mean() < 0.5, f"{k} with sensitivity 0 should ignore the music"


def test_video_files_are_used_in_a_mix_and_follow_the_transition_settings(lib, tmp_path):
    d = tmp_path / "s"
    d.mkdir()
    synth.make_song(d / "A - one.wav", 120, 9, True, structure=TINY, tags={"title": "one", "artist": "A"})
    synth.make_song(d / "wavB.wav", 124, 0, True, structure=TINY, tags={"title": "two", "artist": "B"})
    make_video(d / "C - clip.mp4", d / "wavB.wav", "red")
    (d / "wavB.wav").unlink()
    synth.make_song(d / "D - plain.wav", 122, 4, True, structure=TINY, tags={"title": "plain", "artist": "D"})
    files = audio_io.list_audio_files([d])
    assert any(f.suffix == ".mp4" for f in files)
    s, errs = new_session(files, MixSettings(seed=1, overlap_bars=2), name="v")
    assert not errs and len(s.plan.tracks) == 3
    vs = VideoSettings(width=96, height=54, fps=6, preset="ultrafast", show_overlay=False, mode="single",
                       transition=tr.TransitionParams(type="wipe", duration=2.0).to_dict())
    out = tmp_path / "m.mp4"
    res = render_video(s.plan, s.library, s.paths, out, vs, lib)
    assert out.exists() and any(v.endswith(".mp4") for v in res["visuals"])
    # while the video song plays the picture is the (red) video; while the plain song plays it is a visual
    from lazy_mixtape_maker.plan import timeline
    slots = timeline(s.plan)
    for i, t in enumerate(s.plan.tracks):
        mid = (slots[i].start + slots[i].end) / 2 / 44100
        col = frame_at(out, mid)
        is_video = s.paths[t.song_id].endswith(".mp4")
        if is_video:
            assert col[0] > 150 and col[1] < 60 and col[2] < 60, f"expected the red video, got {col}"
        else:
            assert not (col[0] > 150 and col[1] < 60 and col[2] < 60)
    # turning the option off shows the visual even for the video file
    vs2 = VideoSettings(width=96, height=54, fps=6, preset="ultrafast", show_overlay=False, mode="single", use_video=False)
    out2 = tmp_path / "m2.mp4"
    res2 = render_video(s.plan, s.library, s.paths, out2, vs2, lib)
    assert not any(v.endswith(".mp4") for v in res2["visuals"])


def test_transition_settings_travel_with_a_session(lib):
    from lazy_mixtape_maker.session import Session
    vs = VideoSettings(transition=tr.TransitionParams(type="glitch", intensity=1.7).to_dict(),
                       transitions={"abc": tr.TransitionParams(type="iris", duration=3).to_dict()}, use_video=False,
                       assignments={"u1": "@clip:/x/y.mp4"})
    s = Session()
    attach_to_session(s, vs, lib)
    again = restore_from_session(Session.from_dict(s.to_dict()) if hasattr(Session, "from_dict") else s, lib)
    assert again.transition["type"] == "glitch" and again.transitions["abc"]["duration"] == 3
    assert again.use_video is False and again.assignments["u1"] == "@clip:/x/y.mp4"


def test_studio_with_a_video_file_and_clip_and_own_transition(lib, tmp_path):
    from lazy_mixtape_maker import studio
    wav = tmp_path / "m.wav"
    sr = 44100
    audio_io.write_audio(wav, np.random.default_rng(1).uniform(-.3, .3, (2, sr * 12)).astype(np.float32))
    src = tmp_path / "mixtape.mp4"
    make_video(src, wav, "red")
    clip = tmp_path / "blue.mp4"
    subprocess.run([audio_io.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=64x36:r=12:d=3",
                    "-pix_fmt", "yuv420p", str(clip)], check=True)
    p = studio.new_project(src)
    assert studio.has_source_video(p) and p.duration > 11
    m2 = p.add_marker(6.0, "B", "Second")
    p.video.mode = "random"
    p.video.blend = 1.0
    p.video.show_overlay = False
    p.video.width, p.video.height, p.video.fps, p.video.preset = 96, 54, 6, "ultrafast"
    p.video.transitions[m2.uid] = tr.TransitionParams(type="push", duration=1.0).to_dict()
    labels = studio.visual_labels(p, lib)
    assert set(labels.values()) == {"Source video"}
    out = tmp_path / "s.mp4"
    studio.render_studio(p, out, lib)
    c1, c2 = frame_at(out, 2.0), frame_at(out, 9.0)
    assert c1[0] > 150 and c1[1] < 60 and c2[0] > 150 and c2[1] < 60          # the file's own picture, all the way through
    # the second song gets a looping clip instead
    p.update_marker(m2.uid, shader="@clip:" + str(clip))
    p.video.mode = "per_song"
    assert studio.visual_labels(p, lib)[m2.uid].startswith("Clip:")
    out2 = tmp_path / "s2.mp4"
    studio.render_studio(p, out2, lib)
    c3 = frame_at(out2, 10.5)                                                  # clip is 3 s long: it must have looped
    assert c3[2] > 150 and c3[0] < 60, f"expected the looping blue clip, got {c3}"
    # persistence
    f = tmp_path / "p.lmv"
    studio.save_project(p, f, lib)
    q = studio.load_project(f, lib, [tmp_path])
    assert q.video.transitions[m2.uid]["type"] == "push" and q.find(m2.uid).shader.startswith("@clip:")


def test_gui_editors(tmp_path, monkeypatch):
    monkeypatch.setenv("LMM_DATA_DIR", str(tmp_path / "data"))
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from lazy_mixtape_maker.gui.transition_editor import TransitionEditor
    e = TransitionEditor(allow_inherit=True)
    assert e.value() is None                                  # "use the default" until changed
    e.set_value({"type": "wipe", "angle": 90, "softness": 0.5, "duration": 2.5})
    v = e.value()
    assert v["type"] == "wipe" and v["angle"] == 90 and v["duration"] == 2.5
    assert e.rows["angle"][1].isEnabled() and not e.rows["sensitivity"][1].isEnabled()    # only the controls that matter
    e.set_value({"type": "glitch"})
    assert e.rows["sensitivity"][1].isEnabled() and not e.rows["angle"][1].isEnabled()
    assert e.type.count() >= 20 + len(tr.RANDOM_CHOICES)
    # the mix window has the tab, and the studio shows the controls
    from lazy_mixtape_maker.gui.main_window import MainWindow
    w = MainWindow()
    names = [w.bottom.tabText(i) for i in range(w.bottom.count())]
    assert "Video transitions" in names
    w.transitions.default.type.setCurrentIndex(w.transitions.default.type.findData("kick_spin"))
    w.transitions.default._timer.timeout.emit()
    assert w.state.video.transition["type"] == "kick_spin"
    w.state.dirty = False
    w.close()
