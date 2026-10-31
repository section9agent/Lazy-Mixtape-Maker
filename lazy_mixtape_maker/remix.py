"""Shader remix: make a visual react to the music.

A remix takes any shader's code and wraps it: the original `mainImage` is kept untouched under another name, and
a new `mainImage` around it reads the music (bass, mids, treble) and bends the picture with it: zoom, flash,
colour shifts, shake, RGB split, wobble, kaleidoscope, and a time push. Every effect has an amount and a band
of the music that drives it. The result is an ordinary shader, saved next to the others."""
from __future__ import annotations

import re
from dataclasses import dataclass

BANDS = {"bass": "Bass (kick)", "mid": "Mids (voice, synth)", "treble": "Treble (hats)", "all": "Whole sound"}


@dataclass(frozen=True)
class Mod:
    key: str
    label: str
    tip: str
    amount: float          # the amount a fresh remix starts with
    band: str              # the band it listens to by default


MODS: tuple[Mod, ...] = (
    Mod("zoom", "Beat zoom", "The picture pushes in on every kick.", 0.8, "bass"),
    Mod("flash", "Flash", "The picture gets brighter with the music.", 0.6, "bass"),
    Mod("hue", "Colour shift", "Colours rotate with the music.", 0.7, "mid"),
    Mod("shake", "Shake", "The picture shakes on hits.", 0.5, "bass"),
    Mod("split", "RGB split", "Red, green and blue slide apart (costs 3x the drawing).", 0.6, "treble"),
    Mod("wobble", "Wobble", "The picture ripples and warps.", 0.6, "mid"),
    Mod("kaleido", "Kaleidoscope", "Mirrors the picture around the centre; it turns with the music.", 0.0, "mid"),
    Mod("time", "Time push", "The shader's own animation speeds up and jumps with the music.", 0.5, "all"),
    Mod("contrast", "Contrast pump", "Darks get darker and lights brighter with the music.", 0.0, "bass"),
)
MOD_KEYS = [m.key for m in MODS]

PRESETS = {
    "gentle": ("Gentle", {"zoom": 0.4, "flash": 0.3, "hue": 0.3, "time": 0.3}),
    "club": ("Club", {"zoom": 0.8, "flash": 0.6, "hue": 0.6, "shake": 0.4, "time": 0.5}),
    "wild": ("Wild", {"zoom": 1.2, "flash": 0.9, "hue": 1.0, "shake": 0.8, "split": 0.8, "wobble": 0.8,
                      "kaleido": 0.8, "time": 0.9, "contrast": 0.6}),
}


class RemixError(ValueError):
    pass


def default_spec(preset: str = "club") -> dict:
    """{"mods": {key: {"on", "amount", "band"}}, "gain": 1.0}"""
    on = PRESETS.get(preset, PRESETS["club"])[1]
    mods = {}
    for m in MODS:
        mods[m.key] = {"on": m.key in on, "amount": float(on.get(m.key, m.amount) or m.amount or 0.5), "band": m.band}
    return {"mods": mods, "gain": 1.0}


def normalize_spec(spec: dict | None) -> dict:
    base = default_spec("club")
    out = {"mods": {}, "gain": 1.0}
    spec = spec or {}
    for k, v in base["mods"].items():
        cur = (spec.get("mods") or {}).get(k) or {}
        band = cur.get("band", v["band"])
        out["mods"][k] = {"on": bool(cur.get("on", False if spec else v["on"])),
                          "amount": float(min(2.0, max(0.0, cur.get("amount", v["amount"])))),
                          "band": band if band in BANDS else v["band"]}
    out["gain"] = float(min(3.0, max(0.2, spec.get("gain", 1.0))))
    return out


# ------------------------------------------------------------------ what a shader already does
def reacts_to_audio(shader) -> bool:
    """True when the shader's picture is driven by the music (its code samples an audio channel)."""
    if getattr(shader, "builtin", False) and not shader.passes:
        return bool(re.search(r"\biChannel0\b", shader.source))
    if not shader.passes:                         # plain shaders get the music on iChannel0
        return bool(re.search(r"\biChannel0\b", shader.source))
    for p in shader.passes:
        for ch, kind in (p.get("inputs") or {}).items():
            if kind == "audio" and re.search(rf"\biChannel{ch}\b", p.get("code", "")):
                return True
    return False


# -------------------------------------------------------------------------------- code
_BASE = "lmm_base_mainImage"


def _band_expr(band: str) -> str:
    return {"bass": "lmm_bass", "mid": "lmm_mid", "treble": "lmm_treble", "all": "lmm_all"}[band]


