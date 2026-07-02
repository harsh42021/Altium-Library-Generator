# PyInstaller spec for The Construct.
#
# Build (on Windows, with Python + pip install pyinstaller pdfplumber):
#     pyinstaller installer/pyinstaller/altium_libgen.spec
#
# Output: dist/TheConstruct/TheConstruct.exe
# (onedir build, not onefile — onefile is slower to launch since it
# unpacks to a temp dir on every run; onedir is the better choice for
# a desktop tool that gets launched repeatedly.)

import sys
from pathlib import Path

block_cipher = None

# Paths are relative to the repo root; PyInstaller is invoked from there.
REPO_ROOT = Path(".").resolve()
EXTRACTION_DIR = REPO_ROOT / "python_extraction"
GUI_DIR = REPO_ROOT / "gui"
ALTIUM_BRIDGE_DIR = REPO_ROOT / "altium_bridge"
ICON_PATH = REPO_ROOT / "installer" / "pyinstaller" / "app_icon.ico"

# Bundle the icon as accessible runtime data too (not just baked into
# the .exe resource section via the icon= parameter below) — the icon=
# parameter only controls what Explorer/taskbar show for the .exe
# file itself; it does NOT make the file readable at runtime, which
# the GUI needs for its own self.iconbitmap() call on window creation.
extra_datas = []
if ICON_PATH.exists():
    extra_datas.append((str(ICON_PATH), "installer/pyinstaller"))

a = Analysis(
    [str(GUI_DIR / "app.py")],
    pathex=[str(EXTRACTION_DIR), str(GUI_DIR), str(ALTIUM_BRIDGE_DIR)],
    binaries=[],
    datas=extra_datas,
    hiddenimports=[
        "pdfplumber",
        "PIL",
        "PIL._tkinter_finder",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TheConstruct",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # GUI app — no console window
    icon=str(ICON_PATH) if ICON_PATH.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="TheConstruct",
)
