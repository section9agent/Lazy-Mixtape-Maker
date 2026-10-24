"""Visuals: a local library of Shadertoy-style fragment shaders.

Shaders are plain Shadertoy "Image" pass code (``void mainImage(out vec4, in vec2)``).
Anything the user imports is stored on disk (one JSON file per shader) so it is
available offline from then on. A handful of original shaders ship with the app.

Importing from shadertoy.com never needs the network: copy the code from the
shader's editor (or use its "download JSON" export) and paste / load it. An
optional online import using a user-supplied Shadertoy API key is also provided."""
from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# ------------------------------------------------------------------ data location
def data_dir() -> Path:
    env = os.environ.get("LMM_DATA_DIR")
    if env:
        base = Path(env)
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "LazyMixtapeMaker"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "LazyMixtapeMaker"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "LazyMixtapeMaker"
    return base


# --------------------------------------------------------------------- shader model
@dataclass
class Shader:
    id: str
    name: str
    source: str
    author: str = ""
    origin: str = "pasted"          # builtin | pasted | file | shadertoy-json | shadertoy-api
    url: str = ""
    energy: str = "mid"             # calm | mid | high  (used by the "app chooses" mode)
    warnings: list[str] = field(default_factory=list)
    added: str = ""
    # Multi-pass shaders: [{"name": "Buffer A"|...|"Image", "code": str, "inputs": {channel: kind}}]
    # kind is "buffer:A".."buffer:D", "audio", "keyboard" or "noise". Empty = just `source`.
    passes: list[dict] = field(default_factory=list)

    @property
    def builtin(self) -> bool:
        return self.origin == "builtin"

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, d: dict) -> "Shader":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ------------------------------------------------------------- GLSL wrapping (shared)
VERTEX = """#version 330 core
in vec2 p;
void main(){ gl_Position = vec4(p, 0.0, 1.0); }
"""

_HEADER = """#version 330 core
uniform vec3  iResolution;
uniform float iTime;
uniform float iTimeDelta;
uniform int   iFrame;
uniform vec4  iMouse;
uniform vec4  iDate;
uniform float iSampleRate;
uniform float iChannelTime[4];
uniform vec3  iChannelResolution[4];
uniform sampler2D iChannel0;
uniform sampler2D iChannel1;
uniform sampler2D iChannel2;
uniform sampler2D iChannel3;
out vec4 _lmm_fragColor;
#define texture2D texture
#define textureCube texture
#define HW_PERFORMANCE 1
#line 1
"""

_FOOTER = """
void main(){
    vec4 c = vec4(0.0, 0.0, 0.0, 1.0);
    mainImage(c, gl_FragCoord.xy);
    _lmm_fragColor = vec4(c.rgb, 1.0);
}
"""

_FOOTER_BUFFER = """
void main(){
    vec4 c = vec4(0.0, 0.0, 0.0, 1.0);
    mainImage(c, gl_FragCoord.xy);
    _lmm_fragColor = c;
}
"""


def wrap_fragment(source: str, buffer: bool = False, common: str = "") -> str:
    """Turn Shadertoy pass code into a desktop GLSL 3.30 program."""
    src = re.sub(r"^\s*#version[^\n]*\n?", "", source, flags=re.M)
    if common:
        src = re.sub(r"^\s*#version[^\n]*\n?", "", common, flags=re.M) + "\n" + src
    return _HEADER + src + "\n" + (_FOOTER_BUFFER if buffer else _FOOTER)


class ShaderError(RuntimeError):
    pass


def make_context():
    """A headless OpenGL context (works without a window; EGL fallback on Linux)."""
    import moderngl

    errors = []
    for backend in (None, "egl"):
        try:
            return moderngl.create_standalone_context(require=330, **({"backend": backend} if backend else {}))
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))
    raise ShaderError("Could not create an OpenGL 3.3 context for rendering visuals: " + "; ".join(errors))


def compile_program(ctx, source: str, buffer: bool = False, common: str = ""):
    try:
        return ctx.program(vertex_shader=VERTEX, fragment_shader=wrap_fragment(source, buffer, common))
    except Exception as e:  # noqa: BLE001
        msg = str(e).strip()
        # moderngl prefixes the whole log; keep it readable
        raise ShaderError(msg[:1500]) from None


