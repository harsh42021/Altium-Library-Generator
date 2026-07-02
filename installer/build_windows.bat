@echo off
REM Builds the Windows installer for The Construct.
REM Run this from the repo root on a Windows machine with:
REM   - Python 3.10+ installed and on PATH
REM   - Inno Setup installed (https://jrsoftware.org/isinfo.php)
REM
REM Output: installer\output\TheConstructSetup.exe

setlocal enabledelayedexpansion

echo === Step 1: Installing Python dependencies ===
pip install --upgrade pip
pip install pyinstaller pdfplumber
if errorlevel 1 (
    echo FAILED: pip install. Is Python installed and on PATH?
    exit /b 1
)

echo === Step 2: Building executable with PyInstaller ===
pyinstaller installer\pyinstaller\altium_libgen.spec --distpath dist --workpath build --noconfirm
if errorlevel 1 (
    echo FAILED: PyInstaller build.
    exit /b 1
)

echo === Step 3: Locating Inno Setup Compiler ===
set ISCC=
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"

if "%ISCC%"=="" (
    echo FAILED: Inno Setup Compiler not found.
    echo Install it from https://jrsoftware.org/isinfo.php and re-run this script.
    exit /b 1
)

echo === Step 4: Building installer with Inno Setup ===
%ISCC% installer\innosetup\installer.iss
if errorlevel 1 (
    echo FAILED: Inno Setup compile.
    exit /b 1
)

echo.
echo === DONE ===
echo Installer created at: installer\output\TheConstructSetup.exe
endlocal