def _wrapper(spec: dict, ch: int) -> str:
    m = spec["mods"]
    g = spec["gain"]

    def on(k):
        return m[k]["on"] and m[k]["amount"] > 0.001

    def amt(k):
        return f"{m[k]['amount']:.3f}"

    def b(k):
        return f"({_band_expr(m[k]['band'])})"

    L = []
    L.append(f"""
float lmm_tap(float u) {{ return texture(iChannel{ch}, vec2(u, 0.25)).x; }}
float lmm_lvl(float x) {{ return clamp((x - 0.20) / 0.50 * {g:.3f}, 0.0, 1.0); }}
vec3 lmm_hue(vec3 c, float a) {{
    float s = sin(a), co = cos(a);
    vec3 k = vec3(0.57735);
    return c * co + cross(k, c) * s + k * dot(k, c) * (1.0 - co);
}}
void mainImage(out vec4 fragColor, in vec2 fragCoord) {{
    float lmm_bass   = lmm_lvl((lmm_tap(0.004) + lmm_tap(0.012) + lmm_tap(0.020)) / 3.0);
    float lmm_mid    = lmm_lvl((lmm_tap(0.05) + lmm_tap(0.09) + lmm_tap(0.14)) / 3.0);
    float lmm_treble = lmm_lvl((lmm_tap(0.20) + lmm_tap(0.30) + lmm_tap(0.45)) / 3.0);
    float lmm_all    = (lmm_bass + lmm_mid + lmm_treble) / 3.0;
    float t0 = lmm_real_time();
    vec2 res = iResolution.xy;
    vec2 c = res * 0.5;
    vec2 p = fragCoord;
    lmm_time = t0;""")
    if on("time"):
        L.append(f"    lmm_time = t0 + {amt('time')} * 0.9 * {b('time')};")
    if on("kaleido"):
        n = max(2, int(round(2 + m["kaleido"]["amount"] * 2)))
        L.append(f"""    {{
        vec2 q = p - c; float r = length(q);
        float a = atan(q.y, q.x) + t0 * 0.15 + {b('kaleido')} * 0.6;
        float seg = 6.2831853 / {float(n * 2):.1f};
        a = abs(mod(a, seg) - seg * 0.5);
        p = c + r * vec2(cos(a), sin(a));
    }}""")
    if on("zoom"):
        L.append(f"    p = c + (p - c) / (1.0 + {amt('zoom')} * 0.30 * {b('zoom')});")
    if on("shake"):
        L.append(f"    p += {amt('shake')} * 0.025 * res.y * {b('shake')} * vec2(sin(t0 * 63.0), cos(t0 * 49.0));")
    if on("wobble"):
        L.append(f"    p += {amt('wobble')} * 0.014 * res.y * {b('wobble')} * vec2(sin(p.y * 0.021 + t0 * 4.0), cos(p.x * 0.017 + t0 * 3.0));")
    if on("split"):
        L.append(f"""    float off = {amt('split')} * 0.018 * res.x * {b('split')};
    vec4 cr, cg, cb;
    {_BASE}(cr, p + vec2(off, 0.0));
    {_BASE}(cg, p);
    {_BASE}(cb, p - vec2(off, 0.0));
    vec4 col = vec4(cr.r, cg.g, cb.b, cg.a);""")
    else:
        L.append(f"    vec4 col;\n    {_BASE}(col, p);")
    if on("hue"):
        L.append(f"    col.rgb = lmm_hue(col.rgb, {amt('hue')} * 2.2 * {b('hue')} + 0.0);")
    if on("contrast"):
        L.append(f"    col.rgb = clamp((col.rgb - 0.5) * (1.0 + {amt('contrast')} * 0.9 * {b('contrast')}) + 0.5, 0.0, 1.0);")
    if on("flash"):
        L.append(f"    col.rgb *= 1.0 + {amt('flash')} * 0.8 * {b('flash')};")
    L.append("    fragColor = col;\n}\n")
    return "\n".join(L)


def _rename_main(code: str) -> str:
    if not re.search(r"\bmainImage\b", code):
        raise RemixError("That shader has no mainImage function, so it can't be remixed.")
    return re.sub(r"\bmainImage\b", _BASE, code)


def apply(source: str, passes: list[dict], spec: dict | None) -> tuple[str, list[dict]]:
    """Wrap a shader's Image pass. Returns (source, passes) for a new Shader. `passes` is [] for plain shaders."""
    spec = normalize_spec(spec)
    passes = [dict(p, inputs=dict(p.get("inputs") or {})) if p.get("inputs") is not None else dict(p) for p in (passes or [])]
    if passes:
        idx = next((i for i in range(len(passes) - 1, -1, -1) if passes[i].get("type") == "image"), None)
        if idx is None:
            raise RemixError("That shader has no Image pass.")
        img = passes[idx]
        code = img["code"]
        inputs = img.setdefault("inputs", {})
        ch = next((int(c) for c, k in inputs.items() if k == "audio"), None)
        if ch is None:                                     # a channel the Image code doesn't read
            ch = next((c for c in range(4) if not re.search(rf"\biChannel{c}\b", code)), None)
            if ch is None:
                raise RemixError("All four inputs of this shader's Image pass are in use, so there is no room to add the music.")
            inputs[str(ch)] = "audio"
    else:
        ch, code = 0, source                               # plain shaders get the music on iChannel0
    head = ("float lmm_real_time() { return iTime; }\nfloat lmm_time = 0.0;\n#define iTime lmm_time\n")
    new_code = head + _rename_main(code) + "\n" + _wrapper(spec, ch)
    if passes:
        common = next((p["code"] for p in passes if p.get("type") == "common"), "")
        passes[idx]["code"] = new_code
        return (common + "\n" if common.strip() else "") + new_code, passes
    return new_code, []
