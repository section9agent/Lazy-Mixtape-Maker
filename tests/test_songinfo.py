import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_oct25 import _gui_window  # noqa: E402,F401  (builds a window with a small mix)

from lazy_mixtape_maker import songinfo  # noqa: E402
from lazy_mixtape_maker.session import load_session, save_session  # noqa: E402


def _png(path, rgb):
    from PIL import Image
    Image.new("RGB", (80, 60), rgb).save(path)
    return str(path)


def test_song_info_edit_undo_save_and_cover(tmp_path, monkeypatch):
    app, w, d = _gui_window(tmp_path, monkeypatch, n=3)
    st = w.state
    sid = st.plan.tracks[1].song_id
    orig = (st.lib[sid].artist, st.lib[sid].title)
    assert orig[0] == "B" and orig[1] in ("a", "b", "c")                     # prefilled from the file's tags
    red = _png(tmp_path / "red.png", (255, 0, 0))
    st.edit_info(sid, "New Artist", "New Title", red)
    assert (st.lib[sid].artist, st.lib[sid].title) == ("New Artist", "New Title")
    assert "New Title" in w.list.item(1).text()                              # the list shows it straight away
    over = songinfo.overrides(st.session.extra, w.tmp)
    assert sid in over and over[sid].endswith(".jpg")
    # undo / redo bring back the old and new information
    st.undo()
    assert (st.lib[sid].artist, st.lib[sid].title) == orig and songinfo.overrides(st.session.extra, w.tmp) == {}
    st.redo()
    assert st.lib[sid].title == "New Title" and sid in songinfo.overrides(st.session.extra, w.tmp)
    # saved in the session, cover included, and read back
    st.save(tmp_path / "info.lmm")
    s2 = load_session(tmp_path / "info.lmm", [d])
    assert s2.library[sid].title == "New Title" and sid in songinfo.overrides(s2.extra, tmp_path)
    # "no cover" and "the file's cover"
    st.edit_info(sid, cover="none")
    assert songinfo.overrides(st.session.extra, w.tmp) == {sid: None}
    st.edit_info(sid, cover="file")
    assert songinfo.overrides(st.session.extra, w.tmp) == {}
    # the dialog flow in the window: starts with the current values, Reset goes back to the file's tags
    from lazy_mixtape_maker.gui import main_window as mw
    seen = {}

    class Fake(mw.SongInfoDialog):
        def exec(self):
            seen["artist"], seen["title"] = self.artist.text(), self.title.text()
            seen["file"] = (self.file_artist, self.file_title)
            self._reset()
            return True
    monkeypatch.setattr(mw, "SongInfoDialog", Fake)
    st.select(1)
    w.edit_song_info()
    assert seen["artist"] == "New Artist" and seen["file"] == orig
    assert (st.lib[sid].artist, st.lib[sid].title) == orig
    st.dirty = False
    w.close()


def test_cover_and_title_reach_the_video_card(tmp_path, monkeypatch):
    app, w, d = _gui_window(tmp_path, monkeypatch, n=2)
    from lazy_mixtape_maker.video import build_mix_segments
    st = w.state
    sid = st.plan.tracks[0].song_id
    st.edit_info(sid, "Zed", "Custom", _png(tmp_path / "g.png", (0, 255, 0)))
    covers = songinfo.overrides(st.session.extra, tmp_path)
    segs, _w = build_mix_segments(st.plan, st.lib, st.paths, st.video, st.shaders, tmp_path, 60.0, covers)
    assert (segs[0].artist, segs[0].title) == ("Zed", "Custom") and segs[0].cover == covers[sid]
    st.dirty = False
    w.close()


def test_studio_song_info_dialog(tmp_path, monkeypatch):
    monkeypatch.setenv("LMM_DATA_DIR", str(tmp_path / "data"))
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    import synth
    from lazy_mixtape_maker import studio
    from lazy_mixtape_maker.gui import studio_window as sw
    f = tmp_path / "Art - Tune.wav"
    synth.make_song(f, 120, 0, True, structure=[("intro", 8), ("verse", 8)], tags={"title": "Tune", "artist": "Art"})
    win = sw.StudioWindow()
    win.show()
    proj = studio.new_project(f)
    proj.add_marker(10.0, "", "")
    win.hist = studio.StudioHistory(proj)
    win.refresh(rebuild_lists=True)
    first, second = proj.markers[0], proj.markers[1]
    seen = {}
    green = _png(tmp_path / "g.png", (0, 255, 0))

    class Fake(sw.SongInfoDialog):
        def exec(self):
            seen[len(seen)] = (self.artist.text(), self.title.text(), self.file_artist, self.file_title)
            self.artist.setText("Edited"); self.title.setText("Edited title")
            self._set(green, green)
            return True
    monkeypatch.setattr(sw, "SongInfoDialog", Fake)
    win.select(first.uid)
    assert first.artist == "Art" and first.title == "Tune"                 # pre-filled from the file's tags
    win._song_info()
    assert seen[0] == ("Art", "Tune", "Art", "Tune")
    assert (first.artist, first.title, first.cover) == ("Edited", "Edited title", green)
    win.select(second.uid)
    win._song_info()
    assert (second.artist, second.title) == ("Edited", "Edited title") and seen[1][2:] == ("", "")
    win.hist.undo() if hasattr(win.hist, "undo") else None
    win.dirty = False
    win.close()