def validate(source: str, passes: list[dict] | None = None) -> str | None:
    """None if the shader compiles, otherwise the compiler message."""
    if "mainImage" not in source:
        return "No mainImage function found - paste the Shadertoy 'Image' code."
    ctx = None
    try:
        ctx = make_context()
        if passes:
            common = next((p["code"] for p in passes if p.get("type") == "common"), "")
            for p in passes:
                if p.get("type") == "common":
                    continue
                prog = compile_program(ctx, p["code"], buffer=p["type"] == "buffer", common=common)
                prog.release()
            return None
        prog = compile_program(ctx, source)
        prog.release()
        return None
    except ShaderError as e:
        return str(e)
    finally:
        if ctx is not None:
            ctx.release()


# ------------------------------------------------------------------------ importing
def shader_id_from_url(text: str) -> str | None:
    m = re.search(r"shadertoy\.com/(?:view|embed)/([A-Za-z0-9]{6})", text or "")
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9]{6}", (text or "").strip()):
        return text.strip()
    return None


_BUFFER_FILES = {"buffer00": "A", "buffer01": "B", "buffer02": "C", "buffer03": "D"}


def parse_shadertoy_json(text: str):
    """Return (name, author, code, warnings, passes) from Shadertoy JSON (API or editor export).
    `passes` is [] for plain single-pass shaders."""
    data = json.loads(text)
    if isinstance(data, list):
        data = data[0]
    if "Shader" in data:
        data = data["Shader"]
    if "error" in data:
        raise ValueError(f"Shadertoy said: {data['error']}")
    info = data.get("info", {})
    rps = data.get("renderpass", [])
    image = next((p for p in rps if p.get("type") == "image"), None)
    if image is None:
        raise ValueError("That JSON has no Image pass (sound / cubemap-only shaders can't be used).")
    common = "\n".join(p.get("code", "") for p in rps if p.get("type") == "common")
    warnings: list[str] = []
    out_ids = {}
    for p in rps:
        if p.get("type") == "buffer":
            letter = (p.get("name", "")[-1:] or "A").upper()
            for o in p.get("outputs", []):
                out_ids[str(o.get("id"))] = letter
    unsupported: set[str] = set()

    def kind_of(inp):
        ct = inp.get("ctype") or inp.get("type")
        if ct == "buffer":
            letter = out_ids.get(str(inp.get("id")))
            if not letter:
                fp = str(inp.get("filepath", ""))
                letter = next((v for k, v in _BUFFER_FILES.items() if k in fp), "A")
            return f"buffer:{letter}"
        if ct in ("music", "musicstream", "mic"):
            return "audio"
        if ct == "keyboard":
            return "keyboard"
        if ct in ("webcam", "video", "volume", "cubemap"):
            unsupported.add(ct)
        return "noise"

    passes = []
    if any(p.get("type") == "buffer" for p in rps):
        order = {"Buffer A": 0, "Buffer B": 1, "Buffer C": 2, "Buffer D": 3}
        for p in sorted([p for p in rps if p.get("type") in ("buffer", "image")],
                        key=lambda p: order.get(p.get("name"), 9)):
            passes.append({"name": p.get("name", "Image"), "type": p["type"], "code": p.get("code", ""),
                           "inputs": {str(i.get("channel", 0)): kind_of(i) for i in p.get("inputs", [])}})
        if common.strip():
            passes.insert(0, {"name": "Common", "type": "common", "code": common, "inputs": {}})
    else:
        for i in image.get("inputs", []):
            kind_of(i)
    if unsupported:
        warnings.append("Uses inputs (" + ", ".join(sorted(unsupported))
                        + ") that aren't available offline; they're replaced with noise.")
    code = (common + "\n" if common else "") + image.get("code", "")
    return info.get("name", "Imported shader"), info.get("username", ""), code, warnings, passes


