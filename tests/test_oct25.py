"""Shader inputs (music on any channel, textures, video clips), editing, backup, sidecar analysis, totals."""
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LMM_AUDIO_BACKEND", "null")
sys.path.insert(0, str(Path(__file__).parent))
import synth  # noqa: E402

from lazy_mixtape_maker import audio_io  # noqa: E402
from lazy_mixtape_maker.visuals import ShaderLibrary, make_context, parse_shadertoy_json  # noqa: E402


def _need_gl():
    try:
        make_context().release()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"no OpenGL available: {e}")


@pytest.fixture()
def lib(tmp_path, monkeypatch):
    monkeypatch.setenv("LMM_DATA_DIR", str(tmp_path / "data"))
    return ShaderLibrary()


def _shadertoy_json(code, inputs, extra_passes=()):
    return json.dumps({"Shader": {"info": {"name": "T", "username": "u"}, "renderpass": [
        {"type": "image", "name": "Image", "code": code, "inputs": inputs, "outputs": []}, *extra_passes]}})


MUSIC1 = "void mainImage(out vec4 c,in vec2 p){ vec2 uv=p/iResolution.xy; float s=texture(iChannel1, vec2(uv.x*0.3,0.25)).x; c=vec4(vec3(s),1.0);}"


def _brightness(shader, audio, t):
    from lazy_mixtape_maker.video import AudioTexture, GLRenderer
    r = GLRenderer(96, 54, audio=AudioTexture(audio))
    try:
        r.update_audio(t)
        r.draw_shader(shader, t, 0, 0)
        return float(np.frombuffer(r.composite(0.0), np.uint8).mean())
    finally:
        r.release()


def test_music_on_any_channel_reacts(lib):
    _need_gl()
    sh = lib.add_from_text(_shadertoy_json(MUSIC1, [{"channel": 1, "ctype": "music", "id": "x"}]))
    assert sh.passes and sh.passes[-1]["inputs"] == {"1": "audio"}      # the channel isn't lost any more
    sr = 44100
    loud = np.random.default_rng(0).uniform(-.6, .6, (2, sr * 2)).astype(np.float32)
    quiet = np.zeros_like(loud)
    assert _brightness(sh, loud, 1.5) > _brightness(sh, quiet, 1.5) + 20


def test_shader_sound_is_muted_and_noted(lib):
    snd = {"type": "sound", "name": "Sound", "code": "vec2 mainSound(int s,float t){return vec2(sin(t*440.));}",
           "inputs": [], "outputs": []}
    name, _a, _c, warns, _p = parse_shadertoy_json(_shadertoy_json(MUSIC1, [], [snd]))
    assert any("own sound" in w and "muted" in w for w in warns)


def test_texture_and_video_inputs(lib, tmp_path):
    _need_gl()
    from PIL import Image
    from lazy_mixtape_maker.video import GLRenderer
    from lazy_mixtape_maker.visuals import add_media
    red = tmp_path / "red.png"
    Image.new("RGB", (16, 16), (255, 0, 0)).save(red)
    name = add_media(red)
    code = "void mainImage(out vec4 c,in vec2 p){ c = texture(iChannel2, p/iResolution.xy); }"
    sh = lib.add_from_text(_shadertoy_json(code, [{"channel": 2, "ctype": "texture", "filepath": f"/media/a/{name}"}]))
    assert sh.passes[-1]["inputs"] == {"2": f"texture:{name}"} and not sh.missing_media()
    r = GLRenderer(64, 36)
    try:
        r.draw_shader(sh, 0.0, 0, 0)
        px = np.frombuffer(r.composite(0.0), np.uint8).reshape(36, 64, 3)
    finally:
        r.release()
    assert px[..., 0].mean() > 200 and px[..., 1].mean() < 40
    # a clip that is missing is reported, not fatal
    sh2 = lib.add_from_text(_shadertoy_json(code, [{"channel": 0, "ctype": "video", "filepath": "/media/a/gone.webm"}]))
    assert sh2.missing_media() and sh2.missing_media()[0][2] == "video"
    # a real clip plays
    clip = tmp_path / "blue.mp4"
    subprocess.run([audio_io.ffmpeg(), "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=64x36:d=2:r=12", "-pix_fmt",
                    "yuv420p", str(clip)], check=True)
    vname = add_media(clip)
    code0 = code.replace("iChannel2", "iChannel0")
    sh3 = lib.add_from_text(_shadertoy_json(code0, [{"channel": 0, "ctype": "video", "filepath": f"/media/a/{vname}"}]))
    r = GLRenderer(64, 36)
    try:
        r.draw_shader(sh3, 0.5, 0, 0)
        px = np.frombuffer(r.composite(0.0), np.uint8).reshape(36, 64, 3)
    finally:
        r.release()
    assert px[..., 2].mean() > 150 and px[..., 0].mean() < 80


