# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for 对稿 · PaperDiff (Windows x64 standalone onedir bundle).

Packaging design:
  - Strictly uses `onedir` (`exclude_binaries=True`) + `upx=False` to avoid
    onefile temp extraction latency and minimize antivirus false positives.
  - Packaged into both `Setup.exe` (Inno Setup) and `Portable.zip`.
"""
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

SPEC_DIR = Path(SPECPATH).resolve()
PAPERDIFF_ROOT = SPEC_DIR.parent
FRONTEND_DIST = PAPERDIFF_ROOT / "frontend" / "dist"
ICON_ICO = SPEC_DIR / "PaperDiff.ico"

datas = [
    (str(FRONTEND_DIST), "frontend/dist"),
]
KATEX_DIST = PAPERDIFF_ROOT / "frontend" / "node_modules" / "katex" / "dist"
if KATEX_DIST.exists():
    datas.append((str(KATEX_DIST), "katex"))

datas += collect_data_files("jieba")
datas += collect_data_files("docx")
datas += collect_data_files("webview")
datas += collect_data_files("pylatexenc")

binaries = []
for pkg in ("webview", "pythonnet", "clr_loader"):
    try:
        datas += collect_data_files(pkg)
    except Exception:
        pass
    try:
        binaries += collect_dynamic_libs(pkg)
    except Exception:
        pass

hiddenimports = [
    "backend",
    "backend.main",
    "backend.database",
    "backend.runtime_state",
    "backend.local_workspace",
    "backend.assets",
    "backend.parsers",
    "backend.parsers.ir",
    "backend.parsers.zones",
    "backend.parsers.omml",
    "backend.parsers.md_parser",
    "backend.parsers.latex_parser",
    "backend.parsers.docx_parser",
    "backend.patcher",
    "backend.patcher.latex_patcher",
    "backend.patcher.docx_patcher",
    "backend.patcher.md_patcher",
    "backend.export",
    "backend.export.html_print",
    "backend.export.pdf_exporter",
    "backend.omml",
    "backend.diff_engine",
    "backend.analyzer",
    "backend.exporter",
    "backend.sample_data",
    "markdown_it",
    "mdit_py_plugins",
    "pylatexenc",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "multipart",
    "python_multipart",
    "webview",
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
    "clr",
    "pythonnet",
    "clr_loader",
    "bottle",
    "proxy_tools",
]
hiddenimports += collect_submodules("uvicorn.protocols")
hiddenimports += collect_submodules("uvicorn.lifespan")
hiddenimports += collect_submodules("docx")
hiddenimports += collect_submodules("webview")
hiddenimports += collect_submodules("markdown_it")
hiddenimports += collect_submodules("mdit_py_plugins")
hiddenimports += collect_submodules("pylatexenc")
for opt_pkg in ("clr_loader", "pythonnet"):
    try:
        hiddenimports += collect_submodules(opt_pkg)
    except Exception:
        pass

excludes = [
    "tkinter",
    "matplotlib",
    "numpy",
    "scipy",
    "pandas",
    "pytest",
    "IPython",
    "notebook",
    "PyQt5",
    "PyQt6",
    "PySide6",
    "AppKit",
    "Foundation",
    "Cocoa",
    "WebKit",
    "Quartz",
    "objc",
]

a = Analysis(
    [str(PAPERDIFF_ROOT / "desktop_app.py")],
    pathex=[str(PAPERDIFF_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PaperDiff",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_ICO) if ICON_ICO.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PaperDiff",
)
