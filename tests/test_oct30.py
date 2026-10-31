"""Shader-or-video choice (mix + studio), and the project settings windows."""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LMM_AUDIO_BACKEND", "null")
sys.path.insert(0, str(Path(__file__).parent))
import synth  # noqa: E402
from test_videofiles import TINY, make_video  # noqa: E402

from lazy_mixtape_maker import audio_io, studio as st  # noqa: E402
from lazy_mixtape_maker.engine import new_session  # noqa: E402
from lazy_mixtape_maker.plan import MixSettings  # noqa: E402
from lazy_mixtape_maker.session import save_session  # noqa: E402
from lazy_mixtape_maker.video import build_mix_segments  # noqa: E402


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("LMM_DATA_DIR", str(tmp_path / "data"))
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _mix_window(tmp_path):
    from lazy_mixtape_maker.gui.main_window import MainWindow
    d = tmp_path / "s"
    d.mkdir()
    synth.make_song(d / "A - one.wav", 120, 9, True, structure=TINY, tags={"title": "one", "artist": "A"})
    synth.make_song(d / "wavB.wav", 124, 0, True, structure=TINY, tags={"title": "two", "artist": "B"})
    make_video(d / "C - clip.mp4", d / "wavB.wav", "red")
    (d / "wavB.wav").unlink()
    synth.make_song(d / "D - plain.wav", 122, 4, True, structure=TINY, tags={"title": "plain", "artist": "D"})
    s, _ = new_session(audio_io.list_audio_files([d]), MixSettings(seed=1, overlap_bars=2, order="given"))
    save_session(s, tmp_path / "m.lmm")
    w = MainWindow()
    w.show()
    w.load_session(tmp_path / "m.lmm")
    return w, d


def _seg_videos(w):
    st_ = w.state
    segs, _ = build_mix_segments(st_.plan, st_.lib, st_.paths, st_.video, st_.shaders, w.tmp, 60.0)
    return [sg.video for sg in segs]


def test_mix_can_switch_between_a_shader_and_the_songs_video(app, tmp_path):
    w, d = _mix_window(tmp_path)
    s = w.state
    vi = next(i for i, t in enumerate(s.plan.tracks) if s.paths[t.song_id].endswith(".mp4"))
    uid = s.plan.tracks[vi].uid
    s.select(vi)
    tab = w.inspector.vis_tab
    tab._refresh()
    datas = [tab.combo.itemData(i) for i in range(tab.combo.count())]
    assert datas[0] == "@video" and tab.combo.currentData() == "@video"           # the video is what plays, and is listed
    assert _seg_videos(w)[vi] and _seg_videos(w)[vi].endswith(".mp4")
    shader = s.shaders.all()[1].id
    tab._assign(shader)                                                          # a shader instead of the video
    assert _seg_videos(w)[vi] is None and s.video.assignments[uid] == shader
    tab._refresh()
    assert tab.combo.currentData() == shader and tab.combo.itemData(0) == "@video"
    tab._assign("@video")                                                        # and back
    assert uid not in s.video.assignments and _seg_videos(w)[vi].endswith(".mp4")
    s.undo()
    assert _seg_videos(w)[vi] is None                                            # undo / redo follow it
    s.redo()
    assert _seg_videos(w)[vi].endswith(".mp4")
    # a clip that was chosen can be switched back to after trying a shader
    clip = str(d / "C - clip.mp4")
    tab._assign("@clip:" + clip)
    assert _seg_videos(w)[vi] == clip
    tab._assign(shader)
    assert _seg_videos(w)[vi] is None and s.video.clips[uid] == clip
    tab._refresh()
    assert tab.combo.findData("@clip:" + clip) >= 0
    tab._assign("@clip:" + clip)
    assert _seg_videos(w)[vi] == clip
    s.dirty = False
    w.close()


