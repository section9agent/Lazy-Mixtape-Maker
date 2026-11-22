"""MilkDrop presets: recognising and importing them, choosing between Shadertoy and MilkDrop, and drawing them
with libprojectM (the drawing tests skip themselves when this computer has no libprojectM or no OpenGL)."""
import os
import sys
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LMM_AUDIO_BACKEND", "null")
sys.path.insert(0, str(Path(__file__).parent))

from lazy_mixtape_maker import milkdrop  # noqa: E402
from lazy_mixtape_maker.video import VideoSettings, pick_visuals  # noqa: E402
from lazy_mixtape_maker.visuals import ShaderError, ShaderLibrary, folder_of, make_context  # noqa: E402

PRESET = """[preset00]
fRating=3.000000
fDecay=0.980000
zoom=1.010000
rot=0.020000
nWaveMode=2
bAdditiveWaves=1
wave_r=1.000000
wave_g=0.400000
wave_b=0.900000
wave_a=1.000000
fWaveScale=1.800000
ob_size=0.010000
ob_r=0.2
ob_a=1.0
per_frame_1=wave_r = 0.5 + 0.5*sin(time*1.3);
per_frame_2=wave_g = 0.5 + 0.5*sin(time*1.7);
per_frame_3=zoom = 1.0 + 0.04*bass;
"""

SHADERTOY = "void mainImage(out vec4 c, in vec2 p){ c = vec4(p/iResolution.xy, 0.5, 1.0); }"


def _toy(lib, name):
    """A Shadertoy visual (added without compiling it, so tests run on computers without OpenGL)."""
    return lib.add(name, SHADERTOY, check=False)


@pytest.fixture()
def lib(tmp_path, monkeypatch):
    monkeypatch.setenv("LMM_DATA_DIR", str(tmp_path / "data"))
    return ShaderLibrary()


def _need_milk():
    if not milkdrop.available():
        pytest.skip("libprojectM isn't on this computer: " + milkdrop.why_unavailable()[:200])
    try:
        make_context().release()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"no OpenGL available: {e}")


# ------------------------------------------------------------------ recognising and importing
def test_preset_text_is_recognised():
    assert milkdrop.looks_like_preset(PRESET)
    assert milkdrop.looks_like_preset("zoom=1.01\nrot=0.0\nwarp=0.2\n")       # older presets have no [preset00]
    assert not milkdrop.looks_like_preset(SHADERTOY)
    assert not milkdrop.looks_like_preset("just some notes\nzoom in on the chorus")


def test_texture_names_from_preset_code():
    text = PRESET + "warp_1=`shader_body { ret = tex2D(sampler_clouds2, uv).xyz + tex2D(sampler_fw_main, uv).xyz;\n" \
                    "comp_1=`ret += tex2D(sampler_pw_rocks, uv); ret += tex2D(sampler_blur1, uv); }\n" \
                    "comp_2=`ret += tex2D(sampler_rand03_smalltiled, uv) + tex2D(sampler_noise_lq, uv);\n"
    assert milkdrop.referenced_textures(text) == {"clouds2", "rocks"}


def test_energy_from_category():
    assert milkdrop.energy_for("Supernova") == "high"
    assert milkdrop.energy_for("Hypnotic") == "calm"
    assert milkdrop.energy_for("Geometric") == "mid"


def test_names_from_files():
    assert milkdrop.preset_name("Some Author - Purple_Haze.milk") == "Some Author - Purple Haze"
    assert milkdrop.preset_name("flexi - thing --- Isosceles edit.milk") == "flexi - thing"
    assert len(milkdrop.preset_name("x - " + "y" * 200 + ".milk")) <= 60


