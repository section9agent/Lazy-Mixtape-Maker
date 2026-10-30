"""Command line front end: lmm mix | render | show | edit"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, audio_io, cue as cuemod, effects as fxmod, plan as planmod
from .engine import export_session, new_session
from .plan import MixSettings, recompute
from .session import Session, load_session, relink, save_session


def _progress():
    last = [""]

    def cb(msg, frac):
        line = f"\r[{int(frac * 100):3d}%] {msg}"[:100].ljust(100)
        if line != last[0]:
            sys.stderr.write(line)
            sys.stderr.flush()
            last[0] = line
    return cb


def _done():
    sys.stderr.write("\r" + " " * 100 + "\r")


def _fmt(sec):
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}"


def cmd_show(args):
    s = load_session(args.session, args.library or [])
    p = s.plan
    print(f"{s.name}  -  {p.master_bpm:.1f} BPM (median), mode={p.settings.mode}, tempo={p.settings.tempo_mode}, {len(p.tracks)} tracks")
    rows = cuemod.tracklist(p, s.library)
    for i, (t, r) in enumerate(zip(p.tracks, rows)):
        an = s.library[t.song_id]
        found = "" if t.song_id in s.paths else "  [FILE NOT FOUND]"
        pitch = f" pitch{t.pitch:+d}" if t.pitch else ""
        print(f"{i + 1:2d}. {_fmt(r['cue']):>6}  {an.artist + ' - ' if an.artist else ''}{an.title}"
              f"  [{an.camelot} {an.bpm:.0f}bpm -> plays {t.bpm:.1f}{pitch}{'' if t.matched else ' UNMATCHED'}]{found}")
        for e in t.effects:
            print(f"        fx {e.id} {e.type} @{e.anchor}{e.offset:+.1f}s for {e.duration:.1f}s{' (ai)' if e.auto else ''}")
        tr = p.transition_after(i)
        if tr:
            print(f"      -> {tr.type}, {tr.overlap_beats} beats"
                  f"{f' at {tr.tempo:.1f} BPM' if tr.tempo else ''}{'' if tr.matched else ' (tempos too far apart)'}{' (ai)' if tr.auto else ''}")


def cmd_mix(args):
    from .playlist import expand_inputs
    files, from_playlist, missing = expand_inputs(args.inputs)
    for m in missing:
        sys.stderr.write(f"Playlist entry not found, skipped: {m}\n")
    if from_playlist:
        args.keep_order = True            # a playlist is mixed in its own order
    if len(files) < 2:
        sys.exit("Need at least two supported audio files (mp3, wav, flac, m4a).")
    settings = MixSettings(
        mode=args.mode, clip_seconds=args.clip_seconds, overlap_bars=args.overlap_bars,
        master_bpm=args.bpm, order="given" if args.keep_order else "auto", seed=args.seed,
        use_effects=not args.no_effects, key_match=not args.no_key_match, tempo_mode=args.tempo_mode,
        transition_style=args.transition_style,
    )
    cb = _progress()
    session, errors = new_session(files, settings, cb, name=args.name or Path(args.output).stem)
    for f, e in errors.items():
        sys.stderr.write(f"\nSkipped {f}: {e}")
    if args.session:
        save_session(session, args.session)
    res = export_session(session, args.output, cb)
    _done()
    print(f"Mix written: {res['audio']}  ({_fmt(res['seconds'])})")
    if "cue" in res:
        print(f"Cue sheet:   {res['cue']}")
    if args.session:
        print(f"Session:     {args.session}")


def cmd_render(args):
    s = load_session(args.session, args.library or [])
    miss = s.missing()
    if miss:
        sys.exit("Cannot find: " + ", ".join(a.title for a in miss) + "\nUse --library <folder> to point at your copy of the songs.")
    cb = _progress()
    res = export_session(s, args.output, cb)
    _done()
    print(f"Mix written: {res['audio']}  ({_fmt(res['seconds'])})")


def cmd_video(args):
    from .video import MODES, VideoSettings, attach_to_session, render_video, restore_from_session
    from .visuals import ShaderLibrary

    s = load_session(args.session, args.library or [])
    miss = s.missing()
    if miss:
        sys.exit("Cannot find: " + ", ".join(a.title for a in miss) + "\nUse --library <folder> to point at your copy of the songs.")
    shaders = ShaderLibrary()
    vs = restore_from_session(s, shaders)
    for path in args.add_shader or []:
        sh = shaders.add_from_file(path)
        print(f"Added visual: {sh.name}")
        if args.mode is None:
            vs.mode, vs.single_shader = "single", sh.id
    if args.mode:
        vs.mode = args.mode
    if args.visual:
        match = [x for x in shaders.all() if args.visual.lower() in (x.id.lower(), x.name.lower())]
        if not match:
            sys.exit("No visual called '%s'. Built in: %s" % (args.visual, ", ".join(x.name for x in shaders.all())))
        vs.single_shader = match[0].id
        vs.mode = "single"
    vs.width, vs.height, vs.fps = args.width, args.height, args.fps
    if args.seed is not None:
        vs.seed = args.seed
    if args.no_overlay:
        vs.show_overlay = False
    cb = _progress()
    res = render_video(s.plan, s.library, s.paths, args.output, vs, shaders, progress=cb, extra=s.extra)
    _done()
    print(f"Video written: {res['video']}  ({_fmt(res['seconds'])}, visuals: {', '.join(res['visuals'])})")
    for w in res["warnings"]:
        print("Note:", w)


def cmd_studio(args):
    """Make a video for an audio file you already have (a mixtape made elsewhere)."""
    from . import studio
    from .visuals import ShaderLibrary
    shaders = ShaderLibrary()
    if args.project:
        p = studio.load_project(args.project, shaders, args.library or [])
        if not Path(p.audio).is_file():
            sys.exit("Cannot find the project's audio file. Use --library <folder> to point at it.")
    else:
        if not args.audio:
            sys.exit("Give an audio file or --project.")
        p = studio.new_project(args.audio)
    if args.cue:
        p.set_markers(studio.import_cue_file(args.cue))
        print(f"{len(p.markers)} song markers from {Path(args.cue).name}")
    for path in args.add_shader or []:
        sh = shaders.add_from_file(path)
        print(f"Added visual: {sh.name}")
        if args.mode is None and not args.visual:
            args.visual = sh.name
    vs = p.video
    if args.mode:
        vs.mode = args.mode
    if args.visual:
        match = [x for x in shaders.all() if args.visual.lower() in (x.id.lower(), x.name.lower())]
        if not match:
            sys.exit("No visual called '%s'. Available: %s" % (args.visual, ", ".join(x.name for x in shaders.all())))
        vs.single_shader, vs.mode = match[0].id, "single"
    if args.width: vs.width = args.width
    if args.height: vs.height = args.height
    if args.fps: vs.fps = args.fps
    if args.blend is not None: vs.blend = args.blend
    if args.seed is not None: vs.seed = args.seed
    if args.no_overlay: vs.show_overlay = False
    if args.save_project:
        studio.save_project(p, args.save_project, shaders)
        print(f"Project saved: {args.save_project}")
    if not args.output:
        return
    res = studio.render_studio(p, args.output, shaders, progress=_progress())
    _done()
    print(f"Video written: {res['video']}  ({_fmt(res['seconds'])}, visuals: {', '.join(res['visuals'])})")
    for w in res["warnings"]:
        print("Note:", w)


def cmd_config(args):
    from . import prefs
    if args.overlay:
        prefs.set("show_overlay", args.overlay == "on")
    print("Cover art / artist / title on videos:", "on" if prefs.overlay_enabled() else "off")


def cmd_edit(args):
    s = load_session(args.session, args.library or [])
    p, lib = s.plan, s.library
    a = args
    if a.edit_cmd == "move":
        planmod.move_track(p, lib, a.src - 1, a.dst - 1)
    elif a.edit_cmd == "remove":
        planmod.remove_track(p, lib, a.track - 1)
    elif a.edit_cmd == "add":
        from .engine import analyze_library
        files = audio_io.list_audio_files([a.file])
        l2, paths, errs = analyze_library(files)
        if errs:
            sys.exit(str(errs))
        for sid, an in l2.items():
            lib[sid] = an
            s.paths[sid] = paths[sid]
            planmod.add_track(p, lib, sid, None if a.position is None else a.position - 1)
    elif a.edit_cmd == "transition":
        planmod.set_transition(p, lib, a.after - 1, a.type, a.beats)
    elif a.edit_cmd == "bounds":
        planmod.set_track_bounds(p, lib, a.track - 1, a.start, a.end)
    elif a.edit_cmd == "fx-add":
        params = dict(kv.split("=", 1) for kv in (a.param or []))
        params = {k: (float(v) if v.replace(".", "", 1).replace("-", "", 1).isdigit() else v) for k, v in params.items()}
        e = planmod.add_effect(p, a.track - 1, a.type, a.anchor, a.offset, a.duration, params)
        print(f"Added effect {e.id}")
    elif a.edit_cmd == "fx-update":
        ch = {}
        if a.offset is not None:
            ch["offset"] = a.offset
        if a.duration is not None:
            ch["duration"] = a.duration
        planmod.update_effect(p, a.track - 1, a.effect_id, **ch)
    elif a.edit_cmd == "fx-remove":
        planmod.remove_effect(p, a.track - 1, a.effect_id)
    elif a.edit_cmd == "replan":
        recompute(p, lib)
    save_session(s, a.session)
    print("Session updated.")


def build_parser():
    ap = argparse.ArgumentParser(prog="lmm", description="Lazy Mixtape Maker - offline auto-DJ")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("mix", help="analyse songs and generate a mix")
    m.add_argument("inputs", nargs="+", help="audio files, folders and/or playlists (.m3u .m3u8 .pls .xspf; a playlist is mixed in its own order)")
    m.add_argument("-o", "--output", required=True, help="output file: .wav, .mp3 (320k) or .flac")
    m.add_argument("--session", help="also save an editable session file (.lmm)")
    m.add_argument("--name", help="mix title")
    m.add_argument("--mode", choices=["full", "clips"], default="full",
                   help="full = use whole songs (default); clips = short rave.dj-style highlights")
    m.add_argument("--clip-seconds", type=float, default=30.0)
    m.add_argument("--overlap-bars", type=int, default=32, help="longest blend in bars (whole outro/intro is used up to this)")
    m.add_argument("--bpm", type=float, help="force one fixed tempo for the whole mix")
    m.add_argument("--tempo-mode", choices=["drift", "locked"], default="drift",
                   help="drift = tempo glides from song to song (default); locked = one tempo throughout")
    m.add_argument("--keep-order", action="store_true", help="don't reorder songs")
    m.add_argument("--no-effects", action="store_true")
    m.add_argument("--no-key-match", action="store_true")
    m.add_argument("--transition-style", choices=["auto", "eq_swap", "crossfade", "cut"], default="auto")
    m.add_argument("--seed", type=int, default=0)
    m.set_defaults(fn=cmd_mix)

    r = sub.add_parser("render", help="render a saved session to audio")
    r.add_argument("session")
    r.add_argument("-o", "--output", required=True)
    r.add_argument("--library", action="append", help="folder containing your copy of the songs (repeatable)")
    r.set_defaults(fn=cmd_render)

    v = sub.add_parser("video", help="render an mp4 with Shadertoy-style visuals for a saved session")
    v.add_argument("session")
    v.add_argument("-o", "--output", required=True, help="output .mp4")
    v.add_argument("--library", action="append")
    v.add_argument("--mode", choices=["auto", "random", "per_song", "single"],
                   help="auto = app chooses, random = new random visual each song, single = one visual throughout")
    v.add_argument("--visual", help="name of a visual (built-in or imported) to use for the whole video")
    v.add_argument("--add-shader", action="append", help="import a Shadertoy .glsl/.json file first (kept for later)")
    v.add_argument("--width", type=int, default=1280); v.add_argument("--height", type=int, default=720)
    v.add_argument("--fps", type=int, default=30); v.add_argument("--seed", type=int)
    v.add_argument("--no-overlay", action="store_true", help="leave out the cover / artist / title card")
    v.set_defaults(fn=cmd_video)

    st = sub.add_parser("studio", help="make a video for an existing mixtape audio file (+ optional cue sheet)")
    st.add_argument("audio", nargs="?", help="mp3 / wav / flac / m4a")
    st.add_argument("-o", "--output", help="output .mp4")
    st.add_argument("--cue", help=".cue sheet or text track list: marks where the songs change")
    st.add_argument("--project", help="open a saved .lmv project instead of an audio file")
    st.add_argument("--save-project", help="save the project (.lmv) so it can be edited in the app")
    st.add_argument("--library", action="append", help="folder to look for the project's audio in")
    st.add_argument("--mode", choices=["auto", "random", "per_song", "single"])
    st.add_argument("--visual", help="one visual (by name) for the whole video")
    st.add_argument("--add-shader", action="append")
    st.add_argument("--blend", type=float, help="visual cross-fade length in seconds (default 6)")
    st.add_argument("--width", type=int); st.add_argument("--height", type=int)
    st.add_argument("--fps", type=int); st.add_argument("--seed", type=int)
    st.add_argument("--no-overlay", action="store_true", help="leave out the cover / artist / title card")
    st.set_defaults(fn=cmd_studio)

    cf = sub.add_parser("config", help="app-wide options")
    cf.add_argument("--overlay", choices=["on", "off"], help="cover art / artist / title on every video (default on)")
    cf.set_defaults(fn=cmd_config)

    sh = sub.add_parser("show", help="print a session's tracklist, transitions and effects")
    sh.add_argument("session")
    sh.add_argument("--library", action="append")
    sh.set_defaults(fn=cmd_show)

    e = sub.add_parser("edit", help="change a saved session")
    e.add_argument("session")
    e.add_argument("--library", action="append")
    es = e.add_subparsers(dest="edit_cmd", required=True)
    x = es.add_parser("move"); x.add_argument("src", type=int); x.add_argument("dst", type=int)
    x = es.add_parser("remove"); x.add_argument("track", type=int)
    x = es.add_parser("add"); x.add_argument("file"); x.add_argument("--position", type=int)
    x = es.add_parser("transition", help="timing/type of the blend after a track")
    x.add_argument("after", type=int); x.add_argument("--type", choices=["eq_swap", "crossfade", "cut_fx", "cut"])
    x.add_argument("--beats", type=int, help="blend length in beats")
    x = es.add_parser("bounds", help="where a song starts/ends playing (source seconds)")
    x.add_argument("track", type=int); x.add_argument("--start", type=float); x.add_argument("--end", type=float)
    x = es.add_parser("fx-add")
    x.add_argument("track", type=int); x.add_argument("type", choices=list(fxmod.EFFECT_TYPES))
    x.add_argument("--anchor", choices=["start", "end"], default="end")
    x.add_argument("--offset", type=float); x.add_argument("--duration", type=float, default=2.0)
    x.add_argument("--param", action="append", help="key=value, e.g. feedback=0.6")
    x = es.add_parser("fx-update")
    x.add_argument("track", type=int); x.add_argument("effect_id")
    x.add_argument("--offset", type=float); x.add_argument("--duration", type=float)
    x = es.add_parser("fx-remove"); x.add_argument("track", type=int); x.add_argument("effect_id")
    es.add_parser("replan", help="let the AI redo everything you haven't edited by hand")
    e.set_defaults(fn=cmd_edit)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.fn(args)
    except (audio_io.AudioError, ValueError, KeyError, IndexError) as ex:
        _done()
        sys.exit(f"Error: {ex}")


if __name__ == "__main__":
    main()