def test_studio_can_switch_between_a_shader_and_the_video(app, tmp_path):
    from lazy_mixtape_maker.gui.studio_window import StudioWindow
    d = tmp_path / "s"
    d.mkdir()
    synth.make_song(d / "song.wav", 120, 0, True, structure=TINY, tags={"title": "t", "artist": "a"})
    clip = d / "c.mp4"
    make_video(clip, d / "song.wav", "blue")
    p = st.new_project(d / "song.wav")
    p.add_marker(6.0, "B", "second")
    uid = p.markers[1].uid
    p.set_clip(uid, clip)
    win = StudioWindow()
    win.hist = st.StudioHistory(p)
    win.refresh(rebuild_lists=True)
    win.select(uid)

    def video_of(u):
        segs, _ = st.build_segments(win.project, win.shaders, 20.0)
        return next(sg.video for sg in segs if sg.uid == u)

    def choose(data):
        win.f_visual.setCurrentIndex(win.f_visual.findData(data))
        win._pick_visual(0)
    assert video_of(uid) == str(clip) and win.f_visual.currentData() == "@clip"
    choose(win.shaders.all()[2].id)                                              # a shader instead of the video
    m = win.project.find(uid)
    assert video_of(uid) is None and m.clip["off"] is True and m.clip["path"] == str(clip)    # the video is kept
    assert win.f_visual.currentData() == win.shaders.all()[2].id and win.f_visual.findData("@clip") >= 0
    assert win.timeline.clips == []                                              # and it isn't drawn as a placed video
    assert "Not shown" in win.c_note.text()
    choose("@clip")                                                              # back to the video
    assert video_of(uid) == str(clip) and "off" not in win.project.find(uid).clip and len(win.timeline.clips) == 1
    win.hist.undo()                                                              # undo goes back to the shader...
    win.refresh()
    assert video_of(uid) is None
    win.hist.redo()                                                              # ...and redo to the video
    win.refresh()
    assert video_of(uid) == str(clip)
    win.dirty = False
    win.close()
    # a video file as the source: pick a shader for a song, then go back to the file's own video
    mv = d / "src.mp4"
    make_video(mv, d / "song.wav", "green")
    p2 = st.new_project(mv)
    p2.add_marker(6.0, "", "b")
    win2 = StudioWindow()
    win2.hist = st.StudioHistory(p2)
    win2.refresh(rebuild_lists=True)
    u2 = p2.markers[1].uid
    win2.select(u2)
    assert win2.f_visual.itemData(0) == "@video" and win2.f_visual.currentData() == "@video"

    def v2(u):
        segs, _ = st.build_segments(win2.project, win2.shaders, 20.0)
        return next(sg.video for sg in segs if sg.uid == u)
    assert v2(u2) == str(mv)
    win2.f_visual.setCurrentIndex(win2.f_visual.findData(win2.shaders.all()[1].id))
    win2._pick_visual(0)
    assert v2(u2) is None
    win2.f_visual.setCurrentIndex(win2.f_visual.findData("@video"))
    win2._pick_visual(0)
    assert v2(u2) == str(mv) and win2.project.find(u2).shader == ""
    win2.dirty = False
    win2.close()


def test_mix_project_settings_without_starting_over(app, tmp_path):
    w, _d = _mix_window(tmp_path)
    s = w.state
    from lazy_mixtape_maker.gui import main_window as mw
    order = [t.uid for t in s.plan.tracks]
    s.edit(lambda p, lib: setattr(p.tracks[1], "src_start", p.tracks[1].src_start + 1.0))
    s.plan.tracks[1].auto_bounds = False
    trim = s.plan.tracks[1].src_start
    seen = {}

    class Fake(mw.GenerateDialog):
        rebuild_on = False

        def exec(self):
            seen["title"], seen["has_box"] = self.windowTitle(), self.rebuild is not None
            seen["order"] = self.order.isChecked()
            self.bars.setValue(5)
            self.style.setCurrentIndex(self.style.findData("crossfade"))
            self.rebuild.setChecked(Fake.rebuild_on)
            return True
    monkeypatch_dialog = mw.GenerateDialog
    mw.GenerateDialog = Fake
    try:
        w.project_settings()
        assert seen["title"] == "Project settings" and seen["has_box"] and seen["order"] is False      # given order shown as such
        assert s.plan.settings.overlap_bars == 5 and s.plan.settings.transition_style == "crossfade"
        assert [t.uid for t in s.plan.tracks] == order and s.plan.tracks[1].src_start == trim          # nothing was thrown away
        s.undo()
        assert s.plan.settings.overlap_bars == 2                                                       # undoable
        s.redo()
        Fake.rebuild_on = True
        w.project_settings()                                                                           # now the mix is made again
        assert s.plan.tracks[1].auto_bounds is True
    finally:
        mw.GenerateDialog = monkeypatch_dialog
    s.dirty = False
    w.close()


def test_studio_project_settings(app, tmp_path):
    from lazy_mixtape_maker.gui import studio_window as sw
    from lazy_mixtape_maker.gui.studio_settings import StudioSettingsDialog
    d = tmp_path / "s"
    d.mkdir()
    synth.make_song(d / "song.wav", 120, 0, True, structure=TINY, tags={"title": "t", "artist": "a"})
    p = st.new_project(d / "song.wav")
    p.add_marker(5.0, "B", "second")
    win = sw.StudioWindow()
    win.hist = st.StudioHistory(p)
    win.refresh(rebuild_lists=True)
    dlg = StudioSettingsDialog(win.project.video, win.shaders, False)
    assert dlg.changes() == {} and not dlg.use_video.isEnabled()
    seen = {}

    class Fake(sw.StudioSettingsDialog):
        def exec(self):
            seen["mode"] = self.mode.currentData()
            self.mode.setCurrentIndex(self.mode.findData("per_song"))
            self.res.setCurrentIndex(self.res.findData("1920x1080"))
            self.fps.setCurrentIndex(self.fps.findData(60))
            self.overlay.setChecked(False)
            self.blend.setValue(3.0)
            self.trans.type.setCurrentIndex(self.trans.type.findData("wipe"))
            return True
    orig = sw.StudioSettingsDialog
    sw.StudioSettingsDialog = Fake
    try:
        win.project_settings()
    finally:
        sw.StudioSettingsDialog = orig
    v = win.project.video
    assert (v.mode, v.width, v.height, v.fps, v.show_overlay, v.blend) == ("per_song", 1920, 1080, 60, False, 3.0)
    assert v.transition["type"] == "wipe"
    assert all(m.shader for m in win.project.markers)                  # "I choose per song" starts from what was shown
    win.hist.undo()
    assert win.project.video.width == 1280 and win.project.video.mode != "per_song"
    win.dirty = False
    win.close()
