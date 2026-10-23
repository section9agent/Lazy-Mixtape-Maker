"""Application state shared by every part of the window: the session, the visuals
library, the selection, and undo / redo of plan edits."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .. import plan as planmod
from ..plan import MixPlan, MixSettings
from ..session import Session, load_session, relink, save_session
from ..video import VideoSettings, attach_to_session, restore_from_session
from ..visuals import ShaderLibrary


class AppState(QObject):
    changed = Signal()          # the plan (or video settings) changed
    selection = Signal()        # selected track / effect changed
    library_changed = Signal()  # songs added / session loaded
    title_changed = Signal()

    def __init__(self, shaders: ShaderLibrary | None = None):
        super().__init__()
        self.session = Session()
        self.shaders = shaders or ShaderLibrary()
        self.video = VideoSettings()
        self.file: Path | None = None
        self.dirty = False
        self.sel = -1
        self.sel_fx: str | None = None
        self.preview_path: str | None = None   # rendered preview of the current plan
        self._undo: list[str] = []
        self._redo: list[str] = []
        self._gesture = False

    # ---------------------------------------------------------------- shortcuts
    @property
    def plan(self) -> MixPlan:
        return self.session.plan

    @property
    def lib(self):
        return self.session.library

    @property
    def paths(self):
        return self.session.paths

    def title(self) -> str:
        name = self.file.name if self.file else self.session.name
        return f"{name}{' *' if self.dirty else ''}"

    # ---------------------------------------------------------------- selection
    def select(self, index: int, fx: str | None = None):
        index = index if 0 <= index < len(self.plan.tracks) else -1
        if index != self.sel or fx != self.sel_fx:
            self.sel, self.sel_fx = index, fx
            self.selection.emit()

    def slot_seconds(self, i: int) -> float:
        slots = planmod.timeline(self.plan)
        return slots[i].length / 44100.0 if 0 <= i < len(slots) else 0.0

    def selected_track(self):
        return self.plan.tracks[self.sel] if 0 <= self.sel < len(self.plan.tracks) else None

    # --------------------------------------------------------------- undo / redo
    def _snap(self) -> str:
        return json.dumps({"plan": self.plan.to_dict(), "video": self.video.to_dict()})

    def _restore(self, snap: str):
        d = json.loads(snap)
        self.session.plan = MixPlan.from_dict(d["plan"])
        self.video = VideoSettings.from_dict(d["video"])

    def _push(self, snap: str):
        self._undo.append(snap)
        del self._undo[:-60]
        self._redo.clear()

    def begin_gesture(self):
        """A drag: one undo step however many edits happen during it."""
        self._push(self._snap())
        self._gesture = True

    def end_gesture(self):
        self._gesture = False
        if self._undo and self._undo[-1] == self._snap():   # a click, not a drag
            self._undo.pop()

    def edit(self, fn, *, audio: bool = True):
        """Run fn(plan, library) as one undoable edit."""
        snap = self._snap()
        try:
            fn(self.plan, self.lib)
        except Exception:
            self._restore(snap)
            self.changed.emit()
            raise
        if not self._gesture:
            self._push(snap)
        self._mark(audio)

    def edit_video(self, fn):
        snap = self._snap()
        fn(self.video)
        self._push(snap)
        self._mark(audio=False)

    def _mark(self, audio: bool = True):
        self.dirty = True
        if audio:
            self.preview_path = None
        self.changed.emit()
        self.title_changed.emit()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self):
        if self._undo:
            self._redo.append(self._snap())
            self._restore(self._undo.pop())
            self.sel = min(self.sel, len(self.plan.tracks) - 1)
            self._mark()

    def redo(self):
        if self._redo:
            self._undo.append(self._snap())
            self._restore(self._redo.pop())
            self._mark()

    # ------------------------------------------------------------------ songs
    def add_songs(self, lib: dict, paths: dict, settings: MixSettings | None = None):
        """Songs that finished analysing. The first batch is mixed by the AI; later
        ones are appended to the end of the mix."""
        new_ids = [i for i in lib if i not in {t.song_id for t in self.plan.tracks}]
        self.session.library.update(lib)
        self.session.paths.update(paths)
        if not new_ids:
            self.library_changed.emit()
            return

        def fn(plan, library):
            if not plan.tracks:
                self.session.plan = planmod.plan_mix(library, new_ids, settings or plan.settings)
            else:
                for sid in new_ids:
                    planmod.add_track(plan, library, sid)

        self.edit(fn)
        self.library_changed.emit()

    def generate(self, settings: MixSettings):
        """Rebuild the whole mix from the songs currently in it (hand edits are discarded)."""
        ids = [t.song_id for t in self.plan.tracks] or list(self.lib)

        def fn(plan, library):
            self.session.plan = planmod.plan_mix(library, ids, settings)
            self.video.assignments = {}

        self.edit(fn)
        self.sel, self.sel_fx = -1, None
        self.selection.emit()

    # ---------------------------------------------------------------- sessions
    def new(self):
        self.session = Session()
        self.video = VideoSettings()
        self.file, self.dirty, self.sel, self.sel_fx = None, False, -1, None
        self._undo.clear(); self._redo.clear()
        self.preview_path = None
        self.library_changed.emit(); self.changed.emit(); self.title_changed.emit()

    def open(self, path, search_dirs=()):
        s = load_session(path, search_dirs)
        self.session = s
        self.video = restore_from_session(s, self.shaders)
        self.file, self.dirty, self.sel, self.sel_fx = Path(path), False, -1, None
        self._undo.clear(); self._redo.clear()
        self.preview_path = None
        self.library_changed.emit(); self.changed.emit(); self.title_changed.emit()

    def save(self, path=None):
        path = Path(path or self.file)
        attach_to_session(self.session, self.video, self.shaders, self.plan)
        self.session.name = path.stem
        save_session(self.session, path)
        self.file, self.dirty = path, False
        self.title_changed.emit()

    def relink(self, folder) -> list[str]:
        missing = relink(self.session, None, [folder])
        self.preview_path = None
        self.library_changed.emit()
        self.changed.emit()
        return missing
