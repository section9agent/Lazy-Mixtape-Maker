"""MilkDrop presets, drawn by libprojectM (LGPL-2.1, loaded as a separate library through ctypes).

A MilkDrop visual is a Shader with kind="milkdrop" whose source is the .milk preset text, so it goes
everywhere a Shadertoy visual goes (the app's picks, per-song choices, the studios, sessions).
`MilkRenderer` draws them into a GLRenderer's scene textures, one projectM instance per preset.

Where things are found:
  libprojectM      LMM_PROJECTM_LIB, the packaged app's projectm/ folder, packaging/projectm, the system
  the preset pack  LMM_MILKDROP_PACK, the packaged app's milkdrop/presets, packaging/milkdrop/presets
  textures         LMM_MILKDROP_TEXTURES, the packaged app's milkdrop/textures, packaging/milkdrop/textures
  featured set     lazy_mixtape_maker/assets/milkdrop/featured (featured.json + the .milk files + textures/)
"""
from __future__ import annotations

import ctypes
import ctypes.util
import json
import os
import re
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np

PM_RATE = 44100                    # projectM analyses audio as 44.1 kHz
TEX_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".tga", ".dds")


class MilkError(RuntimeError):
    pass


# ------------------------------------------------------------------------ where things are
def _bundle() -> Path | None:
    b = getattr(sys, "_MEIPASS", None)
    return Path(b) if b else None


def _repo() -> Path:
    return Path(__file__).resolve().parent.parent


def assets_dir() -> Path:
    return Path(__file__).resolve().parent / "assets" / "milkdrop"


def featured_dir() -> Path:
    return assets_dir() / "featured"


def _first_dir(env: str, sub: str) -> Path | None:
    cands = [os.environ.get(env, "")]
    if _bundle():
        cands.append(str(_bundle() / "milkdrop" / sub))
    cands.append(str(_repo() / "packaging" / "milkdrop" / sub))
    for c in cands:
        if c and Path(c).is_dir():
            return Path(c)
    return None


def pack_dir() -> Path | None:
    """The full preset pack (Cream of the Crop), when this install has it."""
    return _first_dir("LMM_MILKDROP_PACK", "presets")


def textures_dir() -> Path | None:
    return _first_dir("LMM_MILKDROP_TEXTURES", "textures")


# ------------------------------------------------------------------------ the library
def _lib_candidates():
    env = os.environ.get("LMM_PROJECTM_LIB", "")
    if env:
        yield env
    names = {"win32": ["projectM-4.dll", "libprojectM-4.dll"],
             "darwin": ["libprojectM-4.dylib", "libprojectM-4.4.dylib"]}.get(sys.platform, ["libprojectM-4.so", "libprojectM-4.so.4"])
    bases = ([_bundle() / "projectm", _bundle()] if _bundle() else []) + [_repo() / "packaging" / "projectm"]
    pat = {"win32": "*projectM-4*.dll", "darwin": "libprojectM-4*.dylib"}.get(sys.platform, "libprojectM-4.so*")
    for base in bases:
        for n in names:
            for p in (base / n, base / "lib" / n, base / "lib64" / n, base / "bin" / n):
                if p.exists():
                    yield str(p)
        for sub in ("", "lib", "lib64", "bin"):          # whatever version suffix this OS's build gave it
            d = base / sub
            if d.is_dir():
                for p in sorted(d.glob(pat)):
                    yield str(p)
    found = ctypes.util.find_library("projectM-4")
    if found:
        yield found


_why = ""


@lru_cache(maxsize=1)
def library():
    """The loaded libprojectM (None when this computer hasn't got it - MilkDrop presets then draw as a
    built-in visual)."""
    global _why
    errors = []
    for c in _lib_candidates():
        try:
            if sys.platform == "win32" and os.path.isabs(c):
                os.add_dll_directory(os.path.dirname(c))
            lib = ctypes.CDLL(c)
            _declare(lib)
            return lib
        except (OSError, AttributeError) as e:
            errors.append(f"{c}: {e}")
    _why = "; ".join(errors) or "libprojectM wasn't found (set LMM_PROJECTM_LIB to the library file)"
    return None


def available() -> bool:
    return library() is not None


def why_unavailable() -> str:
    library()
    return _why


