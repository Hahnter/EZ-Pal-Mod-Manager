# -*- mode: python ; coding: utf-8 -*-
"""One-file build of the desktop app.

Paths are relative to the project root so the spec works from a fresh clone.
The app writes nothing next to itself -- settings, registry, receipts and
profiles all live in %LOCALAPPDATA%\\PalModManager -- which matters here,
because a one-file build unpacks to a temp folder that is deleted on exit.
"""

import os

ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))

a = Analysis(
    [os.path.join(ROOT, 'palmods_gui.py')],
    pathex=[ROOT],                      # so palmods/palpaths/... resolve
    binaries=[],
    datas=[(os.path.join(ROOT, 'assets', 'palmodmanager.ico'), '.')],
    hiddenimports=['palmods', 'palpaths', 'palregistry', 'palinstall',
                   'palsafety', 'paltools', 'palui', 'palwindows',
                   'palmedia', 'palinfo', 'palicons', 'paltext', 'palget',
                   'PIL.ImageTk'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['numpy', 'pytest', 'setuptools', 'pip'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='EZPalModManager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[os.path.join(ROOT, 'assets', 'palmodmanager.ico')],
)
