"""Video export: Shadertoy-style visuals blended like the music, with the cover art,
artist and title of the current song in the lower-left corner. Output is an .mp4
(H.264 + AAC) encoded by ffmpeg; frames are rendered headless with OpenGL."""
from __future__ import annotations

import math
import random
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from . import audio_io, prefs
from .analysis import SongAnalysis
from .audio_io import SR
from .plan import MixPlan, timeline
from .transitions import KIND as _KIND, GL_ID, GLSL as _TRANS_GLSL, TransitionParams, ease as _ease, resolve as _resolve_transition
from .visuals import BUILTIN, Shader, ShaderError, ShaderLibrary, VERTEX, compile_program, make_context

MODES = ("auto", "random", "per_song", "single")
MODE_LABELS = {
    "auto": "Let the app choose",
    "random": "Random visual for each song",
    "per_song": "I choose per song",
    "single": "One visual for the whole video",
}


class Cancelled(RuntimeError):
    pass


# ----------------------------------------------------------------------- settings
@dataclass
class VideoSettings:
    mode: str = "auto"
    single_shader: str = "builtin:plasma"
    assignments: dict[str, str] = field(default_factory=dict)   # track uid -> shader id (per_song)
    clips: dict[str, str] = field(default_factory=dict)         # track uid -> the video clip last chosen for it (to switch back to)
    width: int = 1280
    height: int = 720
    fps: int = 30
    seed: int = field(default_factory=lambda: random.randrange(1, 1 << 30))   # reshuffles the random picks
    blend: float = 6.0               # visual cross-fade length (studio; mixes follow the audio blend)
    show_overlay: bool = True        # cover art + artist/title, lower left
    transition: dict = field(default_factory=lambda: TransitionParams().to_dict())    # default for every boundary
    transitions: dict[str, dict] = field(default_factory=dict)   # incoming track / marker uid -> its own settings
    use_video: bool = True           # video files in the mix / studio supply the picture instead of a visual
    crf: int = 18                    # x264 quality (lower = better)
    preset: str = "medium"           # x264 speed preset

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict | None) -> "VideoSettings":
        d = d or {}
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def load_from_session(session) -> VideoSettings:
    return VideoSettings.from_dict(session.extra.get("video"))


def attach_to_session(session, vs: VideoSettings, shaders: ShaderLibrary, plan: MixPlan | None = None) -> None:
    """Store the video settings plus the code of every user shader they use, so a
    shared session file brings its visuals along."""
    session.extra["video"] = vs.to_dict()
    used = {v for v in vs.assignments.values() if not str(v).startswith("@")} | {vs.single_shader}
    session.extra["shaders"] = shaders.export_used(used)


def restore_from_session(session, shaders: ShaderLibrary) -> VideoSettings:
    shaders.import_embedded(session.extra.get("shaders", {}))
    return load_from_session(session)


# ------------------------------------------------------------ choosing the visuals
def _song_energy(an: SongAnalysis, t) -> float:
    """0..1 'how intense is this song' from tempo and bar energy of the part that plays."""
    tempo = min(1.0, max(0.0, (an.bpm - 80.0) / 80.0))
    be = an.bar_energy
    if be:
        i0 = max(0, int((t.src_start - an.bar_energy_origin) / an.bar_length))
        i1 = max(i0 + 1, int((t.src_end - an.bar_energy_origin) / an.bar_length))
        seg = be[i0:i1] or be
        dens = float(np.mean(seg))
        top = max(be) or 1.0
        dens = min(1.0, dens / top)
    else:
        dens = 0.5
    return 0.45 * tempo + 0.55 * dens


_ENERGY_ORDER = {"calm": 0, "mid": 1, "high": 2}


