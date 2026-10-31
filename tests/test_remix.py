import os
import sys

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LMM_AUDIO_BACKEND", "null")
sys.path.insert(0, os.path.dirname(__file__))

from lazy_mixtape_maker import remix as rmx  # noqa: E402
from lazy_mixtape_maker.visuals import ShaderLibrary, make_context  # noqa: E402

STATIC = ("void mainImage(out vec4 c, in vec2 p){ vec2 uv = p / iResolution.xy; "
          "float d = length(uv - 0.5); c = vec4(vec3(smoothstep(0.35, 0.30, d)) * vec3(0.9, 0.5, 0.2), 1.0); }")
PASSES = [{"name": "Buffer A", "type": "buffer", "code": "void mainImage(out vec4 c, in vec2 p){ c = vec4(0.2); }", "inputs": {}},
          {"name": "Image", "type": "image", "inputs": {"0": "buffer:A", "1": "noise", "2": "noise", "3": "noise"},
           "code": "void mainImage(out vec4 c, in vec2 p){ c = texture(iChannel0, p / iResolution.xy) + 0.3 * sin(iTime); }"}]


def _need_gl():
    try:
        make_context().release()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"no OpenGL available: {e}")


@pytest.fixture()
def lib(tmp_path, monkeypatch):
    monkeypatch.setenv("LMM_DATA_DIR", str(tmp_path / "data"))
    return ShaderLibrary()


def _frame(shader, audio, t=1.0, size=(96, 54)):
    from lazy_mixtape_maker.video import AudioTexture, GLRenderer
    r = GLRenderer(*size, audio=AudioTexture(audio, 11025))
    try:
        for tt in (t - 0.06, t - 0.04, t - 0.02, t):        # the spectrum is smoothed over a few frames, as in a video
            r.update_audio(max(tt, 0.0))
        r.draw_shader(shader, t, 0, 0)
        return np.frombuffer(r.composite(0.0), np.uint8).reshape(size[1], size[0], 3).astype(float)
    finally:
        r.release()


def test_reacts_to_audio_detection(lib):
    from lazy_mixtape_maker.visuals import BUILTIN, Shader
    assert not rmx.reacts_to_audio(Shader(id="a", name="a", source=STATIC))
    assert rmx.reacts_to_audio(Shader(id="b", name="b", source=STATIC.replace("uv - 0.5", "uv - texture(iChannel0, uv).x")))
    sh = Shader(id="c", name="c", source="", passes=PASSES)
    assert not rmx.reacts_to_audio(sh)
    src, passes = rmx.apply("", PASSES, rmx.default_spec("club"))
    assert rmx.reacts_to_audio(Shader(id="d", name="d", source=src, passes=passes))
    assert passes[1]["inputs"]["0"] == "buffer:A" and "audio" in passes[1]["inputs"].values()    # a free channel was used
    assert any(rmx.reacts_to_audio(b) for b in BUILTIN.values())


def test_apply_keeps_the_original_and_reports_problems():
    src, p = rmx.apply(STATIC, [], rmx.default_spec("wild"))
    assert p == [] and "lmm_base_mainImage" in src and src.count("void mainImage") == 1
    with pytest.raises(rmx.RemixError):
        rmx.apply("float f(){return 1.0;}", [], None)
    full = [{"name": "Image", "type": "image", "code": "void mainImage(out vec4 c,in vec2 p){c=texture(iChannel0,p)+texture(iChannel1,p)+texture(iChannel2,p)+texture(iChannel3,p);}",
             "inputs": {"0": "noise", "1": "noise", "2": "noise", "3": "noise"}}]
    with pytest.raises(rmx.RemixError):
        rmx.apply("", full, None)
    spec = rmx.normalize_spec({"mods": {"zoom": {"on": True, "amount": 9, "band": "nope"}}, "gain": 99})
    assert spec["mods"]["zoom"]["amount"] == 2.0 and spec["mods"]["zoom"]["band"] == "bass" and spec["gain"] == 3.0
    assert not spec["mods"]["flash"]["on"]


@pytest.mark.parametrize("which", ["plain", "multipass"])
def test_a_remix_moves_with_the_music_and_the_original_does_not(lib, which):
    _need_gl()
    from lazy_mixtape_maker.gui.remix_studio import beat_loop
    from lazy_mixtape_maker.visuals import Shader
    if which == "plain":
        base = lib.add_from_text(STATIC, "Static dot")
    else:
        base = lib.add("Multi", "void mainImage(out vec4 c, in vec2 p){ c = vec4(1.0); }", passes=PASSES)
    assert not rmx.reacts_to_audio(base)
    spec = rmx.default_spec("club")
    spec["gain"] = 2.0
    rem = lib.add_remix(base, spec)
    assert rem.origin == "remix" and rem.name.endswith("(remix)") and rem.remix["base"]["source"] == base.source
    assert rmx.reacts_to_audio(rem)
    loud = beat_loop()
    quiet = np.zeros_like(loud)
    # at 0.0 s of the loop a kick has just started (loud); with silence nothing moves
    d_orig = np.abs(_frame(base, loud, 0.1) - _frame(base, quiet, 0.1)).mean()
    d_rem = np.abs(_frame(rem, loud, 0.1) - _frame(rem, quiet, 0.1)).mean()
    assert d_rem > d_orig + 2.0, (d_orig, d_rem)
    # remixing a remix starts from the original code, not a stack of wrappers
    again = lib.add_remix(rem, rmx.default_spec("gentle"), "Calmer")
    assert again.remix["base"]["source"] == base.source and again.source.count("lmm_base_mainImage(") <= 4
    # re-tuning updates it in place and survives a reload
    spec2 = rmx.default_spec("wild")
    upd = lib.update_remix(rem.id, spec2, "Renamed")
    assert upd.id == rem.id and upd.name == "Renamed" and upd.remix["spec"]["mods"]["kaleido"]["on"]
    assert ShaderLibrary().get(rem.id).remix["spec"]["mods"]["kaleido"]["on"]
    # editing the code by hand drops the remix link
    lib.update_code(rem.id, upd.source, upd.passes)
    assert lib.get(rem.id).remix == {}


def test_remix_studio_dialog(lib, tmp_path):
    _need_gl()
    import time
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from lazy_mixtape_maker.gui.remix_studio import RemixStudio
    base = lib.add_from_text(STATIC, "Dot")
    dlg = RemixStudio(lib, base)
    dlg.show()
    got = []
    dlg.worker.frame.connect(lambda img, tag: got.append(img) if tag == "remix" else None)
    try:
        end = time.time() + 30
        while time.time() < end and len(got) < 3:
            app.processEvents(); time.sleep(0.02)
        assert len(got) >= 3 and got[-1].width() == 400
        assert not dlg.rows["kaleido"][0].isChecked() and dlg.rows["zoom"][0].isChecked()      # the Club preset
        dlg.preset.setCurrentIndex(dlg.preset.findData("off")); dlg._preset(0)
        dlg._save(False)
        assert dlg.saved is None and "at least one effect" in dlg.msg.text()
        dlg.rows["flash"][0].setChecked(True)
        dlg.name.setText("My dot remix")
        dlg._save(False)
        assert dlg.saved is not None and dlg.saved.name == "My dot remix" and lib.get(dlg.saved.id).remix
    finally:
        dlg.reject()