FAILED_CB = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p)


def _declare(lib) -> None:
    H, sz = ctypes.c_void_p, ctypes.c_size_t
    sig = {
        "projectm_create": ([], H),
        "projectm_destroy": ([H], None),
        "projectm_load_preset_data": ([H, ctypes.c_char_p, ctypes.c_bool], None),
        "projectm_set_window_size": ([H, sz, sz], None),
        "projectm_set_frame_time": ([H, ctypes.c_double], None),
        "projectm_opengl_render_frame_fbo": ([H, ctypes.c_uint32], None),
        "projectm_pcm_add_float": ([H, ctypes.POINTER(ctypes.c_float), ctypes.c_uint, ctypes.c_int], None),
        "projectm_set_texture_search_paths": ([H, ctypes.POINTER(ctypes.c_char_p), sz], None),
        "projectm_set_preset_locked": ([H, ctypes.c_bool], None),
        "projectm_set_hard_cut_enabled": ([H, ctypes.c_bool], None),
        "projectm_set_preset_duration": ([H, ctypes.c_double], None),
        "projectm_set_fps": ([H, ctypes.c_int32], None),
        "projectm_set_mesh_size": ([H, sz, sz], None),
        "projectm_set_preset_switch_failed_event_callback": ([H, FAILED_CB, ctypes.c_void_p], None),
    }
    for name, (args, res) in sig.items():
        f = getattr(lib, name)          # AttributeError: too old a libprojectM (4.1 lacks the frame-time calls)
        f.argtypes, f.restype = args, res


# ------------------------------------------------------------------------ preset files
_KEYS = ("zoom", "rot", "warp", "fdecay", "nwavemode", "wave_r", "wave_g", "wave_b", "wave_a", "ob_size", "ib_size",
         "frating", "fgammaadj", "fvideoechozoom", "milkdrop_preset_version", "psversion", "decay", "cx", "cy", "dx",
         "dy", "sx", "sy", "fwavescale", "badditivewaves", "bwavedots", "echo_zoom", "mv_x", "mv_y")


