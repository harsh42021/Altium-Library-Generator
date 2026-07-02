# Building the Windows Installer

I can't compile a Windows `.exe` from where I'm running (Linux
sandbox) — PyInstaller builds for the OS it runs on, and Inno Setup is
Windows-only. Two ways to actually get the installer:

## Option A — No Windows machine needed (recommended)

1. Push this whole `altium_libgen/` folder to a GitHub repo (public or
   private both work).
2. The workflow at `installer/github_workflow/build-windows-installer.yml`
   needs to live at `.github/workflows/build-windows-installer.yml` in
   your repo — GitHub only picks up workflows from that exact path, so
   move/copy it there:
   ```
   mkdir -p .github/workflows
   cp installer/github_workflow/build-windows-installer.yml .github/workflows/
   git add .
   git commit -m "Add Windows installer build"
   git push
   ```
3. Go to your repo's **Actions** tab on GitHub. The workflow runs
   automatically on push, or click **Run workflow** to trigger it
   manually.
4. When it finishes (a few minutes), open the run and download the
   **TheConstructSetup** artifact from the bottom of the
   page — that's your installer.

This runs on Microsoft's own Windows servers, so the result is a
genuinely compiled, tested Windows build — not something I'm asking
you to trust blind.

## Option B — Build it yourself on a Windows machine

1. Install [Python 3.10+](https://python.org) (check "Add to PATH"
   during install) and [Inno Setup](https://jrsoftware.org/isinfo.php).
2. Copy this whole `altium_libgen/` folder onto the Windows machine.
3. Open Command Prompt in that folder and run:
   ```
   installer\build_windows.bat
   ```
4. Installer appears at `installer\output\TheConstructSetup.exe`.

## What the installer does

- Installs the app to `Program Files\The Construct`
- Creates a Start Menu entry and (optional, checked by default) a
  desktop shortcut
- Bundles the Python runtime and all dependencies (`pdfplumber`, etc.)
  inside the `.exe` via PyInstaller — end users installing this do
  **not** need Python, pip, or anything else installed. That's what
  eliminates the dependency headache you were running into.
- Standard uninstaller registered in Windows "Add or Remove Programs"

## Current scope — please read before relying on this

The GUI wraps everything built so far: datasheet input → pin
extraction → classification → review report → JSON export. It does
**not** yet generate actual Altium `.SchLib`/`.PcbLib` files — that
stage (the DelphiScript bridge driving Altium) hasn't been built yet.
Right now this app gets you a verified, reviewed `component.json` per
part; turning that into real Altium library files is the next piece of
work.
