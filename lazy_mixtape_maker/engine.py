"""High-level API used by the CLI now and the GUI later."""
from __future__ import annotations

from pathlib import Path

from . import audio_io, cue as cuemod
from .analysis import analyze_file
from .plan import MixSettings, plan_mix
from .render import render_mix
from .session import Session


def analyze_library(files, progress=None, cache_dir=None, force=False):
    """Analyse songs. Returns (library, paths, errors)."""
    lib, paths, errors = {}, {}, {}
    files = list(files)
    for i, f in enumerate(files):
        def tick(stage, frac, i=i, f=f):
            if progress:
                progress(f"analysing {f.name}: {stage}", (i + frac) / len(files))
        try:
            an = analyze_file(f, cache_dir=cache_dir, force=force, progress=tick)
            lib[an.id] = an
            paths[an.id] = str(Path(f).resolve())
        except Exception as e:  # keep going; report at the end
            errors[str(f)] = str(e)
    return lib, paths, errors


def new_session(files, settings: MixSettings | None = None, progress=None, name="Untitled mixtape") -> tuple[Session, dict]:
    lib, paths, errors = analyze_library(files, progress)
    if len(lib) < 2:
        raise ValueError("Need at least two analysable songs to make a mix")
    plan = plan_mix(lib, list(lib), settings or MixSettings())
    return Session(library=lib, plan=plan, paths=paths, name=name), errors


def export_session(session: Session, out_path, progress=None, write_cue: bool = True, audio=None) -> dict:
    out_path = Path(out_path)
    notes: list = []
    if audio is None:
        audio = render_mix(session.plan, session.library, session.paths, progress=progress, notes=notes)
    meta = {"title": session.name, "artist": "Lazy Mixtape Maker"}
    audio_io.write_audio(out_path, audio, metadata=meta)
    result = {"audio": str(out_path), "seconds": audio.shape[1] / audio_io.SR, "notes": notes}
    if write_cue:
        cue_path = out_path.with_suffix(".cue")
        txt_path = out_path.with_suffix(".tracklist.txt")
        cuemod.write_cue(cue_path, session.plan, session.library, out_path.name, title=session.name)
        cuemod.write_tracklist_txt(txt_path, session.plan, session.library)
        result.update(cue=str(cue_path), tracklist=str(txt_path))
    session.export = {"format": out_path.suffix.lower().lstrip(".")}
    return result


def export_both(session: Session, audio_path, video_path, video_settings=None, shaders=None, progress=None,
                cancel=None, write_cue: bool = True) -> dict:
    """Render the mix once, save it as audio (plus cue sheet) and use the same render for the video."""
    from .video import render_video

    say = progress or (lambda msg, frac: None)
    audio = render_mix(session.plan, session.library, session.paths, progress=lambda m, f: say(m, 0.35 * f))
    if cancel and cancel():
        from .video import Cancelled
        raise Cancelled("Cancelled")
    res = export_session(session, audio_path, write_cue=write_cue, audio=audio)
    say("saved the audio", 0.38)
    vid = render_video(session.plan, session.library, session.paths, video_path, video_settings, shaders,
                       audio=audio, progress=lambda m, f: say(m, 0.38 + 0.62 * f), cancel=cancel,
                       extra=session.extra)
    res.update(video=vid["video"], warnings=vid.get("warnings", []))
    return res


PREVIEW_SCOPES = (("transition", "1 transition (2 songs)"), ("four", "4 songs"), ("mix", "Whole mix"))


def preview_songs(plan, scope: str, at: float) -> tuple[int, int] | None:
    """Which songs a short preview covers: the transition nearest `at` (seconds into the mix) and its two songs,
    or four songs around it (three transitions). None means the whole mix."""
    from .plan import timeline

    n = len(plan.tracks)
    if scope not in ("transition", "four") or n < 2:
        return None
    slots = timeline(plan)
    mids = [(slots[i + 1].start + slots[i + 1].overlap_in / 2) / audio_io.SR for i in range(n - 1)]
    i = min(range(n - 1), key=lambda k: abs(mids[k] - at))
    if scope == "transition" or n <= 2:
        return i, i + 1
    first = max(0, min(i - 1, n - 4))
    return first, min(n - 1, first + 3)


def preview_window(plan, scope: str, at: float, lead: float = 10.0, tail: float = 10.0) -> tuple[float, float] | None:
    """The stretch of the mix (start, end seconds) a short preview plays: from `lead` seconds before the first
    blend of the songs preview_songs() picks to `tail` seconds after the last one. None means the whole mix."""
    from .plan import timeline

    got = preview_songs(plan, scope, at)
    if got is None:
        return None
    first, last = got
    slots = timeline(plan)
    sr = audio_io.SR
    t0 = slots[first + 1].start / sr - lead
    t1 = (slots[last].start + slots[last].overlap_in) / sr + tail
    if last - first == 1 and slots[last].overlap_in == 0:      # a hard cut: hear a little more either side
        t0, t1 = t0 - 4.0, t1 + 4.0
    return max(0.0, t0), min(slots[-1].end / sr, t1)


def transition_preview_plan(plan, index: int, before: float = 14.0, after: float = 14.0):
    """A small copy of the plan with just songs `index` and `index + 1`, trimmed to a
    few seconds either side of the blend, so a transition can be auditioned quickly."""
    from .plan import MixPlan

    p = MixPlan.from_dict(plan.to_dict())
    if not 0 <= index < len(p.tracks) - 1:
        raise IndexError("There is no transition after the last song")
    a, b = p.tracks[index], p.tracks[index + 1]
    tr = p.transition_after(index)
    from .plan import overlap_seconds

    ov = overlap_seconds(p, tr)
    a.src_start = max(a.src_start, a.src_end - (ov + before) * max(a.rate, a.rate_out or a.rate))
    b.src_end = min(b.src_end, b.src_start + (ov + after) * max(b.rate, b.rate_in or b.rate))
    a.auto_bounds = b.auto_bounds = False
    a.effects = [e for e in a.effects if e.anchor == "end"]
    b.effects = [e for e in b.effects if e.anchor == "start"]
    p.tracks, p.transitions = [a, b], [tr]
    return p