def test_edit_saved_shader_and_reject_bad_code(lib):
    _need_gl()
    from lazy_mixtape_maker.visuals import ShaderError
    sh = lib.add_from_text("void mainImage(out vec4 c,in vec2 p){ c=vec4(1.0,0.0,0.0,1.0);}", "Red")
    lib.update_code(sh.id, "void mainImage(out vec4 c,in vec2 p){ c=vec4(0.0,1.0,0.0,1.0);}")
    assert "0.0,1.0,0.0" in ShaderLibrary(lib.folder).get(sh.id).source             # persisted
    with pytest.raises(ShaderError):
        lib.update_code(sh.id, "void mainImage(out vec4 c,in vec2 p){ c = nope; }")
    assert "0.0,1.0,0.0" in lib.get(sh.id).source                                   # old version kept
    with pytest.raises(ValueError):
        lib.update_code("builtin:plasma", "x")


def test_backup_and_restore_everything(lib, tmp_path, monkeypatch):
    _need_gl()
    from PIL import Image
    from lazy_mixtape_maker.visuals import add_media
    png = tmp_path / "t.png"
    Image.new("RGB", (8, 8), (0, 255, 0)).save(png)
    n = add_media(png)
    code = "void mainImage(out vec4 c,in vec2 p){ c = texture(iChannel0, p/iResolution.xy); }"
    a = lib.add_from_text(_shadertoy_json(code, [{"channel": 0, "ctype": "texture", "filepath": f"/media/a/{n}"}]), "Tex")
    b = lib.add_from_text("void mainImage(out vec4 c,in vec2 p){ c=vec4(0.2);}", "Grey")
    f = tmp_path / "all.lmmshaders"
    assert lib.backup(f) == 2
    monkeypatch.setenv("LMM_DATA_DIR", str(tmp_path / "fresh"))        # a brand new computer
    fresh = ShaderLibrary()
    assert fresh.restore(f) == (2, 0)
    assert {s.name for s in fresh.all() if not s.builtin} == {"Tex", "Grey"}
    assert not fresh.get(a.id).missing_media()                           # the texture came with the backup
    assert fresh.restore(f) == (0, 2)                                     # importing twice adds nothing
    with pytest.raises(ValueError):
        (tmp_path / "x.json").write_text("{}")
        fresh.restore(tmp_path / "x.json")


def test_analysis_sidecar_file(tmp_path):
    from lazy_mixtape_maker import analysis
    p = tmp_path / "Band - a.wav"
    synth.make_song(p, 120, 9, True, structure=[("intro", 4), ("verse", 4), ("chorus", 4)], tags={"title": "a", "artist": "Band"})
    an = analysis.analyze_file(p, cache_dir=tmp_path / "c1")
    side = analysis.sidecar_path(p)
    assert side.exists() and side.name == "Band - a.wav.lmmanalysis"
    # a different (empty) cache and a decode that must not happen: the sidecar alone is enough
    orig = audio_io.decode
    audio_io.decode = lambda *a, **k: (_ for _ in ()).throw(AssertionError("re-analysed"))
    try:
        again = analysis.analyze_file(p, cache_dir=tmp_path / "c2")
    finally:
        audio_io.decode = orig
    assert again.id == an.id and abs(again.bpm - an.bpm) < 0.01 and again.wave == an.wave
    # a changed file isn't trusted
    with open(p, "ab") as f:
        f.write(b"\0" * 5000)
    assert analysis._sidecar_load(p, audio_io.file_id(p)) is None


def test_total_length_format():
    from lazy_mixtape_maker.gui.panels import fmt_hms
    assert fmt_hms(0) == "00:00:00" and fmt_hms(3725) == "01:02:05" and fmt_hms(59.6) == "00:01:00"


def test_export_both_renders_once(tmp_path, monkeypatch):
    _need_gl()
    monkeypatch.setenv("LMM_DATA_DIR", str(tmp_path / "data"))
    from lazy_mixtape_maker import render
    from lazy_mixtape_maker.engine import export_both, new_session
    from lazy_mixtape_maker.plan import MixSettings
    from lazy_mixtape_maker.video import VideoSettings
    d = tmp_path / "s"
    d.mkdir()
    for n, bpm, root in (("a", 120, 9), ("b", 124, 0)):
        synth.make_song(d / f"B - {n}.wav", bpm, root, True, structure=[("intro", 2), ("verse", 4), ("chorus", 4)],
                        tags={"title": n, "artist": "B"})
    s, _ = new_session(audio_io.list_audio_files([d]), MixSettings(seed=1, overlap_bars=2))
    calls = []
    orig = render.render_mix
    import lazy_mixtape_maker.engine as eng
    monkeypatch.setattr(eng, "render_mix", lambda *a, **k: (calls.append(1), orig(*a, **k))[1])
    monkeypatch.setattr(render, "render_mix", lambda *a, **k: (calls.append(1), orig(*a, **k))[1])
    vs = VideoSettings(width=96, height=54, fps=6, preset="ultrafast")
    res = export_both(s, tmp_path / "m.wav", tmp_path / "m.mp4", vs, ShaderLibrary())
    assert (tmp_path / "m.wav").exists() and (tmp_path / "m.mp4").stat().st_size > 1000 and (tmp_path / "m.cue").exists()
    assert len(calls) == 1 and res["video"].endswith("m.mp4")


