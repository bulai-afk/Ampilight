# -*- mode: python ; coding: utf-8 -*-
"""Самостоятельное приложение: Python и библиотеки внутри Hyperion.app."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).resolve().parent
icon = root / "Hyperion.app" / "Contents" / "Resources" / "AppIcon.icns"

qt_datas, qt_binaries, qt_hidden = collect_all("PyQt6")
np_datas, np_binaries, np_hidden = collect_all("numpy")

a = Analysis(
    [str(root / "app" / "hyperion_app.py")],
    pathex=[str(root)],
    binaries=qt_binaries + np_binaries,
    datas=qt_datas + np_datas,
    hiddenimports=qt_hidden
    + np_hidden
    + [
        "app.desk_screen",
        "app.sck",
        "app.discover",
        "app.sender",
        "app.hyperion",
        "app.hyperion_window",
        "app.glass",
        "app.search_page",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Hyperion",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Hyperion",
)
app = BUNDLE(
    coll,
    name="Hyperion.app",
    icon=str(icon) if icon.is_file() else None,
    bundle_identifier="com.ampilight.hyperion.lan",
    info_plist={
        "CFBundleName": "Hyperion",
        "CFBundleDisplayName": "Hyperion",
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        "NSScreenCaptureUsageDescription": "Hyperion передаёт изображение экрана на подсветку.",
        "NSLocalNetworkUsageDescription": "Hyperion ищет сервер подсветки в локальной сети.",
        "NSBonjourServices": ["_hyperiond-json._tcp", "_hyperiond-http._tcp"],
    },
)