def shader_to_json(sh: "Shader") -> str:
    """Shadertoy-style JSON of a shader, so it can be backed up or shared and imported again."""
    info = {"name": sh.name, "username": sh.author, "description": "exported from Lazy Mixtape Maker"}
    if not sh.passes:
        rps = [{"type": "image", "name": "Image", "code": sh.source, "inputs": [], "outputs": []}]
    else:
        rps = []
        for p in sh.passes:
            ins = []
            for ch, kind in p.get("inputs", {}).items():
                ent = {"channel": int(ch)}
                if kind.startswith("buffer:"):
                    ent.update(ctype="buffer", id="buf" + kind.split(":")[1])
                elif kind == "audio":
                    ent.update(ctype="music", id="audio")
                elif kind == "keyboard":
                    ent.update(ctype="keyboard", id="kb")
                else:
                    ent.update(ctype="texture", id="noise")
                ins.append(ent)
            outs = []
            if p.get("type") == "buffer":
                outs = [{"id": "buf" + p["name"][-1].upper(), "channel": 0}]
            rps.append({"type": p["type"], "name": p["name"], "code": p["code"], "inputs": ins, "outputs": outs})
    return json.dumps({"Shader": {"info": info, "renderpass": rps}}, indent=1)


def fetch_from_shadertoy(url_or_id: str, api_key: str, timeout: float = 15.0):
    """Optional online import via the Shadertoy API (needs the user's own API key).
    Returns (name, author, code, warnings, url)."""
    import urllib.request

    sid = shader_id_from_url(url_or_id)
    if not sid:
        raise ValueError("That doesn't look like a Shadertoy link (https://www.shadertoy.com/view/XXXXXX).")
    if not api_key:
        raise ValueError("Online import needs a Shadertoy API key (shadertoy.com -> your profile -> Apps). "
                         "Or just paste the shader's code instead - that works offline.")
    req = urllib.request.Request(f"https://www.shadertoy.com/api/v1/shaders/{sid}?key={api_key}",
                                 headers={"User-Agent": "LazyMixtapeMaker"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            text = r.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"Could not reach Shadertoy ({e}). You can paste the shader code instead.") from None
    name, author, code, warnings, passes = parse_shadertoy_json(text)
    return name, author, code, warnings, f"https://www.shadertoy.com/view/{sid}", passes


# ----------------------------------------------------------------------- the library
class ShaderLibrary:
    """Built-in shaders plus the user's saved ones (stored in the app data folder)."""

    def __init__(self, folder: str | Path | None = None):
        self.folder = Path(folder) if folder else data_dir() / "visuals"
        self._user: dict[str, Shader] = {}
        self.reload()

    # -- reading
    def reload(self) -> None:
        self._user = {}
        if self.folder.is_dir():
            for f in sorted(self.folder.glob("*.json")):
                try:
                    sh = Shader.from_dict(json.loads(f.read_text(encoding="utf-8")))
                    self._user[sh.id] = sh
                except Exception:  # noqa: BLE001 - one bad file must not hide the rest
                    continue

    def all(self) -> list[Shader]:
        return list(BUILTIN.values()) + sorted(self._user.values(), key=lambda s: s.added)

    def get(self, sid: str) -> Shader | None:
        return BUILTIN.get(sid) or self._user.get(sid)

    # -- writing
    def add(self, name: str, source: str, *, author: str = "", origin: str = "pasted", url: str = "",
            warnings: list[str] | None = None, energy: str = "mid", check: bool = True,
            passes: list[dict] | None = None) -> Shader:
        if check:
            err = validate(source, passes)
            if err:
                raise ShaderError(err)
        for ex in self._user.values():  # same code twice -> reuse (the newest explicit name wins)
            if ex.source.strip() == source.strip():
                nm = (name or "").strip()[:80]
                if nm and nm != "Imported shader" and nm != ex.name:
                    ex.name = nm
                    self._save(ex)
                return ex
        sh = Shader(id=uuid.uuid4().hex[:10], name=(name or "Imported shader").strip()[:80], source=source,
                    author=author, origin=origin, url=url, energy=energy, warnings=warnings or [],
                    added=time.strftime("%Y-%m-%dT%H:%M:%S"), passes=passes or [])
        self._save(sh)
        return sh

    def _save(self, sh: Shader) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / f"{sh.id}.json").write_text(json.dumps(sh.to_dict(), indent=1), encoding="utf-8")
        self._user[sh.id] = sh

    def add_from_text(self, text: str, name: str = "") -> Shader:
        """Accepts raw Shadertoy code or Shadertoy JSON."""
        t = text.strip()
        if not t:
            raise ValueError("Nothing to import.")
        if t[0] in "{[":
            n, author, code, warns, passes = parse_shadertoy_json(t)
            return self.add(name or n, code, author=author, origin="shadertoy-json", warnings=warns, passes=passes)
        return self.add(name or "Imported shader", t, origin="pasted")

    def add_from_file(self, path) -> Shader:
        p = Path(path)
        text = p.read_text(encoding="utf-8", errors="replace")
        sh = self.add_from_text(text, name=p.stem)
        return sh

    def add_from_shadertoy(self, url_or_id: str, api_key: str) -> Shader:
        name, author, code, warns, url, passes = fetch_from_shadertoy(url_or_id, api_key)
        return self.add(name, code, author=author, origin="shadertoy-api", url=url, warnings=warns, passes=passes)

    def rename(self, sid: str, name: str) -> None:
        sh = self._user[sid]
        sh.name = name.strip() or sh.name
        self._save(sh)

    def set_energy(self, sid: str, energy: str) -> None:
        sh = self._user[sid]
        sh.energy = energy
        self._save(sh)

    def remove(self, sid: str) -> None:
        if sid in BUILTIN:
            raise ValueError("Built-in visuals can't be removed.")
        self._user.pop(sid, None)
        f = self.folder / f"{sid}.json"
        if f.exists():
            f.unlink()

    # -- sharing: sessions carry the code of the shaders they use
    def export_used(self, ids) -> dict[str, dict]:
        out = {}
        for sid in ids:
            sh = self._user.get(sid)
            if sh:
                out[sid] = sh.to_dict()
        return out

    def import_embedded(self, embedded: dict[str, dict]) -> None:
        """Add shaders that came inside a session file (keeping their ids so the
        session's assignments still line up). Existing ids are left alone."""
        for sid, d in (embedded or {}).items():
            if sid in BUILTIN or sid in self._user:
                continue
            try:
                self._save(Shader.from_dict({**d, "id": sid}))
            except Exception:  # noqa: BLE001
                continue


