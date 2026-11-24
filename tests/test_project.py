"""Project folders: stems are kept in the mix's project folder; an unsaved mix uses a working folder that's
deleted once the mix is saved somewhere."""
import json
import os
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LMM_AUDIO_BACKEND", "null")
sys.path.insert(0, str(Path(__file__).parent))
import synth  # noqa: E402
from test_stems import fake_runner  # noqa: E402
from test_videofiles import TINY  # noqa: E402

from lazy_mixtape_maker import audio_io, project, stems  # noqa: E402
from lazy_mixtape_maker.engine import new_session  # noqa: E402
from lazy_mixtape_maker.plan import MixSettings  # noqa: E402
from lazy_mixtape_maker.session import save_session  # noqa: E402


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("LMM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(stems, "engine_python", lambda: sys.executable)
    songs = tmp_path / "songs"
    songs.mkdir()
    for name, bpm in (("one", 120), ("two", 124)):
        synth.make_song(songs / f"A - {name}.wav", bpm, 0, True, structure=TINY)
    return tmp_path


def _split(path, sid=None):
    return stems.split(path, sid, runner=fake_runner([]))


# ------------------------------------------------------------------ where things go
def test_save_path_becomes_a_project_folder(tmp_path):
    music = tmp_path / "Music"
    assert project.folder_for(music / "My Mix.lmm") == (music / "My Mix" / "My Mix.lmm", music / "My Mix")
    (music / "My Mix").mkdir(parents=True)
    assert project.folder_for(music / "My Mix" / "My Mix.lmm")[1] == music / "My Mix"     # already in its folder
    (music / "Other" / "stems").mkdir(parents=True)
    assert project.folder_for(music / "Other" / "renamed.lmm")[1] == music / "Other"     # an existing project


def test_new_stems_go_into_the_working_folder_then_move_on_save(env):
    work = project.new_working("Night drive")
    assert project.is_working(work) and work.parent == project.working_root()
    song = env / "songs" / "A - one.wav"
    got = _split(song)
    assert all(p.is_relative_to(work / "stems") for p in got.values())
    assert not (project.legacy_stems()).exists()                 # nothing in the old shared folder any more
    sid = audio_io.file_id(song) if hasattr(audio_io, "file_id") else stems.file_id(song)
    dest = project.move_to(env / "Music" / "Night drive", song_ids=[sid])
    assert not work.exists()                                       # the working folder is gone...
    moved = stems.cached(sid)
    assert moved and all(p.is_relative_to(dest / "stems") for p in moved.values())   # ...its stems moved over
    assert project.current() == dest


def test_save_as_from_a_saved_project_copies(env):
    first = project.move_to(env / "Music" / "First")
    song = env / "songs" / "A - one.wav"
    _split(song)
    sid = stems.file_id(song)
    second = project.move_to(env / "Music" / "Second")
    assert (first / "stems" / sid / "stems.json").exists()        # the saved project keeps its own
    assert (second / "stems" / sid / "stems.json").exists()


def test_old_shared_stems_are_still_used_and_copied_into_projects(env):
    song = env / "songs" / "A - two.wav"
    _split(song)                                                   # (no project: the old shared folder)
    sid = stems.file_id(song)
    assert (project.legacy_stems() / sid / "stems.json").exists()
    project.new_working()
    assert stems.cached(sid)                                       # found where earlier versions put it
    dest = project.move_to(env / "Music" / "Kept", song_ids=[sid])
    assert (dest / "stems" / sid / "stems.json").exists()
    assert (project.legacy_stems() / sid / "stems.json").exists()  # (left for any other old sessions using it)


def test_a_split_finishing_after_a_save_lands_in_the_new_project(env):
    project.new_working()
    song = env / "songs" / "A - one.wav"
    sid = stems.file_id(song)
    dest = {}

    def slow_runner(cmd, progress, cancel):
        dest["p"] = project.move_to(env / "Music" / "Saved meanwhile")    # the user saves while it runs
        return fake_runner([])(cmd, progress, cancel)
    stems.split(song, sid, runner=slow_runner)
    assert (dest["p"] / "stems" / sid / "stems.json").exists()


def test_left_behind_working_folders_are_cleaned_up(env):
    old = project.new_working("old")
    new = project.new_working("new")
    then = time.time() - 30 * 86400
    for f in [old, *old.rglob("*")]:
        os.utime(f, (then, then))
    assert project.clean_old_working(keep=new) == 1
    assert not old.exists() and new.exists()


# ------------------------------------------------------------------ in the app
@pytest.fixture()
def win(env, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from lazy_mixtape_maker.gui.main_window import MainWindow
    w = MainWindow()
    yield app, w
    w.state.dirty = False
    from PySide6.QtWidgets import QMessageBox           # (an unsaved mix with stems asks before closing)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Discard))
    w.close()


def _fill(w, env):
    s, _ = new_session(audio_io.list_audio_files([env / "songs"]), MixSettings(seed=1), name="Mix")
    st = w.state
    st.session = s
    for sid, p in s.paths.items():
        stems.split(p, sid, runner=fake_runner([]))
    st.dirty = True
    return s


def test_saving_in_the_app_makes_the_project_folder(win, env, monkeypatch):
    app, w = win
    work = project.current()
    assert work is not None and project.is_working(work)
    s = _fill(w, env)
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(env / "Music" / "Sunday.lmm"), "")))
    assert w.save_session()
    folder = env / "Music" / "Sunday"
    assert w.state.file == folder / "Sunday.lmm" and w.state.file.exists()
    assert not work.exists()
    for sid in s.paths:
        assert (folder / "stems" / sid / "stems.json").exists()
    doc = json.loads((folder / "Sunday.lmm").read_text())
    assert all(not Path(x["relpath"]).is_absolute() for x in doc["songs"])
    # opening it again finds the stems beside it
    w.state.dirty = False
    w.load_session(folder / "Sunday.lmm")
    assert project.current() == folder and all(stems.cached(sid) for sid in s.paths)


