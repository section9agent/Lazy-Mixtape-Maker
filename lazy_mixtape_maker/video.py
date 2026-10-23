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

from . import audio_io
from .analysis import SongAnalysis
from .audio_io import SR
from .plan import MixPlan, timeline
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
    width: int = 1280
    height: int = 720
    fps: int = 30
    seed: int = 0
    show_overlay: bool = True        # cover art + artist/title, lower left
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
    used = set(vs.assignments.values()) | {vs.single_shader}
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


def resolve_assignments(plan: MixPlan, lib: dict[str, SongAnalysis], vs: VideoSettings,
                        shaders: ShaderLibrary) -> list[str]:
    """One shader id per track, according to the chosen mode."""
    pool = [s for s in shaders.all() if not s.warnings or s.builtin] or list(BUILTIN.values())
    ids = [s.id for s in pool]
    n = len(plan.tracks)
    if not n:
        return []
    single = vs.single_shader if shaders.get(vs.single_shader) else ids[0]
    if vs.mode == "single":
        return [single] * n
    out: list[str] = []
    rng = random.Random(f"{vs.seed}:visuals")
    for i, t in enumerate(plan.tracks):
        prev = out[-1] if out else None
        if vs.mode == "per_song" and shaders.get(vs.assignments.get(t.uid, "")):
            pick = vs.assignments[t.uid]
        elif vs.mode == "random":
            options = [x for x in ids if x != prev] or ids
            pick = rng.choice(options)
        else:  # auto (and per_song tracks nobody has set yet)
            an = lib[t.song_id]
            e = _song_energy(an, t)
            want = "calm" if e < 0.42 else "mid" if e < 0.62 else "high"
            cands = [s.id for s in pool if s.energy == want] or ids
            cands = [x for x in cands if x != prev] or cands
            r = random.Random(f"{vs.seed}:{an.id}")
            pick = r.choice(sorted(cands))
        out.append(pick)
    return out


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

    N = 2048

    def __init__(self, mix: np.ndarray | None, sr: int = SR):
        self.sr = sr
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


# ------------------------------------------------------------------------ GL drawing
_COMPOSITE_FS = """#version 330 core
uniform sampler2D sceneA; uniform sampler2D sceneB; uniform sampler2D cardA; uniform sampler2D cardB;
uniform float mixAB; uniform float alphaA; uniform float alphaB; uniform float fade;
uniform vec4 rectA; uniform vec4 rectB; uniform vec2 res;
out vec4 o;
vec3 overlayCard(vec3 col, sampler2D tex, vec4 rect, float a, vec2 uv){
    if (a <= 0.0) return col;
    vec2 q = (uv - rect.xy) / (rect.zw - rect.xy);
    if (q.x < 0.0 || q.y < 0.0 || q.x > 1.0 || q.y > 1.0) return col;
    vec4 c = textureLod(tex, q, 0.0);
    return mix(col, c.rgb, c.a * a);
}
void main(){
    vec2 uv = gl_FragCoord.xy / res;
    vec3 col = mix(textureLod(sceneA, uv, 0.0).rgb, textureLod(sceneB, uv, 0.0).rgb, mixAB);
    col = overlayCard(col, cardA, rectA, alphaA, uv);
    col = overlayCard(col, cardB, rectB, alphaB, uv);
    o = vec4(col * fade, 1.0);
}
"""


def _set(prog, name, value):
    if name in prog:
        try:
            prog[name].value = value
        except Exception:  # noqa: BLE001
            pass


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

    def _bind(self, p):
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
        sizes = self._bind(p)
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
        self.cards: dict[str, tuple] = {}
        self.last_t = -1.0
        self.warnings: list[str] = []

    # -- shaders
    def instance(self, shader: Shader):
        got = self.programs.get(shader.id)
        if got is None:
            try:
                got = _ShaderInstance(self, shader)
            except ShaderError as e:
                msg = str(e).strip().splitlines()
                self.warnings.append(f"'{shader.name}' failed to compile and was replaced: {msg[-1] if msg else ''}")
                got = _ShaderInstance(self, BUILTIN["builtin:plasma"])
            self.programs[shader.id] = got
        return got

    def draw_shader(self, shader: Shader, t: float, frame: int, slot: int, audio_t: float | None = None):
        inst = self.instance(shader)
        inst.draw(max(t, 0.0), slot)

    def update_audio(self, t: float):
        if t != self.last_t:
            self.audio_tex.write(self.audio.at(t).tobytes())
            self.last_t = t

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
                  fade: float = 1.0) -> bytes:
        self.out.use()
        self.ctx.viewport = (0, 0, self.w, self.h)
        self.scene[0][0].use(0)
        self.scene[1][0].use(1)
        ta, ra = card_a if card_a else (self.blank, (0, 0, 1, 1))
        tb, rb = card_b if card_b else (self.blank, (0, 0, 1, 1))
        ta.use(2)
        tb.use(3)
        for i, n in enumerate(("sceneA", "sceneB", "cardA", "cardB")):
            _set(self.comp, n, i)
        _set(self.comp, "mixAB", float(mix_ab))
        _set(self.comp, "alphaA", float(alpha_a if card_a else 0.0))
        _set(self.comp, "alphaB", float(alpha_b if card_b else 0.0))
        _set(self.comp, "fade", float(fade))
        _set(self.comp, "rectA", tuple(float(x) for x in ra))
        _set(self.comp, "rectB", tuple(float(x) for x in rb))
        _set(self.comp, "res", (float(self.w), float(self.h)))
        self.comp_vao.render(self.mgl.TRIANGLE_STRIP)
        return self.out.read(components=3)

    def release(self):
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