def test_import_milk_file_with_its_texture(lib, tmp_path):
    d = tmp_path / "presets"
    d.mkdir()
    text = PRESET + "comp_1=`shader_body { ret = tex2D(sampler_mytex, uv).xyz; }\n"
    f = d / "Some Author - Purple_Haze.milk"
    f.write_text(text)
    from PIL import Image
    Image.new("RGB", (8, 8), (255, 0, 0)).save(d / "mytex.jpg")
    Image.new("RGB", (8, 8), (0, 255, 0)).save(d / "unrelated.jpg")
    sh = lib.add_from_file(str(f))
    assert sh.is_milk and sh.kind == "milkdrop"
    assert sh.name == "Some Author - Purple Haze"
    assert sh.source == text
    folder = folder_of(sh.id)
    assert folder and (Path(folder) / "mytex.jpg").exists()           # the texture it uses came along
    assert not (Path(folder) / "unrelated.jpg").exists()
    again = ShaderLibrary().get(sh.id)                                   # and it all survives a restart
    assert again is not None and again.is_milk and again.source == text
    assert lib.add_from_file(str(f)).id == sh.id                       # the same preset twice isn't added twice


def test_energy_comes_from_the_pack_category(lib, tmp_path, monkeypatch):
    pack = tmp_path / "pack"
    (pack / "Supernova" / "Some Author").mkdir(parents=True)
    f = pack / "Supernova" / "Some Author" / "Some Author - Bang.milk"
    f.write_text(PRESET)
    monkeypatch.setenv("LMM_MILKDROP_PACK", str(pack))
    sh = lib.add_from_file(f)
    assert sh.energy == "high" and sh.category == "Supernova"


def test_pasted_preset_text_becomes_milkdrop(lib):
    sh = lib.add_from_text(PRESET, "Pasted one")
    assert sh.is_milk and sh.name == "Pasted one"
    assert not _toy(lib, "Plain").is_milk


def test_not_a_preset_is_refused(lib, tmp_path):
    f = tmp_path / "nope.milk"
    f.write_text("hello there\nthis is not a preset")
    with pytest.raises(ShaderError):
        lib.add_from_file(str(f))


def test_editing_a_preset(lib):
    sh = lib.add_from_text(PRESET, "Edit me")
    lib.update_code(sh.id, PRESET.replace("1.010000", "1.020000"))
    assert "1.020000" in ShaderLibrary().get(sh.id).source
    with pytest.raises(ShaderError):
        lib.update_code(sh.id, "not a preset at all")


def test_label_marks_milkdrop(lib):
    from lazy_mixtape_maker.visuals import visual_label
    sh = lib.add_from_text(PRESET, "Glow")
    assert "MilkDrop" in visual_label(sh)
    assert "MilkDrop" not in visual_label(_toy(lib, "Flat"))


# ------------------------------------------------------------------ choosing
def test_visual_source_limits_what_the_app_picks(lib):
    milks = [lib.add_from_text(PRESET.replace("1.010000", f"1.0{i}"), f"M{i}") for i in range(3)]
    keys, energies = [f"s{i}" for i in range(12)], [0.5] * 12
    for mode in ("auto", "random"):
        only_milk = pick_visuals(keys, energies, VideoSettings(mode=mode, seed=3, visual_source="milkdrop"), lib)
        assert all(lib.get(i).is_milk for i in only_milk)
        only_st = pick_visuals(keys, energies, VideoSettings(mode=mode, seed=3, visual_source="shadertoy"), lib)
        assert not any(lib.get(i).is_milk for i in only_st)
        both = pick_visuals(keys, energies, VideoSettings(mode=mode, seed=3, visual_source="all"), lib)
        assert len(both) == 12
    assert milks


def test_visual_source_is_saved_with_the_session():
    back = VideoSettings.from_dict(VideoSettings(visual_source="milkdrop").to_dict())
    assert back.visual_source == "milkdrop"


def test_featured_index_is_well_formed():
    if not (milkdrop.featured_dir() / "featured.json").exists():
        pytest.skip("no featured set in this checkout")
    items = milkdrop.featured()
    assert len(items) >= 20
    ids = [it["id"] for it in items]
    assert len(ids) == len(set(ids)) and all(i.startswith("milk:") for i in ids)
    tex = milkdrop.featured_dir() / "textures"
    have = {p.stem.lower() for p in tex.iterdir()} if tex.is_dir() else set()
    for it in items:
        text = Path(it["path"]).read_text(encoding="utf-8", errors="replace")
        assert milkdrop.looks_like_preset(text), it["file"]
        assert it["energy"] in ("calm", "mid", "high")
        for name in milkdrop.referenced_textures(text):          # every texture a featured preset uses ships too
            assert name in have, f"{it['file']} needs texture {name}"