def test_discarding_an_unsaved_mix_asks_about_its_stems_then_deletes_them(win, env, monkeypatch):
    app, w = win
    work = project.current()
    _fill(w, env)
    w.state.dirty = False                       # even with nothing else changed, its stems are worth asking about
    from PySide6.QtWidgets import QMessageBox
    asked = []

    def answer(*a, **k):
        asked.append(a[2])
        return QMessageBox.StandardButton.Discard
    monkeypatch.setattr(QMessageBox, "question", staticmethod(answer))
    w.new_session()
    assert asked and "stems" in asked[0]
    assert not work.exists() and project.is_working(project.current())


def test_opening_an_older_session_saves_it_as_a_project(win, env):
    app, w = win
    s, _ = new_session(audio_io.list_audio_files([env / "songs"]), MixSettings(seed=1), name="Old")
    loose = env / "Music" / "old.lmm"
    loose.parent.mkdir(parents=True)
    save_session(s, loose)
    w.load_session(loose)
    assert project.is_working(project.current())         # no stems/ folder made in a plain Music folder
    assert not (loose.parent / "stems").exists()
    w.state.dirty = True
    assert w.save_session()
    assert w.state.file == env / "Music" / "old" / "old.lmm"


# ------------------------------------------------------------------ songs, exports and the old cache
def test_songs_are_copied_with_their_analysis(env):
    folder = env / "Music" / "P"
    src = env / "songs"
    (src / "A - one.wav.lmmanalysis").write_text("{}")
    paths = {f"id{i}": str(p) for i, p in enumerate(sorted(src.glob("*.wav")))}
    seen = []
    got = project.collect_songs(paths, folder, progress=lambda f, n: seen.append(f))
    assert all(Path(p).parent == folder / "songs" for p in got.values())
    assert (folder / "songs" / "A - one.wav.lmmanalysis").exists()            # no analysing it again
    assert seen[-1] == 1.0
    assert project.songs_to_copy(got, folder) == []                           # nothing left to copy
    # a different song with the same name doesn't overwrite the one already there
    other = env / "elsewhere"
    other.mkdir()
    synth.make_song(other / "A - one.wav", 90, 3, False, structure=TINY)
    again = project.collect_songs({"x": str(other / "A - one.wav")}, folder)
    assert Path(again["x"]).name == "A - one (2).wav"


def test_copying_can_be_cancelled(env):
    paths = {f"id{i}": str(p) for i, p in enumerate(sorted((env / "songs").glob("*.wav")))}
    with pytest.raises(project.Cancelled):
        project.collect_songs(paths, env / "P", cancel=lambda: True)


def test_a_saved_project_has_everything_and_can_move(win, env, monkeypatch):
    import shutil
    app, w = win
    s = _fill(w, env)
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(env / "Music" / "Trip.lmm"), "")))
    assert w.save_session()
    folder = env / "Music" / "Trip"
    doc = json.loads((folder / "Trip.lmm").read_text())
    assert all(x["relpath"].startswith("songs/") for x in doc["songs"])
    assert {p.name for p in (folder / "songs").iterdir()} >= {"A - one.wav", "A - two.wav"}
    # exports default to the project's exports folder
    assert project.default_dir(project.EXPORTS) == folder / "exports"
    # move the whole project somewhere else and lose the original songs: it still opens complete
    w.state.dirty = False
    w.state.new()
    (env / "Backup").mkdir()
    shutil.move(str(folder), str(env / "Backup" / "Trip"))
    shutil.rmtree(env / "songs")
    w.load_session(env / "Backup" / "Trip" / "Trip.lmm")
    assert not w.state.session.missing()
    assert all(Path(p).is_relative_to(env / "Backup" / "Trip" / "songs") for p in w.state.session.paths.values())
    assert all(stems.cached(sid) for sid in s.paths)


def test_copying_songs_can_be_switched_off(win, env, monkeypatch):
    from lazy_mixtape_maker import prefs
    app, w = win
    prefs.set("copy_songs", False)
    _fill(w, env)
    saved = w.state.save(env / "Music" / "Light.lmm")
    assert not (saved.parent / "songs").exists()
    assert all(Path(p).parent == env / "songs" for p in w.state.session.paths.values())


def test_unsaved_mixes_export_where_you_last_did(env):
    project.new_working()
    assert project.default_dir(project.EXPORTS) is None


def test_clearing_the_old_stem_cache(env):
    song = env / "songs" / "A - one.wav"
    _split(song)                                           # (no project: the old shared folder)
    assert project.legacy_size() > 0
    freed = project.clear_legacy()
    assert freed > 0 and project.legacy_size() == 0 and not project.legacy_stems().exists()


def test_cancelling_the_song_copy_cancels_the_save(win, env, monkeypatch):
    app, w = win
    work = project.current()
    _fill(w, env)
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(env / "Music" / "Nope.lmm"), "")))
    monkeypatch.setattr(type(w), "_copy_songs", lambda self, folder: None)    # the user pressed Cancel
    assert not w.save_session()
    assert w.state.file is None and project.current() == work and work.exists()
    assert not (env / "Music" / "Nope" / "Nope.lmm").exists()
