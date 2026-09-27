# The colleague's one-shot build: clean dist/, build the .app, wrap it in a
# .dmg. Run from anywhere with the build venv active (python.org Python 3.12
# with Tk 8.6 + the slim requirements; see docs/MACOS_BUILD_NOTES.md):
#     bash platform/macos/pyinstaller/compileall-whisper-mac.sh
# -> dist/Whisper Transcriber Suite.app + dist/Whisper Transcriber Suite-<x64|arm64>.dmg
# `pyinstaller --noconfirm --clean whisper_project_onedir.spec` from the repo
# root builds the same .app. For release file names plus the bundle check and
# smoke test in one go, use platform/macos/build_mac.sh instead.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../../.." && pwd)"

rm -rf dist

pyinstaller --noconfirm --clean platform/macos/pyinstaller/whisper_project_mac.spec

# Same create-dmg layout as before (x64/arm64-suffixed name); falls back to
# plain hdiutil when create-dmg (brew install create-dmg) is not installed.
bash platform/macos/pyinstaller/builddmg.command
