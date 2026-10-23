import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
import synth  # noqa: E402

from lazy_mixtape_maker import audio_io  # noqa: E402
from lazy_mixtape_maker.engine import new_session  # noqa: E402
from lazy_mixtape_maker.plan import MixSettings  # noqa: E402
from lazy_mixtape_maker.session import load_session, save_session  # noqa: E402
from lazy_mixtape_maker.video import VideoSettings, attach_to_session, render_video, restore_from_session  # noqa: E402
from lazy_mixtape_maker.visuals import ShaderError, ShaderLibrary, make_context  # noqa: E402

TINY = [("intro", 2), ("verse", 4), ("chorus", 4), ("outro", 2)]
GOOD = """void mainImage(out vec4 fragColor, in vec2 fragCoord){
  vec2 uv = fragCoord/iResolution.xy;
  fragColor = vec4(uv, 0.5+0.5*sin(iTime), 1.0);
}"""


@pytest.fixture(scope="module", autouse=True)
def need_gl():
    try:
        make_context().release()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"no OpenGL available: {e}")


@pytest.fixture()
def lib(tmp_path, monkeypatch):
    monkeypatch.setenv("LMM_DATA_DIR", str(tmp_path / "data"))
    return ShaderLibrary()


@pytest.fixture(scope="module")
def session(tmp_path_factory):
    d = tmp_path_factory.mktemp("vsongs")
    for n, bpm, root in (("a", 120, 9), ("b", 126, 0)):
        synth.make_song(d / f"Band - {n}.wav", bpm, root, True, structure=TINY, tags={"title": n, "artist": "Band"})
    s, errs = new_session(audio_io.list_audio_files([d]), MixSettings(seed=1, overlap_bars=2), name="v")
    assert not errs
    return s


def test_shader_import_paste_json_and_persist(lib, tmp_path, monkeypatch):
    sh = lib.add_from_text(GOOD, "My shader")
    assert sh.id in {s.id for s in lib.all()}
    js = json.dumps({"Shader": {"info": {"name": "From JSON", "username": "me"},
                                "renderpass": [{"type": "image", "code": GOOD, "inputs": []}]}})
    sj = lib.add_from_text(js)
    assert sj.name == "From JSON"
    # stored for later: a brand-new library object (as after restarting the app) still has them
    again = ShaderLibrary()
    assert {sh.id, sj.id} <= {s.id for s in again.all()}


def test_bad_shader_is_rejected(lib):
    with pytest.raises(ShaderError):
        lib.add_from_text("void mainImage(out vec4 c, in vec2 p){ c = nonsense; }", "bad")


def test_shaders_travel_inside_session(lib, session, tmp_path, monkeypatch):
    sh = lib.add_from_text(GOOD, "Shared")
    vs = VideoSettings(mode="single", single_shader=sh.id)
    attach_to_session(session, vs, lib)
    f = tmp_path / "s.lmm"
    save_session(session, f)
    monkeypatch.setenv("LMM_DATA_DIR", str(tmp_path / "friend"))   # a friend's computer
    friend = ShaderLibrary()
    assert friend.get(sh.id) is None
    s2 = load_session(f)
    vs2 = restore_from_session(s2, friend)
    assert vs2.mode == "single" and friend.get(sh.id) is not None


@pytest.mark.parametrize("mode", ["auto", "random", "single"])
def test_video_modes(mode, lib, session, tmp_path):
    sh = lib.add_from_text(GOOD, "Mine")
    vs = VideoSettings(mode=mode, single_shader=sh.id, width=320, height=180, fps=10, crf=32, preset="ultrafast")
    out = tmp_path / f"{mode}.mp4"
    res = render_video(session.plan, session.library, session.paths, out, vs, lib)
    assert out.exists() and not res["warnings"]
    info = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(out)],
        capture_output=True, text=True).stdout or "{}")
    if info:
        kinds = {s["codec_name"] for s in info["streams"]}
        assert {"h264", "aac"} <= kinds
    if mode == "single":
        assert set(res["visuals"]) == {"Mine"}


def test_overlay_in_lower_left(lib, session, tmp_path):
    out = {}
    for overlay in (True, False):
        vs = VideoSettings(mode="single", single_shader="builtin:plasma", width=320, height=180, fps=10,
                           crf=18, preset="ultrafast", show_overlay=overlay)
        f = tmp_path / f"o{overlay}.mp4"
        render_video(session.plan, session.library, session.paths, f, vs, lib)
        raw = subprocess.run([audio_io.ffmpeg(), "-v", "error", "-ss", "5", "-i", str(f), "-frames:v", "1",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        out[overlay] = np.frombuffer(raw, np.uint8).reshape(180, 320, 3).astype(float)
    diff = np.abs(out[True] - out[False]).sum(axis=2)
    ys, xs = np.nonzero(diff > 40)
    assert len(ys) > 200, "the cover/artist/title card is missing"
    assert ys.mean() > 180 * 0.6 and xs.mean() < 320 * 0.5, "the card should sit in the lower left"


BUF_A = """void mainImage(out vec4 O, in vec2 F){
  vec2 uv = F/iResolution.xy;
  vec4 prev = texture(iChannel0, uv);
  vec2 p = vec2(0.5 + 0.35*cos(iTime*3.0), 0.5 + 0.35*sin(iTime*3.0));
  float dot_ = smoothstep(0.04, 0.02, length((uv-p)*vec2(iResolution.x/iResolution.y,1.0)));
  O = vec4(max(prev.rgb*0.97, vec3(dot_)), 1.0);
}"""
IMG = """void mainImage(out vec4 O, in vec2 F){ O = vec4(texture(iChannel0, F/iResolution.xy).rgb, 1.0); }"""


def _multipass_json():
    return json.dumps({"Shader": {"info": {"name": "Trails", "username": "t"}, "renderpass": [
        {"type": "buffer", "name": "Buffer A", "code": BUF_A,
         "inputs": [{"channel": 0, "ctype": "buffer", "id": "bufA"}], "outputs": [{"id": "bufA", "channel": 0}]},
        {"type": "image", "name": "Image", "code": IMG,
         "inputs": [{"channel": 0, "ctype": "buffer", "id": "bufA"}], "outputs": []}]}})


def test_multipass_buffers_feed_back(lib):
    from lazy_mixtape_maker.video import GLRenderer
    sh = lib.add_from_text(_multipass_json())
    assert len(sh.passes) == 2 and not sh.warnings
    r = GLRenderer(160, 90)
    try:
        for k in range(40):
            r.draw_shader(sh, k / 20.0, k, 0)
        raw = np.frombuffer(r.composite(0.0), np.uint8).reshape(90, 160, 3)
    finally:
        r.release()
    lit = (raw.max(axis=2) > 30).sum()
    assert lit > 150, "buffer feedback should leave a trail of earlier dot positions"


def test_cover_art_is_used(lib, session, tmp_path):
    from lazy_mixtape_maker.video import make_card
    from PIL import Image
    cover = tmp_path / "c.png"
    Image.new("RGB", (64, 64), (250, 10, 10)).save(cover)
    card = make_card("Artist", "Title", str(cover), 360, 400)
    px = np.array(card)
    assert ((px[..., 0] > 200) & (px[..., 1] < 60) & (px[..., 3] > 200)).sum() > 500