# ------------------------------------------------------------------------------------------- GUI
def _gui_window(tmp_path, monkeypatch, n=3):
    monkeypatch.setenv("LMM_DATA_DIR", str(tmp_path / "data"))
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from lazy_mixtape_maker.engine import new_session
    from lazy_mixtape_maker.gui.main_window import MainWindow
    from lazy_mixtape_maker.plan import MixSettings
    from lazy_mixtape_maker.session import save_session
    d = tmp_path / "songs"
    d.mkdir()
    for k, (nm, bpm, root) in enumerate((("a", 120, 9), ("b", 122, 0), ("c", 121, 2))[:n]):
        synth.make_song(d / f"B - {nm}.wav", bpm, root, True, structure=[("intro", 8), ("verse", 8), ("chorus", 8)],
                        tags={"title": nm, "artist": "B"})
    s, _ = new_session(audio_io.list_audio_files([d]), MixSettings(seed=1, overlap_bars=8))
    save_session(s, tmp_path / "m.lmm")
    w = MainWindow()
    w.resize(1400, 700)
    w.show()
    w.load_session(tmp_path / "m.lmm")
    for _ in range(5):
        app.processEvents()
    return app, w, d


def test_waveform_shows_on_every_track_at_80_percent(tmp_path, monkeypatch):
    app, w, _d = _gui_window(tmp_path, monkeypatch)
    tl = w.timeline
    tl.set_zoom(8.0)
    img = tl.grab().toImage()
    _slots, rects = tl._rects()
    for i, r in enumerate(rects):
        vals = []
        for x in range(int(r.left()) + 10, int(r.right()) - 10, 2):
            for y in range(int(r.top()) + 4, int(r.bottom()) - 26, 2):
                c = img.pixelColor(x, y)
                vals.append((c.red() + c.green() + c.blue()) // 3)
        dark = [v for v in vals if v < 70]
        assert len(dark) > 0.05 * len(vals), f"track {i + 1} has no dark waveform"
        assert 12 < float(np.median(dark)) < 55, "waveform should be about 80% black, not solid black"
    w.state.dirty = False
    w.close()


def test_totals_label_and_folder_add_asks_for_options(tmp_path, monkeypatch):
    app, w, d = _gui_window(tmp_path, monkeypatch)
    assert "3 songs" in w.info.text() and "mix length 00:" in w.info.text()
    # a folder added to an empty mix shows the Generate dialog first, and its choices are used
    from lazy_mixtape_maker.gui import main_window as mw
    w.state.new()
    shown = []

    class FakeDlg:
        def __init__(self, settings, has_edits, parent=None):
            shown.append(settings)
        def exec(self):
            return True
        def result_settings(self):
            s = shown[0]
            s.overlap_bars = 4
            s.seed = 7
            return s
    monkeypatch.setattr(mw, "GenerateDialog", FakeDlg)
    w.run_task = lambda title, fn, done, *a, **k: done(fn(lambda *x: None, lambda: False))
    w.add_files([str(d)], ask_options=True)
    assert shown and w.state.plan.settings.overlap_bars == 4 and len(w.state.plan.tracks) == 3
    # cancelling the dialog adds nothing
    w.state.new()
    FakeDlg.exec = lambda self: False
    w.add_files([str(d)], ask_options=True)
    assert not w.state.plan.tracks
    w.state.dirty = False
    w.close()


def test_edit_dialog_saves_and_offers_the_texture(tmp_path, monkeypatch):
    _need_gl()
    monkeypatch.setenv("LMM_DATA_DIR", str(tmp_path / "data"))
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from lazy_mixtape_maker.gui.dialogs import EditShaderDialog
    lib = ShaderLibrary()
    code = "void mainImage(out vec4 c,in vec2 p){ c = texture(iChannel1, p/iResolution.xy); }"
    sh = lib.add_from_text(_shadertoy_json(code, [{"channel": 1, "ctype": "texture", "filepath": "/media/a/abc.jpg"}]), "Tex")
    assert sh.missing_media()
    dlg = EditShaderDialog(lib, sh)
    combo = dlg.image.combos[1]
    assert "abc.jpg" in combo.combo.currentText() and "file needed" in combo.combo.currentText()  # only what the code uses
    dlg.image.set_text(code.replace("c = texture", "c = 0.5 * texture"))
    dlg._save()
    assert dlg.saved and "0.5 *" in lib.get(sh.id).source
    assert lib.get(sh.id).passes[-1]["inputs"]["1"] == "texture:abc.jpg"                   # the input survived the edit
    bad = EditShaderDialog(lib, lib.get(sh.id))
    bad.image.set_text("void mainImage(out vec4 c,in vec2 p){ c = oops; }")
    bad._save()
    assert not bad.saved and "Not saved" in bad.msg.text()
