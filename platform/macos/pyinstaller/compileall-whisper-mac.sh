# The colleague's one-shot build: build the .app, wrap it in a
# .dmg. Run from anywhere with the build venv active (python.org Python 3.12
# with Tk 8.6 + the slim requirements; see docs/MACOS_BUILD_NOTES.md):
#     bash platform/macos/pyinstaller/compileall-whisper-mac.sh
# -> dist/Whisper Transcriber Suite.app + dist/Whisper Transcriber Suite-<x64|arm64>.dmg
# `pyinstaller --noconfirm --clean whisper_project_onedir.spec` from the repo
# root builds the same .app. For real transcription/download smoke tests and
# release file names in one go, use platform/macos/build_mac.sh instead.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../../.." && pwd)"

pyinstaller --noconfirm --clean platform/macos/pyinstaller/whisper_project_mac.spec

# Same create-dmg layout as before (x64/arm64-suffixed name); falls back to
# plain hdiutil when create-dmg (brew install create-dmg) is not installed.
# The central packager checks the host, native bundle and copied image.
# Pass --no-gui only for an explicitly nonrelease packaging check.
bash platform/macos/pyinstaller/builddmg.command "$@"