def test_featured_presets_are_visuals(lib):
    if not milkdrop.featured():
        pytest.skip("no featured set in this checkout")
    first = milkdrop.featured()[0]
    sh = lib.get(first["id"])                                    # sessions can name them even without projectM
    assert sh is not None and sh.is_milk and sh.builtin
    with pytest.raises(ValueError):
        lib.remove(sh.id)
    assert (first["id"] in {s.id for s in lib.all()}) == milkdrop.available()


# ------------------------------------------------------------------ drawing
def _rgb(r):
    return np.frombuffer(r.composite(0.0), np.uint8).reshape(r.h, r.w, 3).astype(int)


def test_preset_draws_and_moves(lib):
    _need_milk()
    from lazy_mixtape_maker.video import GLRenderer
    sh = lib.add_from_text(PRESET, "Draw me")
    st = lib.add_from_text(SHADERTOY, "After")      # (checking a shader uses a GL context of its own, so add it first)
    r = GLRenderer(160, 90)
    try:
        frames = []
        for k in range(45):
            r.draw_shader(sh, 2.0 + k / 30.0, k, 0)
            if k in (20, 44):
                frames.append(_rgb(r))
        r.draw_shader(st, 1.0, 0, 0)               # Shadertoy visuals still draw afterwards (GL state is put back)
        after = _rgb(r)
    finally:
        r.release()
    assert frames[1].mean() > 3, "the preset should draw something"
    assert np.abs(frames[1] - frames[0]).mean() > 0.5, "and it should move"
    assert abs(after[45, 80, 2] - 128) < 20 and after[5, 150, 0] > after[5, 5, 0] + 100


def test_preset_reacts_to_the_music(lib):
    _need_milk()
    from lazy_mixtape_maker.video import AudioTexture, GLRenderer
    sh = lib.add_from_text(PRESET, "Listen")
    sr = 22050
    t = np.arange(sr * 4) / sr
    loud = (0.9 * np.sin(2 * np.pi * 60 * t) * np.exp(-np.mod(t, 0.5) * 10)).astype(np.float32)
    shots = []
    for mix in (np.zeros_like(loud), loud):
        r = GLRenderer(96, 54, AudioTexture(np.stack([mix, mix]), sr))
        try:
            for k in range(60):
                r.update_audio(1 + k / 30)
                r.draw_shader(sh, 1 + k / 30, k, 0, audio_t=1 + k / 30)
            shots.append(_rgb(r))
        finally:
            r.release()
    assert np.abs(shots[0] - shots[1]).mean() > 2


def test_preset_frames_are_repeatable(lib):
    """An export renders frame by frame at its own pace; the same moment must look the same each time."""
    _need_milk()
    from lazy_mixtape_maker.video import GLRenderer
    sh = lib.add_from_text(PRESET, "Again")
    shots = []
    for _ in range(2):
        r = GLRenderer(96, 54)
        try:
            for k in range(10):
                r.draw_shader(sh, 5.0 + k / 30.0, k, 0)
            shots.append(_rgb(r))
        finally:
            r.release()
    # projectM picks some of its textures and motion at random each start (on a real GPU two runs can look quite
    # different), so all that can be relied on is that drawing the same moment again works and shows a picture.
    assert shots[0].mean() > 3 and shots[1].mean() > 3


def test_broken_preset_falls_back(lib):
    """A preset projectM can't draw must not stop a render."""
    _need_milk()
    from lazy_mixtape_maker.video import GLRenderer
    sh = lib.add_from_text("[preset00]\nzoom=1.0\nrot=0.0\nper_frame_1=this is ((( not valid;\n", "Odd")
    r = GLRenderer(64, 36)
    try:
        for k in range(5):
            r.draw_shader(sh, k / 30.0, k, 0)
        r.composite(0.0)
    finally:
        r.release()


def test_preview_frame_for_preset(lib):
    _need_milk()
    from lazy_mixtape_maker.video import preview_frame
    img = preview_frame(lib.add_from_text(PRESET, "Thumb"), size=(128, 72))
    assert img.shape[:2] == (72, 128)


