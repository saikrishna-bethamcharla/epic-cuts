# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for the single-file ``autocut`` executable.

Build from the repository root with the project (and its ``vad`` extra) already
installed:

    pyinstaller packaging/autocut.spec --noconfirm --distpath dist

The Silero VAD model is added beside the ``autocut`` package so detection works
without a download. FFmpeg is deliberately *not* bundled: it stays an external
program found on ``PATH`` (docs/DECISIONS.md, D32).
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parent
PACKAGE = ROOT / "src" / "autocut"
MODEL = PACKAGE / "analysis" / "models" / "silero_vad.onnx"

datas = [(str(MODEL), "autocut/analysis/models")]

a = Analysis(  # noqa: F821 - injected by PyInstaller
    [str(PACKAGE / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=collect_submodules("autocut"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "hypothesis", "mypy", "ruff"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821 - injected by PyInstaller

exe = EXE(  # noqa: F821 - injected by PyInstaller
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="autocut",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