def looks_like_preset(text: str) -> bool:
    """True for MilkDrop 1/2 preset text (a [preset00] header, or enough of the usual settings)."""
    if not text or "mainImage" in text:
        return False
    if re.search(r"^\s*\[preset\d*\]\s*$", text, re.M | re.I):
        return True
    keys = {m.lower() for m in re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", text, re.M)}
    code = any(k.startswith(("per_frame_", "per_pixel_", "warp_", "comp_", "wavecode_", "shapecode_")) for k in keys)
    return len(keys & set(_KEYS)) >= 2 or (code and len(keys & set(_KEYS)) >= 1)


def preset_name(path) -> str:
    """A readable name from a preset's file name ("Author - Title"), without the pack's edit notes."""
    stem = Path(path).stem
    name = re.split(r"\s+---\s+|\s+nz\+", stem)[0].replace("_", " ")
    name = re.sub(r"\s+", " ", name).strip(" -")
    return (name[:57].rstrip(" -,") + "…") if len(name) > 60 else (name or "MilkDrop preset")


_BUILTIN_TEX = re.compile(r"^(main|blur\d|noise_(lq|mq|hq)(_lite)?|noisevol_(lq|hq)|rand\d+(_.*)?)$")


def referenced_textures(text: str) -> set[str]:
    """Names of the picture files a preset's shader code reads (not MilkDrop's own built-in textures)."""
    out = set()
    for m in re.findall(r"sampler_([A-Za-z0-9_]+)", text or ""):
        name = re.sub(r"^(fw|fc|pw|pc)_", "", m.lower())
        if not _BUILTIN_TEX.match(name):
            out.add(name)
    return out


_CALM = ("hypnotic", "waveform", "drawing")
_HIGH = ("supernova", "sparkle", "particles", "dancer")


def energy_for(category: str) -> str:
    c = (category or "").lower()
    return "high" if any(k in c for k in _HIGH) else "calm" if any(k in c for k in _CALM) else "mid"


def category_of(path) -> str:
    """The pack category a preset file is in (its top folder in the pack - presets sit in Category/Author/),
    or for a file from elsewhere, the nearest folder named like a category."""
    p = Path(path).resolve()
    root = pack_dir()
    if root is not None:
        try:
            parts = p.relative_to(root.resolve()).parts
            if len(parts) > 1:
                return parts[0].lstrip("! ").strip()
        except ValueError:
            pass
    for folder in p.parents:
        n = folder.name.lower()
        if energy_for(n) != "mid" or n in ("fractal", "geometric", "reaction"):
            return folder.name
    return p.parent.name


@lru_cache(maxsize=1)
def _featured_cached(stamp: float) -> tuple:
    f = featured_dir() / "featured.json"
    try:
        items = json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return ()
    out = []
    for it in items:
        p = featured_dir() / it["file"]
        if p.exists():
            out.append({**it, "path": str(p)})
    return tuple(out)


def featured() -> list[dict]:
    """The hand-picked presets that come with the app: [{id, name, file, category, energy, author, path}]."""
    f = featured_dir() / "featured.json"
    return list(_featured_cached(f.stat().st_mtime if f.exists() else 0.0))


def browse(query: str = "") -> dict[str, list[Path]]:
    """Category -> preset files of the full pack (or of the featured set when the pack isn't installed),
    filtered by words in the file name."""
    words = [w for w in (query or "").lower().split() if w]
    root = pack_dir()
    out: dict[str, list[Path]] = {}
    if root is None:
        for it in featured():
            out.setdefault(it["category"], []).append(Path(it["path"]))
    else:
        for cat in sorted(d for d in root.iterdir() if d.is_dir()):
            name = cat.name.lstrip("! ").strip()
            if name.lower() == "transition":
                continue
            out[name] = sorted(cat.rglob("*.milk"), key=lambda p: p.name.lower())
    if words:
        out = {c: [p for p in ps if all(w in p.stem.lower() for w in words)] for c, ps in out.items()}
    return {c: ps for c, ps in out.items() if ps}


# ------------------------------------------------------------------------ the music it reacts to
def music_at(audio, t0: float, t1: float) -> np.ndarray:
    """Mono 44.1 kHz samples between two moments of the mix (a steady made-up beat when there's no music yet,
    so previews still pulse)."""
    t1 = max(t1, t0 + 1.0 / 240)
    n = max(64, min(int((t1 - t0) * PM_RATE), PM_RATE))
    ts = t0 + (np.arange(n) + 1) * ((t1 - t0) / n)
    mono = getattr(audio, "mono", None) if audio is not None else None
    if mono is None or not len(mono):
        ph = np.mod(ts, 0.5)
        x = 0.7 * np.sin(2 * np.pi * 55 * ts) * np.exp(-ph * 14) + 0.12 * np.sin(2 * np.pi * 440 * ts) \
            * (0.6 + 0.4 * np.sin(ts * 1.7)) + 0.05 * np.sin(2 * np.pi * 1870 * ts) * np.exp(-np.mod(ts + 0.25, 0.5) * 30)
        return x.astype(np.float32)
    sr = audio.sr
    idx = ts * sr
    i0 = max(0, int(idx[0]) - 1)
    i1 = min(len(mono), int(idx[-1]) + 2)
    if i1 - i0 < 2:
        return np.zeros(n, np.float32)
    return np.interp(idx, np.arange(i0, i1), mono[i0:i1]).astype(np.float32)


# ------------------------------------------------------------------------ one preset, live
class MilkInstance:
    def __init__(self, lib, text: str, w: int, h: int, fps: int, tex_paths: list[str]):
        self.lib = lib
        self.failed = ""
        self.h = lib.projectm_create()
        if not self.h:
            raise MilkError("projectM couldn't start (it needs OpenGL 3.3)")
        self._cb = FAILED_CB(self._on_fail)                 # keep a reference: projectM calls it later
        lib.projectm_set_preset_switch_failed_event_callback(self.h, self._cb, None)
        lib.projectm_set_window_size(self.h, w, h)
        lib.projectm_set_fps(self.h, int(fps))
        lib.projectm_set_mesh_size(self.h, 64 if w > 900 else 48, 48 if w > 900 else 36)
        lib.projectm_set_preset_locked(self.h, True)
        lib.projectm_set_hard_cut_enabled(self.h, False)
        lib.projectm_set_preset_duration(self.h, 1e9)
        if tex_paths:
            arr = (ctypes.c_char_p * len(tex_paths))(*[p.encode("utf-8") for p in tex_paths])
            lib.projectm_set_texture_search_paths(self.h, arr, len(tex_paths))
        lib.projectm_set_frame_time(self.h, 0.0)
        lib.projectm_load_preset_data(self.h, text.encode("utf-8", "replace"), False)
        if self.failed:
            self.close()
            raise MilkError(self.failed)
        self.last_t = None
        self.used = 0

    def _on_fail(self, fname, message, _user):
        self.failed = (message or b"").decode("utf-8", "replace") or "projectM couldn't read the preset"

    def feed(self, samples: np.ndarray) -> None:
        s = np.ascontiguousarray(samples, dtype=np.float32)
        self.lib.projectm_pcm_add_float(self.h, s.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), len(s), 1)

    def frame(self, t: float, fbo: int) -> None:
        self.lib.projectm_set_frame_time(self.h, float(t))
        self.lib.projectm_opengl_render_frame_fbo(self.h, int(fbo))
        self.last_t = t

    def close(self) -> None:
        if self.h:
            self.lib.projectm_destroy(self.h)
            self.h = None


