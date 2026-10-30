import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import synth  # noqa: E402

from lazy_mixtape_maker import audio_io  # noqa: E402
from lazy_mixtape_maker.engine import new_session  # noqa: E402
from lazy_mixtape_maker.plan import MixSettings  # noqa: E402
from lazy_mixtape_maker.playlist import expand_inputs, read_playlist  # noqa: E402


@pytest.fixture(scope="module")
def songs(tmp_path_factory):
    d = tmp_path_factory.mktemp("pl")
    out = {}
    for n, bpm, root in (("a", 100, 9), ("b", 140, 0), ("c", 120, 2)):
        f = d / f"S - {n}.wav"
        synth.make_song(f, bpm, root, True, structure=[("intro", 8), ("verse", 8), ("chorus", 8)], tags={"title": n, "artist": "S"})
        out[n] = f
    return d, out


def test_every_playlist_format_is_read_in_order(songs, tmp_path):
    d, s = songs
    order = ["b", "a", "c"]
    (d / "x.m3u").write_text("#EXTM3U\n#EXTINF:1,x\n" + "\n".join(s[n].name for n in order) + "\n")
    (d / "x.m3u8").write_text("﻿" + "\n".join(str(s[n]) for n in order), encoding="utf-8")
    (d / "x.pls").write_text("[playlist]\nFile3=%s\nFile1=%s\nFile2=%s\nNumberOfEntries=3\n" % (s["c"], s["b"], s["a"]))
    (d / "x.xspf").write_text('<?xml version="1.0"?><playlist version="1" xmlns="http://xspf.org/ns/0/"><trackList>'
                              + "".join(f"<track><location>{s[n].as_uri()}</location></track>" for n in order)
                              + "</trackList></playlist>")
    for ext in ("m3u", "m3u8", "pls", "xspf"):
        got = [p.name for p in read_playlist(d / f"x.{ext}")]
        assert got == [s[n].name for n in order], ext
    files, pl, missing = expand_inputs([d / "x.m3u"])
    assert pl and [f.name for f in files] == [s[n].name for n in order] and not missing


def test_missing_entries_are_reported_and_duplicates_dropped(songs):
    d, s = songs
    (d / "y.m3u").write_text(f"{s['a'].name}\nnope.mp3\n{s['a'].name}\nhttp://example.com/stream.mp3\n{s['b'].name}\n")
    files, pl, missing = expand_inputs([d / "y.m3u"])
    assert [f.name for f in files] == [s["a"].name, s["b"].name] and len(missing) == 1 and missing[0].endswith("nope.mp3")
    plain, pl2, _ = expand_inputs([d])
    assert not pl2 and len(plain) >= 3


def test_a_playlist_is_mixed_in_its_own_order(songs):
    d, s = songs
    (d / "z.m3u").write_text("\n".join(s[n].name for n in ("b", "a", "c")))
    files, pl, _ = expand_inputs([d / "z.m3u"])
    auto, _e = new_session(files, MixSettings(seed=1, overlap_bars=8))          # the AI would reorder these
    kept, _e = new_session(files, MixSettings(seed=1, overlap_bars=8, order="given"))
    titles = lambda sess: [sess.library[t.song_id].title for t in sess.plan.tracks]  # noqa: E731
    assert titles(kept) == ["b", "a", "c"]
    assert titles(auto) != ["b", "a", "c"]


def test_window_adds_a_playlist_and_keeps_its_order(tmp_path, monkeypatch):
    sys.path.insert(0, os.path.dirname(__file__))
    from test_oct25 import _gui_window
    app, w, d = _gui_window(tmp_path, monkeypatch, n=3)
    from lazy_mixtape_maker.gui import main_window as mw
    w.state.new()
    asked = []

    class FakeDlg(mw.GenerateDialog):
        def exec(self):
            asked.append((self.playlist, self.order.isChecked(), self.order.isEnabled()))
            return True
    monkeypatch.setattr(mw, "GenerateDialog", FakeDlg)
    w.run_task = lambda title, fn, done, *a, **k: done(fn(lambda *x: None, lambda: False))
    pl = tmp_path / "set.m3u"
    pl.write_text("\n".join(str(d / f"B - {n}.wav") for n in ("c", "a", "b")))
    w.add_files([str(pl)])
    assert asked == [(True, False, False)]                                  # "AI chooses the order" is off and locked
    titles = [w.state.lib[t.song_id].title for t in w.state.plan.tracks]
    assert titles == ["c", "a", "b"] and w.state.plan.settings.order == "given"
    w.state.dirty = False
    w.close()