# -------------------------------------------------------------------- built-in shaders
def _b(sid, name, energy, source):
    return Shader(id=sid, name=name, source=source.strip() + "\n", author="Lazy Mixtape Maker",
                  origin="builtin", energy=energy)


_PLASMA = """
void mainImage(out vec4 O, in vec2 F){
    vec2 uv = (F - 0.5*iResolution.xy) / iResolution.y;
    float t = iTime * 0.4;
    float v = sin(uv.x*6.0 + t) + sin((uv.y*5.0 + t)*1.3) + sin((uv.x+uv.y)*5.0 + t*1.7);
    float r = length(uv*3.0 + vec2(sin(t), cos(t*0.7)));
    v += sin(r*4.0 - t*2.0);
    vec3 col = 0.5 + 0.5*cos(6.2831*(v*0.18 + vec3(0.0, 0.33, 0.67)) + t*0.5);
    col *= 0.7 + 0.3*smoothstep(1.3, 0.2, length(uv));
    O = vec4(col, 1.0);
}
"""

_TUNNEL = """
void mainImage(out vec4 O, in vec2 F){
    vec2 p = (F - 0.5*iResolution.xy) / iResolution.y;
    float bass = texture(iChannel0, vec2(0.03, 0.25)).x;
    float r = max(length(p), 1e-3);
    float a = atan(p.y, p.x) / 6.2831853;
    float z = 0.35 / r;
    float t = iTime * (0.7 + 1.5*bass);
    float rings = smoothstep(0.30, 0.5, abs(fract(z - t) - 0.5));
    float spokes = smoothstep(0.30, 0.5, abs(fract(a*12.0 + z*0.15 + iTime*0.05) - 0.5));
    vec3 c1 = 0.5 + 0.5*cos(6.2831*(z*0.08 + vec3(0.0, 0.3, 0.6)) + iTime*0.3);
    vec3 col = c1 * (0.25 + 0.9*rings) + vec3(1.0, 0.3, 0.8) * spokes * 0.35;
    col *= smoothstep(0.0, 0.25, r) * (0.8 + 0.6*bass);
    O = vec4(col, 1.0);
}
"""