def _state_at(t: float, starts, wins):
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
            return idx - 1, idx, _smooth((t - fs) / max(1e-6, fe - fs))
    return None, idx, 1.0


# ------------------------------------------------------------------------ the render
def render_video(plan: MixPlan, lib: dict[str, SongAnalysis], paths: dict[str, str], out_path,
                 vs: VideoSettings | None = None, shaders: ShaderLibrary | None = None,
                 audio: np.ndarray | None = None, progress=None, cancel=None) -> dict:
    """Render the whole mix to an mp4. `audio` is the already rendered mix (else it is rendered here)."""
    from .render import render_mix

    vs = vs or VideoSettings()
    shaders = shaders or ShaderLibrary()
    out_path = Path(out_path)
    w, h = (int(vs.width) // 2 * 2), (int(vs.height) // 2 * 2)
    say = progress or (lambda msg, frac: None)

    def check():
        if cancel and cancel():
            raise Cancelled("Cancelled")

    if audio is None:
        audio = render_mix(plan, lib, paths, progress=lambda m, f: say(m, 0.3 * f))
    check()
    seconds = audio.shape[1] / SR
    n_frames = int(math.ceil(seconds * vs.fps))
    starts, wins = frame_schedule(plan, seconds)
    chosen = resolve_assignments(plan, lib, vs, shaders)
    shader_of = [shaders.get(i) or BUILTIN["builtin:plasma"] for i in chosen]
    single = vs.mode == "single"

    with tempfile.TemporaryDirectory(prefix="lmm_video_") as tmp:
        tmp = Path(tmp)
        wav = tmp / "mix.wav"
        audio_io.write_audio(wav, audio)
        covers: dict[str, str | None] = {}
        for t in plan.tracks:
            if t.song_id not in covers:
                p = tmp / f"cover_{len(covers)}.jpg"
                covers[t.song_id] = str(p) if audio_io.extract_cover(paths[t.song_id], p) else None

        def card_for(r: GLRenderer, i: int):
            an = lib[plan.tracks[i].song_id]
            key = plan.tracks[i].uid
            return r.card(key, lambda: make_card(an.artist, an.title, covers[an.id], h, int(w * 0.55)))

        r = GLRenderer(w, h, AudioTexture(audio), fps=vs.fps)
        cmd = [audio_io.ffmpeg(), "-v", "error", "-nostdin", "-y",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(vs.fps), "-i", "-",
               "-i", str(wav), "-map", "0:v", "-map", "1:a", "-vf", "vflip",
               "-c:v", "libx264", "-preset", vs.preset, "-crf", str(vs.crf), "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "320k", "-shortest", "-movflags", "+faststart", str(out_path)]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            for k in range(n_frames):
                if k % 8 == 0:
                    check()
                    say(f"rendering video {k}/{n_frames}", 0.3 + 0.7 * k / max(1, n_frames))
                t = k / vs.fps
                r.update_audio(t)
                out_i, in_i, u = _state_at(t, starts, wins)

                def stime(i):  # shader clock: global for "single", else time since that song started
                    return t if single else t - starts[i]

                if single and chosen:
                    r.draw_shader(shader_of[0], t, k, 0)
                    mixab = 0.0
                else:
                    r.draw_shader(shader_of[in_i], stime(in_i), k, 0)
                    mixab = 0.0
                    if out_i is not None and shader_of[out_i].id != shader_of[in_i].id:
                        r.draw_shader(shader_of[out_i], stime(out_i), k, 1)
                        mixab = 1.0 - u          # scene[1] fades out as the new one fades in
                fade = min(1.0, t / 1.0) * min(1.0, max(0.0, (seconds - t) / 1.5))
                ca = cb = None
                aa = ab = 0.0
                if vs.show_overlay:
                    ca = card_for(r, in_i)
                    aa = min(1.0, t / 1.5)
                    if out_i is not None:
                        # one after the other, so the two cards never overprint: old fades out, then new fades in
                        aa = _smooth(2.0 * u - 1.0)
                        cb = card_for(r, out_i)
                        ab = _smooth(1.0 - 2.0 * u)
                frame = r.composite(mixab, ca, aa, cb, ab, fade)
                proc.stdin.write(frame)
            proc.stdin.close()
            err = proc.stderr.read().decode(errors="replace")
            if proc.wait() != 0:
                raise audio_io.AudioError("ffmpeg could not encode the video: " + err[:500])
        except BrokenPipeError:
            err = proc.stderr.read().decode(errors="replace")
            raise audio_io.AudioError("ffmpeg stopped unexpectedly: " + err[:500]) from None
        except BaseException:
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
            "visuals": [s.name for s in shader_of]}
