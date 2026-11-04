# PyInstaller spec - run from the project root:  pyinstaller packaging/lmm.spec --noconfirm
import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = Path(SPECPATH).parent
datas, binaries, hidden = [], [], []
for pkg in ("librosa", "imageio_ffmpeg", "soundfile", "miniaudio", "moderngl", "glcontext", "lazy_loader", "numba", "llvmlite"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hidden += h
    except Exception:
        pass
datas += [(str(ROOT / "lazy_mixtape_maker" / "assets"), "assets")]

# Only the Qt parts the app uses keep the download small.
excludes = ["tkinter", "matplotlib", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
            "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtPdf"]

a = Analysis([str(ROOT / "packaging" / "entry.py")], pathex=[str(ROOT)], binaries=binaries, datas=datas,
             hiddenimports=hidden + ["scipy.special._cdflib", "lazy_mixtape_maker.gui.studio_window", "lazy_mixtape_maker.studio"], excludes=excludes)
if sys.platform.startswith("linux"):
    # Use the computer's own graphics drivers and C++ runtime. Bundled (older) copies of these clash with the
    # newer Mesa on rolling distributions such as Arch / SteamOS, and then OpenGL is "not available".
    _SYSTEM = ("libstdc++.so", "libgcc_s.so", "libGL.so", "libGLX", "libEGL", "libGLdispatch", "libOpenGL.so",
               "libgbm.so", "libdrm", "libwayland-")
    a.binaries = [b for b in a.binaries if not os.path.basename(b[0]).startswith(_SYSTEM)]
pyz = PYZ(a.pure)
icon = str(ROOT / "packaging" / ("icon.ico" if sys.platform == "win32" else "icon.icns"))
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="LazyMixtapeMaker", console=False,
          icon=icon if sys.platform in ("win32", "darwin") else None)
coll = COLLECT(exe, a.binaries, a.datas, name="LazyMixtapeMaker")
if sys.platform == "darwin":
    app = BUNDLE(coll, name="Lazy Mixtape Maker.app", icon=icon, bundle_identifier="app.lazymixtapemaker",
                 info_plist={"NSHighResolutionCapable": True, "CFBundleDocumentTypes": [
                     {"CFBundleTypeName": "Lazy Mixtape session", "CFBundleTypeExtensions": ["lmm"], "CFBundleTypeRole": "Editor"},
                     {"CFBundleTypeName": "Lazy Mixtape visualization", "CFBundleTypeExtensions": ["lmv"], "CFBundleTypeRole": "Editor"}]})