_AURORA = """
float h21(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float vn(vec2 p){
    vec2 i = floor(p), f = fract(p); f = f*f*(3.0 - 2.0*f);
    return mix(mix(h21(i), h21(i + vec2(1,0)), f.x), mix(h21(i + vec2(0,1)), h21(i + vec2(1,1)), f.x), f.y);
}
void mainImage(out vec4 O, in vec2 F){
    vec2 uv = F / iResolution.xy;
    float t = iTime * 0.12;
    vec3 col = mix(vec3(0.01, 0.02, 0.06), vec3(0.02, 0.07, 0.12), uv.y);
    for (int i = 0; i < 4; i++){
        float fi = float(i);
        float y = 0.45 + 0.1*fi + 0.12*sin(uv.x*(2.0 + fi) + t*(2.0 + fi) + fi*1.7) + 0.06*vn(vec2(uv.x*4.0 + t*3.0, fi*3.0));
        float band = exp(-pow((uv.y - y) * (6.0 + 2.0*fi), 2.0));
        vec3 tint = 0.55 + 0.45*cos(vec3(0.0, 2.0, 4.0) + fi*0.9 + 3.2);
        col += tint * band * (0.45 - 0.07*fi) * (0.7 + 0.3*vn(vec2(uv.x*8.0 - t*5.0, fi)));
    }
    vec2 sp = floor(F / 3.0);
    col += step(0.9975, h21(sp)) * (0.5 + 0.5*sin(iTime + h21(sp + 1.0)*30.0)) * smoothstep(0.55, 0.9, uv.y);
    O = vec4(col, 1.0);
}
"""

_KALEIDO = """
void mainImage(out vec4 O, in vec2 F){
    vec2 p = (F - 0.5*iResolution.xy) / iResolution.y;
    float bass = texture(iChannel0, vec2(0.04, 0.25)).x;
    float mid  = texture(iChannel0, vec2(0.25, 0.25)).x;
    float a = atan(p.y, p.x), r = length(p);
    float seg = 6.2831853 / 8.0;
    a = abs(mod(a, seg) - 0.5*seg);
    vec2 q = r * vec2(cos(a), sin(a));
    q *= 3.0 + 1.5*bass;
    float t = iTime * 0.5;
    float v = 0.0;
    for (int i = 0; i < 4; i++){
        q = abs(q) / dot(q, q) - vec2(0.8 + 0.1*sin(t), 0.6 + 0.1*cos(t*1.3));
        v += length(q);
    }
    vec3 col = 0.5 + 0.5*cos(6.2831*(v*0.07 + mid + vec3(0.0, 0.33, 0.67)) + t);
    col *= clamp(v*0.12, 0.2, 1.2) * (0.8 + 0.5*bass);
    O = vec4(col, 1.0);
}
"""

_SUNSET = """
void mainImage(out vec4 O, in vec2 F){
    vec2 p = (F - 0.5*iResolution.xy) / iResolution.y;
    float horizon = -0.05;
    vec3 col = mix(vec3(0.99, 0.35, 0.45), vec3(0.12, 0.04, 0.30), smoothstep(horizon, 0.55, p.y));
    float sun = smoothstep(0.31, 0.30, length(p - vec2(0.0, 0.12)));
    float slats = step(0.0, sin(p.y*70.0 - iTime*1.5) + (0.10 - p.y)*6.0 - 0.6);
    sun *= mix(1.0, slats, step(p.y, 0.10));
    col = mix(col, mix(vec3(1.0, 0.45, 0.35), vec3(1.0, 0.85, 0.30), smoothstep(-0.2, 0.4, p.y)), sun);
    if (p.y < horizon){
        float z = 0.5 / (horizon - p.y);
        float gx = abs(fract(p.x*z*0.8) - 0.5);
        float gz = abs(fract(z*0.8 - iTime*0.7) - 0.5);
        float g = max(smoothstep(0.46, 0.5, gx), smoothstep(0.46, 0.5, gz)) / (1.0 + 0.12*z);
        col = mix(vec3(0.06, 0.0, 0.14), vec3(0.95, 0.25, 0.95), clamp(g, 0.0, 1.0));
        col += vec3(0.6, 0.15, 0.4) * exp(-(horizon - p.y) * 18.0) * 0.5;
    }
    O = vec4(col, 1.0);
}
"""

