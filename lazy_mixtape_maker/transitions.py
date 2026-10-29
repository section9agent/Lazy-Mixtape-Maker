"""Video transitions: how one picture (a visual or a video clip) hands over to the next.

There are 20: twelve classic ones and eight that react to the rhythm of the music (they get the bass level
and a "kick" pulse measured from the audio at every frame). Each is a few lines of GLSL inside the compositor
and shares the same parameters, so the editors can offer the same controls for all of them."""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass

# key, label, kind, id used by the shader, what the controls do
TRANSITIONS = [
    ("crossfade", "Crossfade", "standard", 0),
    ("dip_black", "Dip to black", "standard", 1),
    ("dip_white", "Dip to white", "standard", 2),
    ("wipe", "Wipe", "standard", 3),
    ("push", "Push / slide", "standard", 4),
    ("iris", "Circle iris", "standard", 5),
    ("clock", "Clock wipe", "standard", 6),
    ("zoom", "Zoom through", "standard", 7),
    ("dissolve", "Noise dissolve", "standard", 8),
    ("pixelate", "Pixelate", "standard", 9),
    ("blinds", "Blinds", "standard", 10),
    ("swirl", "Swirl", "standard", 11),
    ("beat_zoom", "Beat zoom", "rhythm", 12),
    ("beat_flash", "Beat flash", "rhythm", 13),
    ("beat_shake", "Beat shake + RGB split", "rhythm", 14),
    ("glitch", "Glitch slices", "rhythm", 15),
    ("bass_ripple", "Bass ripple", "rhythm", 16),
    ("strobe", "Beat strobe", "rhythm", 17),
    ("beat_mosaic", "Beat mosaic", "rhythm", 18),
    ("kick_spin", "Kick spin", "rhythm", 19),
]
KEYS = [t[0] for t in TRANSITIONS]
LABELS = {t[0]: t[1] for t in TRANSITIONS}
KIND = {t[0]: t[2] for t in TRANSITIONS}
GL_ID = {t[0]: t[3] for t in TRANSITIONS}

# choices that pick a transition for you (a different one at each boundary, never the same twice in a row)
RANDOM_CHOICES = {
    "random": "Random (all 20)",
    "random_standard": "Random (classic only)",
    "random_rhythm": "Random (rhythm only)",
}
EASES = {"smooth": "Smooth", "linear": "Linear", "in": "Ease in", "out": "Ease out"}

# which controls matter for which transition (the editors grey out the rest)
USES = {
    "crossfade": set(), "dip_black": set(), "dip_white": set(),
    "wipe": {"angle", "softness"}, "push": {"angle"}, "iris": {"softness"}, "clock": {"angle", "softness"},
    "zoom": {"intensity"}, "dissolve": {"softness", "intensity"}, "pixelate": {"intensity"},
    "blinds": {"angle", "softness", "intensity"}, "swirl": {"intensity"},
    "beat_zoom": {"intensity", "sensitivity"}, "beat_flash": {"intensity", "sensitivity"},
    "beat_shake": {"intensity", "sensitivity"}, "glitch": {"intensity", "sensitivity"},
    "bass_ripple": {"intensity", "sensitivity"}, "strobe": {"intensity", "sensitivity"},
    "beat_mosaic": {"intensity", "sensitivity"}, "kick_spin": {"intensity", "sensitivity"},
}


@dataclass
class TransitionParams:
    type: str = "crossfade"       # a key above, or one of RANDOM_CHOICES
    duration: float = 0.0         # seconds; 0 = automatic (a mix follows its audio blend, the studio its blend setting)
    angle: float = 0.0            # degrees: direction of wipes, pushes, blinds; start angle of the clock
    softness: float = 0.3         # 0..1 edge softness
    intensity: float = 1.0        # 0..2 strength (zoom amount, pixel size, shake, glitch ...)
    sensitivity: float = 1.0      # 0..2 how strongly the rhythm effects react to the audio
    ease: str = "smooth"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict | None) -> "TransitionParams":
        d = d or {}
        p = cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        if p.type not in KIND and p.type not in RANDOM_CHOICES:
            p.type = "crossfade"
        p.duration = max(0.0, float(p.duration))
        p.softness = min(1.0, max(0.0, float(p.softness)))
        p.intensity = min(2.0, max(0.0, float(p.intensity)))
        p.sensitivity = min(2.0, max(0.0, float(p.sensitivity)))
        if p.ease not in EASES:
            p.ease = "smooth"
        return p


