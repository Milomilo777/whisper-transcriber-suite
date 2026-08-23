# macOS .app + .dmg via PyInstaller (highest-confidence user install)

This mirrors the **proven pipeline the maintainer already ships** for
`github.com/translation-robot/machine-translate-docx` (PyInstaller → `.app`
→ `create-dmg` → `.dmg`). It produces a **self-contained** app: the user
just opens the `.dmg` and drags *Whisper Transcriber Suite* to Applications — **no
Python, no Terminal, no venv** on their side. Because that toolchain is
already trusted on real Macs, this is the highest-confidence Mac deliverable.

> Trade-off vs. the other two methods (the `install.command` source+venv,
> and the Homebrew formula): this one **must be built on a Mac** and is a
> bigger download (bundles Python + all deps). It has NOT been built here
> (no Mac available) — the `.spec` is adapted from the Windows
> `whisper_project_onedir.spec`; build + verify it on a Mac before shipping.

## Build steps (on a Mac)

```bash
# 0. (optional) make an icon:  generate assets/whisper.icns from whisper.png
#    e.g.  sips -s format icns assets/whisper.png --out assets/whisper.icns
# 1. put MAC ffmpeg/ffprobe/ffplay (+ yt-dlp) in ./bin  — NOT the .exe ones.
#    e.g.  cp "$(brew --prefix)/bin/"{ffmpeg,ffprobe,ffplay} bin/
#          ./bin/yt-dlp  (download the macos build or `pip download yt-dlp`)
# 2. deps + PyInstaller
python3 -m venv .buildenv && . .buildenv/bin/activate
pip install -r requirements.txt pyinstaller
# 3. build the .app
pyinstaller --noconfirm --clean platform/macos/pyinstaller/whisper_project_mac.spec
#    -> dist/Whisper Transcriber Suite.app
# 4. wrap into a .dmg
brew install create-dmg
bash platform/macos/pyinstaller/builddmg.command
#    -> dist/Whisper Transcriber Suite.dmg
```

## Gatekeeper (still unsigned)

This `.app` is **unsigned/un-notarized** (no paid Apple Developer cert), so
a user who downloads the `.dmg` via a browser hits the same Gatekeeper
block as any unsigned app. Two easy outs (see `../README.md` for detail):
right-click the app → Open (or System Settings → Privacy & Security → "Open
Anyway"), or `xattr -dr com.apple.quarantine "/Applications/Whisper Transcriber Suite.app"`.
Optionally ad-hoc sign for a stable code identity (better TCC behavior):
`codesign --force --deep -s - "dist/Whisper Transcriber Suite.app"`.

## Notes / to verify on a Mac

- `bin/` must hold **macOS** ffmpeg/ffprobe/ffplay (bundling ffplay here is
  what makes Video Tiling work out of the box on this path).
- Universal2 vs single-arch: build on the target arch, or use a universal2
  Python + `--target-arch universal2` if you need one app for Intel + ASi.
- Trim/extend the `.spec` `hiddenimports` after the first real build (some
  optional backends may pull or miss modules on macOS).