_BARS = """
void mainImage(out vec4 O, in vec2 F){
    vec2 uv = F / iResolution.xy;
    float n = 48.0;
    float i = floor(uv.x * n);
    float fx = fract(uv.x * n);
    float f = texture(iChannel0, vec2(pow((i + 0.5) / n, 1.6) * 0.8, 0.25)).x;
    float h = f * 0.8 + 0.02;
    float bar = step(uv.y, h) * step(0.12, fx) * step(fx, 0.88);
    vec3 base = 0.5 + 0.5*cos(6.2831*(uv.x*0.6 + vec3(0.0, 0.33, 0.67)) + iTime*0.4);
    vec3 bg = mix(vec3(0.02, 0.02, 0.06), vec3(0.08, 0.04, 0.14), uv.y);
    vec3 col = mix(bg, base * (0.5 + 0.7*uv.y/max(h, 0.01)), bar);
    col += base * 0.12 * smoothstep(h + 0.12, h, uv.y) * step(h, uv.y) * step(0.12, fx) * step(fx, 0.88);
    O = vec4(col, 1.0);
}
"""

_WARP = """
float h12(vec2 p){ return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }
void mainImage(out vec4 O, in vec2 F){
    vec2 p = (F - 0.5*iResolution.xy) / iResolution.y;
    float bass = texture(iChannel0, vec2(0.03, 0.25)).x;
    vec3 col = vec3(0.0, 0.0, 0.02);
    for (int l = 0; l < 5; l++){
        float fl = float(l);
        float sc = 6.0 + fl*5.0;
        float t = iTime * (0.25 + 0.15*fl) * (1.0 + bass);
        float r = length(p);
        float a = atan(p.y, p.x);
        vec2 g = vec2(a*sc*0.5, log(r + 1e-3)*sc*0.6 - t*sc*0.9);
        vec2 id = floor(g), f = fract(g) - 0.5;
        float rnd = h12(id + fl*17.0);
        float star = smoothstep(0.12*rnd + 0.02, 0.0, length(f)) * step(0.55, rnd);
        col += star * (0.6 + 0.4*cos(vec3(0.0, 2.0, 4.0) + rnd*6.0)) * smoothstep(0.0, 0.3, r) * 1.6;
    }
    col += vec3(0.3, 0.2, 0.9) * bass * 0.25 * smoothstep(0.7, 0.0, length(p));
    O = vec4(col, 1.0);
}
"""

_MARBLE = """
float h21(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float vn(vec2 p){
    vec2 i = floor(p), f = fract(p); f = f*f*(3.0 - 2.0*f);
    return mix(mix(h21(i), h21(i + vec2(1,0)), f.x), mix(h21(i + vec2(0,1)), h21(i + vec2(1,1)), f.x), f.y);
}
float fbm(vec2 p){ float s = 0.0, a = 0.5; for (int i = 0; i < 5; i++){ s += a*vn(p); p = p*2.03 + 7.1; a *= 0.5; } return s; }
void mainImage(out vec4 O, in vec2 F){
    vec2 p = (F - 0.5*iResolution.xy) / iResolution.y * 2.2;
    float t = iTime * 0.08;
    vec2 q = vec2(fbm(p + t), fbm(p + vec2(5.2, 1.3) - t));
    vec2 r = vec2(fbm(p + 4.0*q + vec2(1.7, 9.2) + 2.0*t), fbm(p + 4.0*q + vec2(8.3, 2.8) - 2.0*t));
    float f = fbm(p + 4.0*r);
    vec3 col = mix(vec3(0.05, 0.08, 0.20), vec3(0.85, 0.35, 0.55), clamp(f*f*2.4, 0.0, 1.0));
    col = mix(col, vec3(0.95, 0.85, 0.6), clamp(length(r)*0.6 - 0.2, 0.0, 1.0)*f);
    O = vec4(col * (0.6 + 0.8*f), 1.0);
}
"""

BUILTIN: dict[str, Shader] = {s.id: s for s in [
    _b("builtin:plasma", "Plasma Waves", "calm", _PLASMA),
    _b("builtin:aurora", "Aurora", "calm", _AURORA),
    _b("builtin:marble", "Liquid Marble", "calm", _MARBLE),
    _b("builtin:sunset", "Synth Sunset", "mid", _SUNSET),
    _b("builtin:bars", "Spectrum Bars", "mid", _BARS),
    _b("builtin:tunnel", "Neon Tunnel", "high", _TUNNEL),
    _b("builtin:kaleido", "Kaleido Pulse", "high", _KALEIDO),
    _b("builtin:warp", "Starfield Warp", "high", _WARP),
]}