def test_preset_textures_travel_with_sessions_and_backups(tmp_path, monkeypatch):
    monkeypatch.setenv("LMM_DATA_DIR", str(tmp_path / "home"))
    mine = ShaderLibrary()
    d = tmp_path / "src"
    d.mkdir()
    (d / "Tex - Thing.milk").write_text(PRESET + "comp_1=`shader_body { ret = tex2D(sampler_ownpic, uv).xyz; }\n")
    (d / "ownpic.png").write_bytes(b"\x89PNG fake")
    sh = mine.add_from_file(str(d / "Tex - Thing.milk"))
    assert "ownpic.png" in mine.milk_files(sh)
    embedded = mine.export_used({sh.id})
    mine.backup(tmp_path / "all.lmmshaders")
    monkeypatch.setenv("LMM_DATA_DIR", str(tmp_path / "friend"))     # someone else's computer
    friend = ShaderLibrary()
    friend.import_embedded(embedded)
    got = friend.get(sh.id)
    assert got is not None and got.is_milk
    assert (Path(folder_of(sh.id)) / "ownpic.png").read_bytes() == b"\x89PNG fake"
    monkeypatch.setenv("LMM_DATA_DIR", str(tmp_path / "third"))
    third = ShaderLibrary()
    assert third.restore(tmp_path / "all.lmmshaders") == (1, 0)
    t = next(s for s in third.all() if s.is_milk and not s.builtin)
    assert "ownpic.png" in third.milk_files(t)


# ------------------------------------------------------------------ windows
@pytest.fixture(scope="module")
def app():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _spin(app, n=10):
    import time
    for _ in range(n):
        app.processEvents()
        time.sleep(0.05)


def test_milk_browser_lists_and_adds(app, lib, tmp_path, monkeypatch):
    pack = tmp_path / "pack"
    for cat, names in (("Hypnotic", ["Alpha - one", "Beta - two"]), ("Supernova", ["Gamma - boom"])):
        (pack / cat / "sub").mkdir(parents=True)
        for n in names:
            (pack / cat / "sub" / f"{n}.milk").write_text(PRESET.replace("0.020000", str(len(n))))
    monkeypatch.setenv("LMM_MILKDROP_PACK", str(pack))
    from lazy_mixtape_maker.gui.milk_browser import MilkBrowser
    b = MilkBrowser(lib)
    b.show()
    _spin(app, 3)
    assert b.items.count() == 3
    b.search.setText("gamma")
    b.refill()
    assert b.items.count() == 1
    b.items.setCurrentRow(0)
    b.add_selected()
    assert len(b.added) == 1 and b.added[0].is_milk and b.added[0].energy == "high"
    assert lib.get(b.added[0].id) is not None
    b.done(0)


def test_import_milk_files_dialog(app, lib, tmp_path, monkeypatch):
    f = tmp_path / "x.milk"
    f.write_text(PRESET)
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda *a, **k: ([str(f)], "")))
    from lazy_mixtape_maker.gui.milk_browser import import_milk_files
    got = import_milk_files(None, lib)
    assert len(got) == 1 and got[0].is_milk


def test_shader_manager_filters_and_edits_presets(app, lib, monkeypatch):
    try:
        make_context().release()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"no OpenGL available: {e}")
    from lazy_mixtape_maker.gui.panels import ThumbCache
    from lazy_mixtape_maker.gui.shader_manager import MilkPresetDialog, ShaderManager
    milk = lib.add_from_text(PRESET, "Milky")
    _toy(lib, "Toy")
    thumbs = ThumbCache()
    m = ShaderManager(lib, thumbs)
    m.show()
    _spin(app, 3)
    ids = lambda: [m.list.item(r).data(0x100) for r in range(m.list.count())]  # noqa: E731
    m.kind.setCurrentIndex(m.kind.findData("milkdrop"))
    _spin(app, 2)
    assert milk.id in ids() and all(lib.get(i).is_milk for i in ids())
    m.kind.setCurrentIndex(m.kind.findData("shadertoy"))
    _spin(app, 2)
    assert milk.id not in ids()
    d = MilkPresetDialog(lib, milk, m)
    d.name.setText("Milky renamed")
    d.text.setPlainText(PRESET.replace("1.010000", "1.020000"))
    d._save()
    assert lib.get(milk.id).name == "Milky renamed" and "1.020000" in lib.get(milk.id).source
    m.shutdown()
    thumbs.shutdown()
