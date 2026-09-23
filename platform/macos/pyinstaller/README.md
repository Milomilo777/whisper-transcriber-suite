# macOS .app + .dmg via PyInstaller (highest-confidence user install)

This mirrors the **proven pipeline the maintainer already ships** for
`github.com/translation-robot/machine-translate-docx` (PyInstaller → `.app`
→ `.dmg`). It produces a **self-contained** app: the user just opens the
`.dmg` and drags *Whisper Transcriber Suite* to Applications — **no Python,
no Terminal, no venv** on their side.

> **Status (2026-09-23):** built and verified end-to-end on a real Intel
> macOS 10.15 machine (VM) — see `docs/MACOS_BUILD_NOTES.md` for every
> problem hit on the way, why it happened, and how it was fixed. Read that
> file before changing this pipeline or the CI workflow.

## Build steps (on a Mac)

```bash
# 0. (optional) make an icon:  generate assets/whisper.icns from whisper.png
#    e.g.  sips -s format icns assets/whisper.png --out assets/whisper.icns

# 1. SELF-CONTAINED ffmpeg/ffprobe/ffplay + yt-dlp into ./bin (verified: no
#    non-system dylibs). Do NOT copy Homebrew's ffmpeg — it links ~18
#    Homebrew dylibs that PyInstaller does not bundle.
bash platform/macos/pyinstaller/fetch_mac_binaries.sh          # host arch

# 2. deps + PyInstaller (python.org Python 3.12). --prefer-binary matters on
#    Intel: several deps' newest release is sdist-only there.
python3 -m venv .buildenv && . .buildenv/bin/activate
grep -viE '^\s*(pywhispercpp|stable-ts)' requirements.txt > /tmp/req-slim.txt
pip install --prefer-binary -r /tmp/req-slim.txt pyinstaller

# 3. build the .app. LSMinimumSystemVersion is computed from the bundled
#    binaries; override ONLY with a version you actually tested on:
pyinstaller --noconfirm --clean platform/macos/pyinstaller/whisper_project_mac.spec
#    (e.g. WTS_MACOS_MIN=10.15 pyinstaller ...  after verifying on 10.15)

# 4. verify BEFORE shipping — fails on any dylib outside the bundle
bash platform/macos/pyinstaller/verify_mac_bundle.sh

# 5. wrap into a .dmg (create-dmg if installed, else plain hdiutil)
bash platform/macos/pyinstaller/builddmg.command
#    -> dist/Whisper Transcriber Suite-x64.dmg   (rename for the release:
#       WhisperTranscriberSuite-vX.Y.Z-3-macOS-x64.dmg)
```

## Which Macs will the result run on?

The minimum macOS of the `.app` is the **highest** minimum of anything
inside it — not `MACOSX_DEPLOYMENT_TARGET`, which does not touch prebuilt
wheels. The spec prints it (`[mac-spec] highest bundled minos: …`) and
`verify_mac_bundle.sh` reports it. What pip picks depends on the BUILD
host's macOS, e.g. for onnxruntime (needed by faster-whisper's VAD):

| build host | onnxruntime pip picks | resulting app minimum |
|---|---|---|
| Intel, macOS 13+ | 1.23.2 (`macosx_13_0_x86_64`) | macOS 13 |
| Intel, macOS 11–12 | 1.19.2 (`macosx_11_0_universal2`) | macOS 11 (+ protobuf's 12.0 file, runs on 10.15) |
| Apple Silicon | ≥ 1.24 (`macosx_14_0_arm64`) | macOS 14 |

Pin versions (e.g. `onnxruntime==1.19.2`) if you need an older floor.

## Gatekeeper (still unsigned)

This `.app` is **unsigned/un-notarized** (ad-hoc signature only, no paid
Apple Developer cert), so a user who downloads the `.dmg` via a browser hits
the same Gatekeeper block as any unsigned app. Ways through: right-click the
app → Open (macOS ≤ 14), System Settings → Privacy & Security → "Open
Anyway", or
`xattr -dr com.apple.quarantine "/Applications/Whisper Transcriber Suite.app"`.
See `docs/MACOS_BUILD_NOTES.md` for what was actually observed.

## Universal2

Build under the universal2 python.org Python with universal2/fused wheels
and universal ffmpeg (`fetch_mac_binaries.sh universal2`), then
`WTS_TARGET_ARCH=universal2 WTS_DMG_SUFFIX=universal`. Every Mach-O must
then report both archs (`verify_mac_bundle.sh <app> universal2`).
