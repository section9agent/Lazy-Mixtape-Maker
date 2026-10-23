# PyInstaller spec - run from the project root:  pyinstaller packaging/lmm.spec --noconfirm
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
             hiddenimports=hidden + ["scipy.special._cdflib"], excludes=excludes)
pyz = PYZ(a.pure)
icon = str(ROOT / "packaging" / ("icon.ico" if sys.platform == "win32" else "icon.icns"))
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="LazyMixtapeMaker", console=False,
          icon=icon if sys.platform in ("win32", "darwin") else None)
coll = COLLECT(exe, a.binaries, a.datas, name="LazyMixtapeMaker")
if sys.platform == "darwin":
    app = BUNDLE(coll, name="Lazy Mixtape Maker.app", icon=icon, bundle_identifier="app.lazymixtapemaker",
                 info_plist={"NSHighResolutionCapable": True, "CFBundleDocumentTypes": [
                     {"CFBundleTypeName": "Lazy Mixtape session", "CFBundleTypeExtensions": ["lmm"], "CFBundleTypeRole": "Editor"}]})