def resolve(params: TransitionParams, seed, index: int) -> TransitionParams:
    """Turn "random…" into a concrete transition for boundary `index` (stable for a given seed)."""
    if params.type in KIND:
        return params
    pool = [k for k in KEYS if params.type == "random" or (params.type == "random_standard" and KIND[k] == "standard")
            or (params.type == "random_rhythm" and KIND[k] == "rhythm")]
    rng = random.Random(f"{seed}:transition:{index}")
    pick = rng.choice(pool)
    if index > 0:                                   # not the same one twice in a row
        prev = random.Random(f"{seed}:transition:{index - 1}").choice(pool)
        while len(pool) > 1 and pick == prev:
            pick = rng.choice(pool)
    d = params.to_dict()
    d["type"] = pick
    return TransitionParams(**d)


def ease(u: float, kind: str) -> float:
    u = min(1.0, max(0.0, u))
    if kind == "linear":
        return u
    if kind == "in":
        return u * u
    if kind == "out":
        return 1.0 - (1.0 - u) * (1.0 - u)
    return u * u * (3.0 - 2.0 * u)


# ------------------------------------------------------------------------------------- GLSL
GLSL = """
uniform sampler2D texOut;   // the picture that is leaving
uniform sampler2D texIn;    // the picture that is arriving
uniform int   tType;
uniform float tP;           // progress 0 (all outgoing) .. 1 (all incoming)
uniform float tAngle;       // radians
uniform float tSoft;
uniform float tInt;
uniform float tSens;
uniform float tBass;        // 0..1 bass level of the music
uniform float tPulse;       // 0..1 kick / onset pulse
uniform float tTime;
uniform float tBpm;
uniform vec2  res;

float hash(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float vnoise(vec2 p){
    vec2 i = floor(p), f = fract(p); f = f*f*(3.0-2.0*f);
    return mix(mix(hash(i), hash(i+vec2(1,0)), f.x), mix(hash(i+vec2(0,1)), hash(i+vec2(1,1)), f.x), f.y);
}
vec3 A(vec2 uv){ return textureLod(texOut, clamp(uv, 0.0, 1.0), 0.0).rgb; }
vec3 B(vec2 uv){ return textureLod(texIn,  clamp(uv, 0.0, 1.0), 0.0).rgb; }
float reveal(float v, float p, float s){          // 1 where the incoming picture shows, sweeping with p
    s = max(s, 0.004);
    return clamp((p * (1.0 + s) - v) / s, 0.0, 1.0);
}
vec2 rot(vec2 q, float a){ float c = cos(a), s = sin(a); return vec2(c*q.x - s*q.y, s*q.x + c*q.y); }

vec3 transitionColor(vec2 uv){
    float asp = res.x / res.y;
    vec2 c = vec2(0.5);
    vec2 dir = vec2(cos(tAngle), sin(tAngle));
    float p = tP;
    float k = clamp(tPulse * tSens, 0.0, 1.5);          // how hard the beat hits right now
    float bz = clamp(tBass * tSens, 0.0, 1.5);
    float env = sin(p * 3.14159265);       // rhythm effects peak in the middle of the transition

    if (tType == 0) return mix(A(uv), B(uv), p);
    if (tType == 1) { return p < 0.5 ? A(uv) * (1.0 - 2.0*p) : B(uv) * (2.0*p - 1.0); }
    if (tType == 2) { return p < 0.5 ? mix(A(uv), vec3(1.0), 2.0*p) : mix(vec3(1.0), B(uv), 2.0*p - 1.0); }
    if (tType == 3) {
        float v = clamp(dot(uv - c, dir) / (abs(dir.x) + abs(dir.y)) + 0.5, 0.0, 1.0);
        return mix(A(uv), B(uv), reveal(v, p, tSoft));
    }
    if (tType == 4) {
        vec2 ua = uv - dir * p;
        if (all(greaterThanEqual(ua, vec2(0.0))) && all(lessThanEqual(ua, vec2(1.0)))) return A(ua);
        return B(uv + dir * (1.0 - p));
    }
    if (tType == 5) {
        float d = length((uv - c) * vec2(asp, 1.0)) / (0.5 * sqrt(asp*asp + 1.0));
        return mix(A(uv), B(uv), reveal(d, p, tSoft));
    }
    if (tType == 6) {
        vec2 q = (uv - c) * vec2(asp, 1.0);
        float a = fract(atan(q.y, q.x) / 6.2831853 + 0.25 - tAngle / 6.2831853);
        return mix(A(uv), B(uv), reveal(a, p, tSoft * 0.3));
    }
    if (tType == 7) {
        float z = 1.0 + tInt * 2.0 * p;
        float zb = 1.0 + tInt * 2.0 * (1.0 - p);
        return mix(A(c + (uv - c) / z), B(c + (uv - c) / zb), smoothstep(0.3, 0.7, p));
    }
    if (tType == 8) {
        float n = vnoise(uv * vec2(asp, 1.0) * (6.0 + tInt * 18.0));
        n = clamp((n - 0.15) / 0.7, 0.0, 1.0);
        return mix(A(uv), B(uv), reveal(n, p, max(tSoft, 0.06)));
    }
    if (tType == 9 || tType == 18) {
        float q = (tType == 9) ? sin(p * 3.14159265) : clamp(k, 0.0, 1.0) * env;
        float cells = mix(res.y, 6.0 + 50.0 / max(tInt, 0.25), q);
        vec2 g = vec2(cells * asp, cells);
        vec2 uq = (floor(uv * g) + 0.5) / g;
        return mix(A(uq), B(uq), smoothstep(0.4, 0.6, p));
    }
    if (tType == 10) {
        vec2 perp = vec2(-dir.y, dir.x);
        float f = fract(dot(uv, perp) * floor(5.0 + tInt * 10.0));
        return mix(A(uv), B(uv), reveal(f, p, tSoft * 0.5 + 0.02));
    }
    if (tType == 11) {
        vec2 q = (uv - c) * vec2(asp, 1.0);
        float r = length(q);
        float a = tInt * 5.0 * sin(p * 3.14159265) * (1.0 - clamp(r * 1.2, 0.0, 1.0));
        vec2 uvr = rot(q, a) / vec2(asp, 1.0) + c;
        return mix(A(uvr), B(uvr), smoothstep(0.25, 0.75, p));
    }
    if (tType == 12) {
        float z = 1.0 + 0.16 * tInt * k * env;
        vec2 uz = c + (uv - c) / z;
        return mix(A(uz), B(uz), p);
    }
    if (tType == 13) {
        vec3 col = mix(A(uv), B(uv), p);
        return mix(col, vec3(1.0), clamp(k * tInt * env * 0.85, 0.0, 1.0));
    }
    if (tType == 14) {
        float seed = floor(tTime * 30.0);
        vec2 off = (vec2(hash(vec2(seed, 1.0)), hash(vec2(seed, 2.0))) - 0.5) * 0.07 * tInt * k * env;
        vec2 sp = off * vec2(1.0, asp);
        vec3 a = vec3(A(uv + sp).r, A(uv).g, A(uv - sp).b);
        vec3 b = vec3(B(uv + sp).r, B(uv).g, B(uv - sp).b);
        return mix(a, b, p);
    }
    if (tType == 15) {
        float rows = 28.0;
        float row = floor(uv.y * rows);
        float step_t = floor(tTime * 14.0);
        float on = step(0.55, hash(vec2(row, step_t)));
        float sh = (hash(vec2(row, step_t + 7.0)) - 0.5) * 0.5 * tInt * clamp(k + 0.25 * bz, 0.0, 1.5) * env * on;
        vec2 uvs = uv + vec2(sh, 0.0);
        float m = reveal(hash(vec2(row, 3.0)), p, 0.25);
        vec3 a = vec3(A(uvs + vec2(0.01 * on * k, 0.0)).r, A(uvs).g, A(uvs - vec2(0.01 * on * k, 0.0)).b);
        vec3 b = vec3(B(uvs + vec2(0.01 * on * k, 0.0)).r, B(uvs).g, B(uvs - vec2(0.01 * on * k, 0.0)).b);
        return mix(a, b, m);
    }
    if (tType == 16) {
        vec2 q = (uv - c) * vec2(asp, 1.0);
        float d = length(q);
        vec2 n = q / max(d, 1e-4);
        float w = sin(d * 38.0 - tTime * 9.0) * 0.018 * tInt * clamp(bz * 0.6 + k, 0.0, 1.5) * env;
        vec2 uvr = uv + n * w / vec2(asp, 1.0);
        return mix(A(uvr), B(uvr), smoothstep(0.2, 0.8, p));
    }
    if (tType == 17) {
        float cell = (tBpm > 1.0) ? floor(tTime * tBpm / 60.0 * 2.0) : floor(tTime * 8.0);
        float showB = step(hash(vec2(cell, 11.0)), clamp(p * 1.15 - 0.02, 0.0, 1.0));
        vec3 col = mix(A(uv), B(uv), showB);
        return col * (1.0 + 0.5 * tInt * k * env);
    }
    // 19: kick spin
    {
        vec2 q = (uv - c) * vec2(asp, 1.0);
        float dirn = (p < 0.5) ? 1.0 : -1.0;
        float a = dirn * 0.7 * tInt * k * env;
        float z = 1.0 + 0.35 * abs(sin(a));
        vec2 uvr = rot(q, a) / z / vec2(asp, 1.0) + c;
        return mix(A(uvr), B(uvr), p);
    }
}
"""