def pick_visuals(keys: list[str], energies: list[float | None], vs: VideoSettings,
                 shaders: ShaderLibrary) -> list[str]:
    """One shader id per item (song / marker) according to vs.mode.

    'random' and 'auto' draw from the *whole* pool: a pick is not allowed to be any of the last few,
    and the more often a visual has already been used the less likely it is, so every visual gets a
    turn before any repeats. 'auto' additionally leans towards visuals whose energy suits the song
    (a gentle weight, not a filter, so it never collapses to two favourites)."""
    pool = [s for s in shaders.all() if not s.warnings or s.builtin] or list(BUILTIN.values())
    ids = [s.id for s in pool]
    n = len(keys)
    if not n:
        return []
    single = vs.single_shader if shaders.get(vs.single_shader) else ids[0]
    if vs.mode == "single":
        return [single] * n
    rng = random.Random(f"{vs.seed}:visuals")
    uses = {i: 0 for i in ids}
    recent: list[str] = []
    memory = min(max(1, len(ids) // 2), 5) if len(ids) > 1 else 0
    energy_of = {s.id: _ENERGY_ORDER.get(s.energy, 1) for s in pool}
    out: list[str] = []
    for key, e in zip(keys, energies):
        fixed = vs.assignments.get(key, "") if vs.mode == "per_song" else ""
        if fixed and (shaders.get(fixed) or str(fixed).startswith("@clip:")):
            pick = fixed
        else:
            ok = [i for i in ids if i not in recent[-memory:]] if memory else list(ids)
            weights = []
            for i in ok:
                w = 1.0 / (1.0 + uses[i]) ** 1.5
                if vs.mode != "random" and e is not None:
                    want = 0 if e < 0.42 else 1 if e < 0.62 else 2
                    w *= (3.0, 1.6, 0.6)[abs(energy_of[i] - want)]
                weights.append(w)
            pick = rng.choices(ok, weights=weights)[0]
        uses[pick] = uses.get(pick, 0) + 1
        recent.append(pick)
        out.append(pick)
    return out


def resolve_assignments(plan: MixPlan, lib: dict[str, SongAnalysis], vs: VideoSettings,
                        shaders: ShaderLibrary) -> list[str]:
    """One shader id per track, according to the chosen mode."""
    keys = [t.uid for t in plan.tracks]
    energies = [_song_energy(lib[t.song_id], t) for t in plan.tracks]
    return pick_visuals(keys, energies, vs, shaders)


# ------------------------------------------------------------------ cover-art card
_FONT_BOLD = ["segoeuib.ttf", "arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf",
              "NotoSans-Bold.ttf", "Helvetica.ttc"]
_FONT_REG = ["segoeui.ttf", "arial.ttf", "Arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf",
             "NotoSans-Regular.ttf", "Helvetica.ttc"]


def _font(names, size):
    from PIL import ImageFont

    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except Exception:  # noqa: BLE001
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # very old Pillow
        return ImageFont.load_default()


def _ellipsize(draw, text, font, max_w):
    if draw.textlength(text, font=font) <= max_w:
        return text
    while len(text) > 1 and draw.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


def _placeholder_cover(seed_text: str, size: int):
    from PIL import Image, ImageDraw

    rnd = random.Random(seed_text)
    c1 = tuple(rnd.randint(40, 200) for _ in range(3))
    c2 = tuple(rnd.randint(40, 200) for _ in range(3))
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            k = (x + y) / (2 * size)
            px[x, y] = tuple(int(a + (b - a) * k) for a, b in zip(c1, c2))
    d = ImageDraw.Draw(img)
    f = _font(_FONT_BOLD, int(size * 0.5))
    ch = (seed_text.strip()[:1] or "♪").upper()
    w = d.textlength(ch, font=f)
    d.text(((size - w) / 2, size * 0.16), ch, font=f, fill=(255, 255, 255))
    return img


def make_card(artist: str, title: str, cover_path: str | None, frame_h: int, max_w: int):
    """Rounded dark card: cover art on the left, artist and title on the right (RGBA)."""
    from PIL import Image, ImageDraw

    s = frame_h / 720.0
    pad, cover = int(14 * s), int(92 * s)
    f_title, f_artist = _font(_FONT_BOLD, int(27 * s)), _font(_FONT_REG, int(20 * s))
    probe = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    text_w_max = max(int(160 * s), max_w - cover - 3 * pad)
    title = _ellipsize(probe, title or "Unknown title", f_title, text_w_max)
    artist = _ellipsize(probe, artist, f_artist, text_w_max) if artist else ""
    tw = max(probe.textlength(title, font=f_title), probe.textlength(artist, font=f_artist) if artist else 0)
    w, h = int(cover + 3 * pad + tw), cover + 2 * pad
    card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=int(14 * s), fill=(8, 8, 14, 175))
    art = None
    if cover_path:
        try:
            art = Image.open(cover_path).convert("RGB")
            m = min(art.size)
            art = art.crop(((art.width - m) // 2, (art.height - m) // 2, (art.width + m) // 2, (art.height + m) // 2))
        except Exception:  # noqa: BLE001
            art = None
    if art is None:
        art = _placeholder_cover(title or artist, 256)
    art = art.resize((cover, cover), Image.LANCZOS)
    mask = Image.new("L", (cover, cover), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, cover - 1, cover - 1), radius=int(8 * s), fill=255)
    card.paste(art, (pad, pad), mask)
    tx = pad + cover + pad
    if artist:
        d.text((tx, pad + int(10 * s)), title, font=f_title, fill=(255, 255, 255, 255))
        d.text((tx, pad + int(10 * s) + int(38 * s)), artist, font=f_artist, fill=(215, 215, 225, 255))
    else:
        d.text((tx, pad + cover / 2 - int(17 * s)), title, font=f_title, fill=(255, 255, 255, 255))
    return card


# -------------------------------------------------------------------- audio -> texture
class AudioTexture:
    """Shadertoy's music input: a 512x2 texture, row 0 = spectrum, row 1 = waveform."""

    def __init__(self, mix: np.ndarray | None, sr: int = SR):
        self.sr = sr
        self.N = 1024 if sr <= 24000 else 2048        # 512 bins spanning 0 .. ~11 kHz either way
        self.mono = None if mix is None else np.ascontiguousarray(mix.mean(axis=0), dtype=np.float32)
        self.win = np.hanning(self.N).astype(np.float32)
        self.prev = np.zeros(512, dtype=np.float32)

    def at(self, t: float) -> np.ndarray:
        out = np.zeros((2, 512), dtype=np.float32)
        if self.mono is None:  # silent / preview: a gentle moving fake so reactive shaders aren't dead
            x = np.linspace(0, 1, 512)
            out[0] = np.clip((0.55 + 0.35 * np.sin(t * 3.1 + x * 9)) * np.exp(-x * 6), 0, 1)
            out[1] = 0.5 + 0.3 * np.sin(x * 40 + t * 12) * 0.5
            return out
        end = int(t * self.sr)
        seg = self.mono[max(0, end - self.N):end]
        if len(seg) < self.N:
            seg = np.pad(seg, (self.N - len(seg), 0))
        spec = np.abs(np.fft.rfft(seg * self.win))[:512] / self.N
        db = 20.0 * np.log10(spec + 1e-9)
        cur = np.clip((db + 100.0) / 70.0, 0.0, 1.0).astype(np.float32)   # WebAudio-style -100..-30 dB
        self.prev = 0.7 * self.prev + 0.3 * cur
        out[0] = self.prev
        out[1] = np.clip(seg[-512:] * 0.5 + 0.5, 0.0, 1.0)
        return out


def _level(mono: np.ndarray, sr: int, N: int, win: np.ndarray, t: float) -> float:
    """Bass level 0..1 of the N samples ending at t (stateless, so scrubbing works)."""
    end = int(t * sr)
    if end <= 0:
        return 0.0
    seg = mono[max(0, end - N):end]
    if len(seg) < N:
        seg = np.pad(seg, (N - len(seg), 0))
    spec = np.abs(np.fft.rfft(seg * win)) / N
    top = max(3, int(160.0 / (sr / N)))               # up to ~160 Hz
    db = 20.0 * np.log10(float(np.sqrt(np.mean(spec[1:top] ** 2))) + 1e-9)
    return float(np.clip((db + 78.0) / 36.0, 0.0, 1.0))


def audio_features(a: "AudioTexture", t: float) -> tuple[float, float]:
    """(bass, pulse) for the rhythm transitions: how loud the low end is, and how sharply it just rose (a kick)."""
    if a.mono is None:                                # no audio yet: a gentle 2 Hz fake so the effects can be seen
        ph = (t * 2.0) % 1.0
        return 0.5 + 0.3 * math.sin(t * 6.0), max(0.0, 1.0 - ph * 4.0)
    now = _level(a.mono, a.sr, a.N, a.win, t)
    before = 0.5 * (_level(a.mono, a.sr, a.N, a.win, t - 0.11) + _level(a.mono, a.sr, a.N, a.win, t - 0.24))
    return now, float(np.clip((now - before) * 4.0, 0.0, 1.0))


# ------------------------------------------------------------------------ video files as pictures
KIND_RHYTHM = {k for k, v in _KIND.items() if v == "rhythm"}


class VideoSource:
    """Plays a video file as frames of a given size (cover-fit, so it fills the picture), sequentially through
    one ffmpeg process. Asking for an earlier time, or a much later one, restarts it there."""

    FPS = 30

    def __init__(self, path, w: int, h: int, loop: bool = False):
        self.path, self.w, self.h, self.loop = str(path), int(w), int(h), loop
        self.proc = None
        self.t_cur = -1.0          # source time of self.frame
        self.frame: bytes | None = None
        self.eof = False
        self._dur: float | None = None

    @property
    def duration(self) -> float:
        if self._dur is None:
            from .studio import probe_duration
            self._dur = probe_duration(self.path) or 1e9
        return self._dur

    def _start(self, at: float):
        self.close()
        cmd = [audio_io.ffmpeg(), "-v", "error", "-nostdin", "-ss", f"{max(0.0, at):.3f}", "-i", self.path, "-an",
               "-vf", f"fps={self.FPS},scale={self.w}:{self.h}:force_original_aspect_ratio=increase,"
                      f"crop={self.w}:{self.h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=self.w * self.h * 12)
        self.t_cur, self.eof = at - 1.0 / self.FPS, False
        self._advance(1)

    def _advance(self, n: int) -> None:
        size = self.w * self.h * 3
        for _ in range(max(0, n)):
            buf = self.proc.stdout.read(size) if self.proc else b""
            if len(buf) < size:
                self.eof = True
                return
            self.frame = buf
            self.t_cur += 1.0 / self.FPS

    def frame_at(self, s: float) -> bytes | None:
        """RGB bytes, top row first, of the picture at source time s."""
        if self.loop and self.duration < 1e8:
            s = s % self.duration
        s = max(0.0, s)
        back = self.proc is None or s < self.t_cur - 0.5 / self.FPS
        far = self.proc is not None and s > self.t_cur + 2.0
        wrapped = self.proc is not None and self.eof and self.loop and s < self.t_cur - 0.5
        if back or far or wrapped:
            self._start(s)
        elif not self.eof:
            self._advance(int(round((s - self.t_cur) * self.FPS)))
        return self.frame

    def close(self):
        if self.proc is not None:
            try:
                self.proc.kill()
                self.proc.stdout.close()
            except Exception:  # noqa: BLE001
                pass
            self.proc = None


# ------------------------------------------------------------------------ GL drawing
_COMPOSITE_FS = """#version 330 core
uniform sampler2D cardA; uniform sampler2D cardB;
uniform float alphaA; uniform float alphaB; uniform float fade;
uniform vec4 rectA; uniform vec4 rectB;
out vec4 o;
""" + _TRANS_GLSL + """
vec3 overlayCard(vec3 col, sampler2D tex, vec4 rect, float a, vec2 uv){
    if (a <= 0.0) return col;
    vec2 q = (uv - rect.xy) / (rect.zw - rect.xy);
    if (q.x < 0.0 || q.y < 0.0 || q.x > 1.0 || q.y > 1.0) return col;
    vec4 c = textureLod(tex, q, 0.0);
    return mix(col, c.rgb, c.a * a);
}
void main(){
    vec2 uv = gl_FragCoord.xy / res;
    vec3 col = (tP >= 0.9999) ? B(uv) : transitionColor(uv);
    col = overlayCard(col, cardA, rectA, alphaA, uv);
    col = overlayCard(col, cardB, rectB, alphaB, uv);
    o = vec4(clamp(col, 0.0, 1.0) * fade, 1.0);
}
"""


def _set(prog, name, value):
    if name in prog:
        try:
            prog[name].value = value
        except Exception:  # noqa: BLE001
            pass


def _decode_clip(path, seconds: float = 12.0, fps: int = 12, size=(320, 180)):
    """Decode (the first seconds of) a video clip into small RGB frames, bottom row first, to loop as a texture."""
    import subprocess

    import imageio_ffmpeg

    w, h = size
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", str(path), "-t", str(seconds), "-an",
           "-vf", f"fps={fps},scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    raw = subprocess.run(cmd, capture_output=True, timeout=120).stdout
    n = len(raw) // (w * h * 3)
    if n < 1:
        raise ValueError("no video frames could be read")
    arr = np.frombuffer(raw[: n * w * h * 3], dtype=np.uint8).reshape(n, h, w, 3)
    return [np.ascontiguousarray(a[::-1]) for a in arr], fps, (w, h)


class _ShaderInstance:
    """One shader ready to draw: every pass compiled, buffer textures allocated.
    Buffers keep their contents between frames (feedback effects) and are cleared
    whenever the shader's clock jumps back, i.e. when its song starts again."""

    def __init__(self, r: "GLRenderer", shader: Shader):
        self.r, self.shader = r, shader
        raw = shader.passes or [{"name": "Image", "type": "image", "code": shader.source, "inputs": None}]
        common = next((p["code"] for p in raw if p.get("type") == "common"), "")
        self.passes = []
        for p in raw:
            if p.get("type") == "common":
                continue
            prog = compile_program(r.ctx, p["code"], buffer=p["type"] == "buffer", common=common)
            vao = r.ctx.vertex_array(prog, [(r.vbo, "2f", "p")])
            for i in range(4):
                _set(prog, f"iChannel{i}", i)
            _set(prog, "iResolution", (float(r.w), float(r.h), 1.0))
            _set(prog, "iSampleRate", float(SR))
            self.passes.append({"name": p.get("name", "Image"), "type": p["type"], "prog": prog, "vao": vao,
                                "inputs": p.get("inputs")})
        self.buf: dict[str, dict] = {}
        for p in self.passes:
            if p["type"] == "buffer":
                letter = p["name"][-1].upper()
                texs = []
                for _ in range(2):
                    tex = r.ctx.texture((r.w, r.h), 4, dtype="f4")
                    tex.filter = (r.mgl.LINEAR, r.mgl.LINEAR)
                    tex.repeat_x = tex.repeat_y = False
                    texs.append((tex, r.ctx.framebuffer(color_attachments=[tex])))
                self.buf[letter] = {"t": texs, "cur": 0}
        self.frame = 0
        self.last_t = -1.0

    def reset(self):
        self.frame = 0
        for b in self.buf.values():
            for tex, fbo in b["t"]:
                fbo.use()
                fbo.clear(0.0, 0.0, 0.0, 0.0)
            b["cur"] = 0

    def _bind(self, p, t=0.0):
        r = self.r
        inputs = p["inputs"]
        sizes = []
        for ch in range(4):
            kind = None if inputs is None else inputs.get(str(ch))
            if inputs is None:
                kind = "audio" if ch == 0 else "noise"
            tex = None
            if kind and kind.startswith("buffer:"):
                b = self.buf.get(kind.split(":")[1])
                tex = b["t"][b["cur"]][0] if b else None
            elif kind == "audio":
                tex = r.audio_tex
            elif kind == "keyboard":
                tex = r.key_tex
            elif kind and kind.startswith(("texture:", "video:")):
                tex = r.media(kind, t)
            if tex is None:
                tex = r.noise_tex if kind else r.blank
            tex.use(ch)
            sizes.append((float(tex.size[0]), float(tex.size[1]), 1.0))
        return sizes

    def _uniforms(self, p, t):
        prog = p["prog"]
        _set(prog, "iTime", float(t))
        _set(prog, "iTimeDelta", 1.0 / max(1, self.r.fps))
        _set(prog, "iFrame", int(self.frame))
        _set(prog, "iMouse", (0.0, 0.0, 0.0, 0.0))
        _set(prog, "iDate", (2026.0, 1.0, 1.0, float(t)))
        _set(prog, "iChannelTime", [float(t)] * 4)
        sizes = self._bind(p, t)
        if "iChannelResolution" in prog:
            try:
                prog["iChannelResolution"].value = sizes
            except Exception:  # noqa: BLE001
                pass

    def draw(self, t: float, slot: int):
        r = self.r
        if t < self.last_t - 1e-6:
            self.reset()
        self.last_t = t
        for p in self.passes:
            if p["type"] != "buffer":
                continue
            b = self.buf[p["name"][-1].upper()]
            w_idx = 1 - b["cur"]
            fbo = b["t"][w_idx][1]
            fbo.use()
            r.ctx.viewport = (0, 0, r.w, r.h)
            self._uniforms(p, t)
            p["vao"].render(r.mgl.TRIANGLE_STRIP)
            b["cur"] = w_idx
        img = next(p for p in reversed(self.passes) if p["type"] == "image")
        tex, fbo = r.scene[slot]
        fbo.use()
        r.ctx.viewport = (0, 0, r.w, r.h)
        self._uniforms(img, t)
        img["vao"].render(r.mgl.TRIANGLE_STRIP)
        self.frame += 1


class GLRenderer:
    def __init__(self, width: int, height: int, audio: AudioTexture | None = None, fps: int = 30):
        import moderngl

        self.fps = fps
        self.mgl = moderngl
        self.w, self.h = int(width), int(height)
        self.ctx = make_context()
        self.audio = audio or AudioTexture(None)
        self.vbo = self.ctx.buffer(np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype="f4").tobytes())
        self.scene = []
        for _ in range(2):
            tex = self.ctx.texture((self.w, self.h), 4)
            tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            self.scene.append((tex, self.ctx.framebuffer(color_attachments=[tex])))
        self.out = self.ctx.simple_framebuffer((self.w, self.h), components=3)
        self.audio_tex = self.ctx.texture((512, 2), 1, dtype="f4")
        self.audio_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.audio_tex.repeat_x = self.audio_tex.repeat_y = False
        rng = np.random.default_rng(1234)
        noise = rng.integers(0, 256, (256, 256, 4), dtype=np.uint8)
        self.noise_tex = self.ctx.texture((256, 256), 4, noise.tobytes())
        self.noise_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.noise_tex.repeat_x = self.noise_tex.repeat_y = True
        self.comp = self.ctx.program(vertex_shader=VERTEX, fragment_shader=_COMPOSITE_FS)
        self.comp_vao = self.ctx.vertex_array(self.comp, [(self.vbo, "2f", "p")])
        self.blank = self.ctx.texture((1, 1), 4, bytes(4))
        self.key_tex = self.ctx.texture((256, 3), 1, bytes(256 * 3))
        self.programs: dict[str, tuple] = {}
        self._media: dict = {}
        self.videos: dict[tuple, VideoSource] = {}
        self.cards: dict[str, tuple] = {}
        self.last_t = -1.0
        self.warnings: list[str] = []

    # -- shaders
    def instance(self, shader: Shader):
        key = f"{shader.id}:{hash((shader.source, repr(shader.passes)))}"
        got = self.programs.get(key)
        if got is None:
            try:
                got = _ShaderInstance(self, shader)
            except ShaderError as e:
                msg = str(e).strip().splitlines()
                self.warnings.append(f"'{shader.name}' failed to compile and was replaced: {msg[-1] if msg else ''}")
                got = _ShaderInstance(self, BUILTIN["builtin:plasma"])
            self.programs[key] = got
        return got

    def draw_shader(self, shader: Shader, t: float, frame: int, slot: int, audio_t: float | None = None):
        inst = self.instance(shader)
        inst.draw(max(t, 0.0), slot)

    def update_audio(self, t: float):
        if t != self.last_t:
            self.audio_tex.write(self.audio.at(t).tobytes())
            self.last_t = t

    def draw_video(self, path: str, src_time: float, slot: int, loop: bool = False) -> bool:
        """Put the video frame at `src_time` into scene `slot` (False if the file can't be read)."""
        key = (path, loop)
        vs = self.videos.get(key)
        if vs is None:
            vs = self.videos[key] = VideoSource(path, self.w, self.h, loop)
        fr = vs.frame_at(src_time)
        if fr is None:
            self.warnings.append(f"Couldn't read the video {Path(path).name}; a visual is shown instead.") \
                if f"v:{path}" not in self.warnings else None
            return False
        rgb = np.frombuffer(fr, np.uint8).reshape(self.h, self.w, 3)[::-1]
        rgba = np.empty((self.h, self.w, 4), np.uint8)
        rgba[..., :3] = rgb
        rgba[..., 3] = 255
        self.scene[slot][0].write(rgba.tobytes())
        return True

    # -- textures and video clips a shader uses
    def media(self, kind: str, t: float):
        """GL texture for a "texture:<file>" / "video:<file>" input (None if the file is missing)."""
        got = self._media.get(kind)
        if got is None:
            got = self._load_media(kind)
            self._media[kind] = got
        if got is False:
            return None
        if got["frames"] is not None:
            frames = got["frames"]
            i = int(max(t, 0.0) * got["fps"]) % len(frames)
            if i != got["cur"]:
                got["tex"].write(frames[i].tobytes())
                got["cur"] = i
        return got["tex"]

    def _load_media(self, kind: str):
        from .visuals import kind_media, media_path
        kind_, name = kind_media(kind)
        path = media_path(name)
        if path is None:
            self.warnings.append(f"A {kind_} the shader uses is missing: {name}")
            return False
        try:
            if kind_ == "texture":
                from PIL import Image
                img = Image.open(path).convert("RGBA")
                img.thumbnail((1024, 1024))
                img = img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
                tex = self.ctx.texture(img.size, 4, img.tobytes())
                tex.build_mipmaps()
                tex.filter = (self.mgl.LINEAR_MIPMAP_LINEAR, self.mgl.LINEAR)
                tex.repeat_x = tex.repeat_y = True
                return {"tex": tex, "frames": None, "fps": 0, "cur": -1}
            frames, fps, (w, h) = _decode_clip(path)
            tex = self.ctx.texture((w, h), 3, frames[0].tobytes())
            tex.filter = (self.mgl.LINEAR, self.mgl.LINEAR)
            tex.repeat_x = tex.repeat_y = True
            return {"tex": tex, "frames": frames, "fps": fps, "cur": 0}
        except Exception as e:  # noqa: BLE001
            self.warnings.append(f"Couldn't load {name}: {e}")
            return False

    # -- cards
    def card(self, key: str, make) -> tuple:
        got = self.cards.get(key)
        if got is None:
            from PIL import Image
            img = make().transpose(Image.Transpose.FLIP_TOP_BOTTOM)  # GL textures start at the bottom row
            tex = self.ctx.texture(img.size, 4, img.tobytes())
            tex.filter = (self.mgl.LINEAR, self.mgl.LINEAR)
            m = int(36 * self.h / 720)
            rect = (m / self.w, m / self.h, (m + img.width) / self.w, (m + img.height) / self.h)
            got = (tex, rect)
            if len(self.cards) > 6:  # keep a few, drop the oldest
                old = next(iter(self.cards))
                self.cards.pop(old)[0].release()
            self.cards[key] = got
        return got

    def composite(self, mix_ab: float, card_a=None, alpha_a: float = 0.0, card_b=None, alpha_b: float = 0.0,
                  fade: float = 1.0, trans: dict | None = None) -> bytes:
        self.out.use()
        self.ctx.viewport = (0, 0, self.w, self.h)
        self.scene[0][0].use(0)
        self.scene[1][0].use(1)
        ta, ra = card_a if card_a else (self.blank, (0, 0, 1, 1))
        tb, rb = card_b if card_b else (self.blank, (0, 0, 1, 1))
        ta.use(2)
        tb.use(3)
        for i, n in enumerate(("texIn", "texOut", "cardA", "cardB")):
            _set(self.comp, n, i)
        tr = {"type": 0, "p": 1.0 - float(mix_ab), "angle": 0.0, "soft": 0.3, "inten": 1.0, "sens": 1.0,
              "bass": 0.0, "pulse": 0.0, "time": 0.0, "bpm": 0.0}
        tr.update(trans or {})
        _set(self.comp, "tType", int(tr["type"]))
        _set(self.comp, "tP", float(tr["p"]))
        _set(self.comp, "tAngle", float(tr["angle"]))
        _set(self.comp, "tSoft", float(tr["soft"]))
        _set(self.comp, "tInt", float(tr["inten"]))
        _set(self.comp, "tSens", float(tr["sens"]))
        _set(self.comp, "tBass", float(tr["bass"]))
        _set(self.comp, "tPulse", float(tr["pulse"]))
        _set(self.comp, "tTime", float(tr["time"]))
        _set(self.comp, "tBpm", float(tr["bpm"]))
        _set(self.comp, "alphaA", float(alpha_a if card_a else 0.0))
        _set(self.comp, "alphaB", float(alpha_b if card_b else 0.0))
        _set(self.comp, "fade", float(fade))
        _set(self.comp, "rectA", tuple(float(x) for x in ra))
        _set(self.comp, "rectB", tuple(float(x) for x in rb))
        _set(self.comp, "res", (float(self.w), float(self.h)))
        self.comp_vao.render(self.mgl.TRIANGLE_STRIP)
        return self.out.read(components=3)

    def release(self):
        for v in self.videos.values():
            v.close()
        try:
            self.ctx.release()
        except Exception:  # noqa: BLE001
            pass


def preview_frame(shader: Shader, t: float = 4.0, size=(256, 144), renderer: GLRenderer | None = None) -> np.ndarray:
    """A single RGB frame (h, w, 3) of one shader, for the visuals picker."""
    own = renderer is None
    r = renderer or GLRenderer(*size)
    try:
        if shader.passes:     # feedback buffers need a run-up of frames
            n = min(60, max(1, int(t * 15)))
            for k in range(n):
                tk = t * k / max(1, n - 1)
                r.update_audio(tk)
                r.draw_shader(shader, tk, k, 0)
        else:
            r.update_audio(t)
            r.draw_shader(shader, t, int(t * 30), 0)
        raw = r.composite(0.0)
        return np.flipud(np.frombuffer(raw, np.uint8).reshape(r.h, r.w, 3)).copy()
    finally:
        if own:
            r.release()


# ------------------------------------------------------------------- the schedule
def _smooth(u: float) -> float:
    u = min(1.0, max(0.0, u))
    return u * u * (3 - 2 * u)


def frame_schedule(plan: MixPlan, total_seconds: float, sr: int = SR):
    """Per-boundary visual fade windows: [(fade_start, fade_end), ...] for tracks 1..n-1,
    aligned with the audio transitions (a short fade for hard cuts)."""
    slots = timeline(plan, sr)
    starts = [s.start / sr for s in slots]
    wins = []
    for s in slots[1:]:
        ov = s.overlap_in / sr
        t0 = s.start / sr
        wins.append((t0, t0 + ov) if ov >= 1.0 else (t0 - 0.4, t0 + 0.4))
    return starts, wins


def _state_at(t: float, starts, wins, raw: bool = False):
    """-> (outgoing_track, incoming_track, u) with u in 0..1; no blend when outgoing is None."""
    idx = 0
    for i, (fs, fe) in enumerate(wins, start=1):
        if t >= fs:
            idx = i
        else:
            break
    if idx >= 1:
        fs, fe = wins[idx - 1]
        if t < fe:
            lin = (t - fs) / max(1e-6, fe - fs)
            return idx - 1, idx, (lin if raw else _smooth(lin))
    return None, idx, 1.0


# ------------------------------------------------------------------------ the render
@dataclass
class Segment:
    """One stretch of the video: a song (or a marker in the studio) with its visual and card."""
    uid: str
    start: float                 # seconds on the timeline
    shader: str = "builtin:plasma"
    artist: str = ""
    title: str = ""
    cover: str | None = None
    video: str | None = None     # a video file supplies the picture instead of the visual
    vstart: float = 0.0          # video time at `start` (when vcurve is not given)
    vcurve: object = None        # tempo curve of the song (mixes): video time = vcurve.src_time(t - start)
    vspeed: float = 1.0          # playback speed of the video (studio clips)
    vloop: bool = False          # loop a clip that is shorter than its segment
    trans: dict | None = None    # this segment's own transition settings (into it); None = the default

    def key(self) -> str:
        return f"v:{self.uid}" if self.video else self.shader

    def video_time(self, t: float) -> float:
        if self.vcurve is not None:
            return float(self.vcurve.src_time(max(0.0, t - self.start)))
        return self.vstart + (t - self.start) * self.vspeed


def _encode_cmd(w, h, fps, audio_path, out_path, vs):
    return [audio_io.ffmpeg(), "-v", "error", "-nostdin", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
            "-i", str(audio_path), "-map", "0:v", "-map", "1:a", "-vf", "vflip",
            "-c:v", "libx264", "-preset", vs.preset, "-crf", str(vs.crf), "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "320k", "-shortest", "-movflags", "+faststart", str(out_path)]


class FrameComposer:
    """Draws the picture for any moment of a video made of segments (shared by the exporter and the
    live previews): the visual or video of each segment, the transitions between them and the card."""

    def __init__(self, segments: list[Segment], wins: list, seconds: float, vs: VideoSettings,
                 shaders: ShaderLibrary, bpm: float = 0.0):
        self.segments, self.seconds, self.vs, self.bpm = segments, seconds, vs, float(bpm or 0.0)
        self.starts = [sg.start for sg in segments]
        self.shader_of = [shaders.get(sg.shader) or BUILTIN["builtin:plasma"] for sg in segments]
        self.single = vs.mode == "single"
        self.overlay = bool(vs.show_overlay) and prefs.overlay_enabled()     # per-video AND the app-wide switch
        default = TransitionParams.from_dict(vs.transition)
        self.tp: list[TransitionParams | None] = [None]
        self.wins = []
        for i, (fs, fe) in enumerate(wins, start=1):
            own = segments[i].trans if i < len(segments) else None
            p = _resolve_transition(TransitionParams.from_dict(own) if own else default, vs.seed, i)
            self.tp.append(p)
            if p.duration > 0:                       # the user's own length, centred on the automatic window
                mid = 0.5 * (fs + fe)
                fs, fe = mid - p.duration / 2, mid + p.duration / 2
            self.wins.append((fs, fe))

    def _scene(self, r: "GLRenderer", i: int, t: float, k: int, slot: int):
        sg = self.segments[i]
        if sg.video and r.draw_video(sg.video, sg.video_time(t), slot, sg.vloop):
            return
        r.draw_shader(self.shader_of[i], t if self.single else t - self.starts[i], k, slot)

    def draw(self, r: "GLRenderer", t: float, k: int) -> bytes:
        vs, segs = self.vs, self.segments
        h = r.h
        r.update_audio(t)
        out_i, in_i, u = _state_at(t, self.starts, self.wins, raw=True)
        us = _smooth(u)
        self._scene(r, in_i, t, k, 0)
        trans = None
        mixab = 0.0
        if out_i is not None and segs[out_i].key() != segs[in_i].key():
            self._scene(r, out_i, t, k, 1)
            p = self.tp[in_i]
            bass = pulse = 0.0
            if p.type in KIND_RHYTHM:
                bass, pulse = audio_features(r.audio, t)
            trans = {"type": GL_ID[p.type], "p": _ease(u, p.ease), "angle": math.radians(p.angle), "soft": p.softness,
                     "inten": p.intensity, "sens": p.sensitivity, "bass": bass, "pulse": pulse, "time": t, "bpm": self.bpm}
        fade = min(1.0, t / 1.0) * min(1.0, max(0.0, (self.seconds - t) / 1.5))
        ca = cb = None
        aa = ab = 0.0
        if self.overlay:
            def card_for(i):
                sg = segs[i]
                return r.card(f"{sg.uid}|{sg.artist}|{sg.title}|{sg.cover}", lambda: make_card(sg.artist, sg.title, sg.cover, h, int(r.w * 0.55)))

            ca = card_for(in_i)
            aa = min(1.0, t / 1.5)
            if out_i is not None:
                # one after the other, so the two cards never overprint: old fades out, then new fades in
                aa = _smooth(2.0 * us - 1.0)
                cb = card_for(out_i)
                ab = _smooth(1.0 - 2.0 * us)
        return r.composite(mixab, ca, aa, cb, ab, fade, trans)


def render_segments(segments: list[Segment], wins: list, seconds: float, out_path, vs: VideoSettings,
                    shaders: ShaderLibrary, audio_path, texture_audio: np.ndarray | None = None,
                    texture_sr: int = SR, progress=None, cancel=None, bpm: float = 0.0) -> dict:
    """The shared video renderer used by mixes and by the visualization studio.

    wins[i-1] = (fade_start, fade_end) of the visual cross-fade into segments[i].
    audio_path is muxed as the soundtrack; texture_audio only feeds music-reactive shaders."""
    out_path = Path(out_path)
    w, h = (int(vs.width) // 2 * 2), (int(vs.height) // 2 * 2)
    say = progress or (lambda msg, frac: None)
    if not segments:
        raise audio_io.AudioError("There is nothing to put in the video.")

    def check():
        if cancel and cancel():
            raise Cancelled("Cancelled")

    n_frames = int(math.ceil(seconds * vs.fps))
    comp = FrameComposer(segments, wins, seconds, vs, shaders, bpm)
    r = GLRenderer(w, h, AudioTexture(texture_audio, texture_sr), fps=vs.fps)
    proc = None
    try:
        proc = subprocess.Popen(_encode_cmd(w, h, vs.fps, audio_path, out_path, vs),
                                stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        for k in range(n_frames):
            if k % 8 == 0:
                check()
                say(f"rendering video {k}/{n_frames}", k / max(1, n_frames))
            proc.stdin.write(comp.draw(r, k / vs.fps, k))
        proc.stdin.close()
        err = proc.stderr.read().decode(errors="replace")
        if proc.wait() != 0:
            raise audio_io.AudioError("ffmpeg could not encode the video: " + err[:500])
    except BrokenPipeError:
        err = proc.stderr.read().decode(errors="replace")
        raise audio_io.AudioError("ffmpeg stopped unexpectedly: " + err[:500]) from None
    except BaseException:
        if proc is not None:
            proc.kill()
        if out_path.exists():
            try:
                out_path.unlink()
            except OSError:
                pass
        raise
    finally:
        warnings = list(r.warnings)
        r.release()
    say("done", 1.0)
    return {"video": str(out_path), "seconds": seconds, "frames": n_frames, "warnings": warnings,
            "visuals": [(Path(sg.video).name if sg.video else s.name) for s, sg in zip(comp.shader_of, segments)]}


def render_video(plan: MixPlan, lib: dict[str, SongAnalysis], paths: dict[str, str], out_path,
                 vs: VideoSettings | None = None, shaders: ShaderLibrary | None = None,
                 audio: np.ndarray | None = None, progress=None, cancel=None, extra: dict | None = None) -> dict:
    """Render the whole mix to an mp4 (`extra` = the session's extra, which holds the covers you chose). `audio` is the already rendered mix (else it is rendered here)."""
    from .render import render_mix

    vs = vs or VideoSettings()
    shaders = shaders or ShaderLibrary()
    say = progress or (lambda msg, frac: None)
    if audio is None:
        audio = render_mix(plan, lib, paths, progress=lambda m, f: say(m, 0.3 * f))
    if cancel and cancel():
        raise Cancelled("Cancelled")
    seconds = audio.shape[1] / SR
    with tempfile.TemporaryDirectory(prefix="lmm_video_") as tmp:
        tmp = Path(tmp)
        wav = tmp / "mix.wav"
        audio_io.write_audio(wav, audio)
        from . import songinfo
        covers = songinfo.overrides(extra, tmp) if extra else None
        segs, wins = build_mix_segments(plan, lib, paths, vs, shaders, tmp, seconds, covers)
        return render_segments(segs, wins, seconds, out_path, vs, shaders, wav, audio, SR,
                               progress=lambda m, f: say(m, 0.3 + 0.7 * f), cancel=cancel, bpm=plan.master_bpm)


def build_mix_segments(plan: MixPlan, lib: dict, paths: dict, vs: VideoSettings, shaders: ShaderLibrary,
                       tmp_dir, seconds: float, covers: dict | None = None):
    """-> (segments, fade windows) for a mix: each song's visual (or its own video, when the file is one)."""
    starts, wins = frame_schedule(plan, seconds)
    slots = timeline(plan)
    chosen = resolve_assignments(plan, lib, vs, shaders)
    covers = covers if covers is not None else {}
    segs = []
    for t, sid, st, slot in zip(plan.tracks, chosen, starts, slots):
        path = paths.get(t.song_id)
        if t.song_id not in covers:
            cover = None
            if path:
                p = Path(tmp_dir) / f"cover_{len(covers)}.jpg"
                try:
                    cover = str(p) if audio_io.extract_cover(path, p) else None
                except Exception:  # noqa: BLE001
                    cover = None
            covers[t.song_id] = cover
        an = lib[t.song_id]
        seg = Segment(t.uid, st, sid, an.artist, an.title, covers[t.song_id], trans=vs.transitions.get(t.uid))
        if isinstance(sid, str) and sid.startswith("@clip:"):
            seg.video, seg.vloop = sid[6:], True
        elif vs.use_video and path and audio_io.is_video_file(path) and not (
                vs.mode == "per_song" and vs.assignments.get(t.uid)):
            seg.video, seg.vcurve = path, slot.curve          # the song's own video follows its tempo changes
        segs.append(seg)
    return segs, wins