class MilkRenderer:
    """Draws MilkDrop presets into a GLRenderer's scene textures (one projectM instance per preset).

    projectM's picture builds up from frame to frame, so a preset is "warmed up" for WARMUP seconds
    whenever it starts or its clock jumps (a seek, or its song starting again)."""

    MAX_LIVE = 6
    WARMUP = 1.5

    def __init__(self, r):
        lib = library()
        if lib is None:
            raise MilkError("MilkDrop isn't available: " + why_unavailable())
        self.lib, self.r = lib, r
        self.live: dict[str, MilkInstance] = {}
        self.clock = 0

    def _texture_paths(self, sh) -> list[str]:
        from .visuals import folder_of
        out = []
        own = folder_of(sh.id)
        if own:
            out.append(str(own))
        for d in (featured_dir() / "textures", textures_dir()):
            if d is not None and Path(d).is_dir():
                out.append(str(d))
        return out

    def _get(self, sh) -> MilkInstance:
        key = f"{sh.id}:{hash(sh.source)}"
        inst = self.live.get(key)
        if inst is None:
            if len(self.live) >= self.MAX_LIVE:               # forget the one used longest ago
                old = min(self.live, key=lambda k: self.live[k].used)
                self.live.pop(old).close()
            inst = MilkInstance(self.lib, sh.source, self.r.w, self.r.h, self.r.fps, self._texture_paths(sh))
            self.live[key] = inst
        self.clock += 1
        inst.used = self.clock
        return inst

    def draw(self, sh, t: float, slot: int, audio_t: float | None = None) -> None:
        r = self.r
        fbo = r.scene[slot][1].glo
        inst = self._get(sh)
        at = t if audio_t is None else audio_t
        audio = r.audio if audio_t is not None else None
        step = 1.0 / max(1, r.fps)
        jump = inst.last_t is None or t < inst.last_t - 1e-6 or t > inst.last_t + 1.0
        if jump:
            if inst.last_t is not None:                      # restart cleanly: no leftovers from the old moment
                key = next(k for k, v in self.live.items() if v is inst)
                inst.close()
                del self.live[key]
                inst = self._get(sh)
            n = int(min(t, self.WARMUP) / step)
            for k in range(n, 0, -1):
                tk, ak = t - k * step, at - k * step
                inst.feed(music_at(audio, ak - step, ak))
                inst.frame(tk, fbo)
            inst.feed(music_at(audio, at - step, at))
        else:
            inst.feed(music_at(audio, at - (t - inst.last_t), at))
        inst.frame(t, fbo)
        self._restore()

    def _restore(self) -> None:
        """Put back the GL state moderngl expects (projectM changes blending, the bound buffers and more)."""
        ctx = self.r.ctx
        mgl = self.r.mgl
        ctx.enable_only(mgl.NOTHING)
        ctx.blend_func = mgl.SRC_ALPHA, mgl.ONE_MINUS_SRC_ALPHA
        ctx.viewport = (0, 0, self.r.w, self.r.h)

    def release(self) -> None:
        for inst in self.live.values():
            inst.close()
        self.live.clear()
