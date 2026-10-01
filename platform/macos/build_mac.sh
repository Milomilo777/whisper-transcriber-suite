#!/usr/bin/env bash
# Build, test and package the macOS app in one command, from a fresh clone:
#
#     bash platform/macos/build_mac.sh
#
# -> dist/WhisperTranscriberSuite-vX.Y.Z-macOS-<x64|arm64>.dmg
#
# Steps (each one is explained in docs/MACOS_BUILD_NOTES.md):
#   1. find a Python 3.12 with Tk 8.6 (python.org installer; not Apple's
#      /usr/bin/python3, whose Tk 8.5 breaks the GUI)
#   2. build venv .buildenv with the slim requirements, --prefer-binary and
#      constraints-macos.txt (on macOS 10.15 also the onnxruntime wheel fix)
#   3. self-contained ffmpeg/ffprobe/ffplay + yt-dlp + deno into bin/
#   4. PyInstaller with platform/macos/pyinstaller/whisper_project_mac.spec
#   5. verify_mac_bundle.sh + smoke_test_app.sh (real transcription, GUI
#      launch, real download) -- skip the smoke test with --no-smoke
#   6. .dmg (create-dmg if installed, else hdiutil), then test_dmg.sh: mount
#      it, copy the app out like Finder, run its CLI and GUI from the copy
#
# Options / environment:
#   --no-smoke        skip step 5's smoke test (the bundle check still runs)
#   PYTHON=/path      use this Python instead of searching for one
#   WTS_MACOS_MIN=X   LSMinimumSystemVersion override (only after testing on X)
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd)"

SMOKE=1
for arg in "$@"; do
  case "$arg" in
    --no-smoke) SMOKE=0 ;;
    -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
    *) echo "error: unknown option $arg" >&2; exit 2 ;;
  esac
done

say_step() { printf '\n== %s\n' "$*"; }
die() { echo "error: $*" >&2; exit 1; }

ARCH="$(uname -m)"
case "$ARCH" in
  x86_64) SUFFIX=x64 ;;
  arm64)  SUFFIX=arm64 ;;
  *) die "unsupported Mac architecture: $ARCH" ;;
esac
MACOS="$(sw_vers -productVersion)"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' core/__init__.py)"
echo "Whisper Transcriber Suite $VERSION -- macOS $MACOS ($ARCH)"

say_step "1. Python 3.12 with Tk 8.6"
py_ok() {
  "$1" -c 'import sys, tkinter; sys.exit(0 if sys.version_info[:2] == (3, 12) and tkinter.TkVersion >= 8.6 else 1)' 2>/dev/null
}
PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for c in /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12 \
           /usr/local/bin/python3.12 "$(command -v python3.12 || true)"; do
    if [ -n "$c" ] && [ -x "$c" ] && py_ok "$c"; then PY="$c"; break; fi
  done
fi
[ -n "$PY" ] && py_ok "$PY" || die "no Python 3.12 with Tk 8.6 found.
  Install it from https://www.python.org/downloads/macos/ (3.12.10 is the last
  3.12 with a macOS installer), or pass one: PYTHON=/path/to/python3.12 bash $0"
echo "using $PY ($("$PY" -c 'import sys, tkinter; print(sys.version.split()[0], "Tk", tkinter.TkVersion)'))"

say_step "2. build venv (.buildenv) + dependencies"
if [ ! -x .buildenv/bin/python ] || ! py_ok .buildenv/bin/python; then
  rm -rf .buildenv
  "$PY" -m venv .buildenv
fi
# shellcheck disable=SC1091
. .buildenv/bin/activate
python -m pip install -q --upgrade pip
# pywhispercpp and stable-ts are optional and never bundled (no Intel wheel /
# pulls torch); see docs/MACOS_BUILD_NOTES.md.
grep -viE '^\s*(pywhispercpp|stable-ts)' requirements.txt > .buildenv/requirements-slim.txt
if [ "$ARCH" = x86_64 ] && [ "${MACOS%%.*}" = 10 ]; then
  # No onnxruntime cp312 wheel installs on macOS < 11. The official
  # macosx_11_0 universal2 wheel works on 10.15 (verified); offer it to pip
  # under a 10.15 tag. Build host only -- nothing about the app changes.
  ORT=.buildenv/ort-wheel
  if ! ls "$ORT"/onnxruntime-1.19.2-*macosx_10_15_universal2.whl >/dev/null 2>&1; then
    mkdir -p "$ORT"
    python -m pip download -q --no-deps --only-binary=:all: --dest "$ORT" \
      --platform macosx_11_0_universal2 --python-version 3.12 onnxruntime==1.19.2
    for w in "$ORT"/onnxruntime-1.19.2-*macosx_11_0_universal2.whl; do
      mv "$w" "${w/macosx_11_0_universal2/macosx_10_15_universal2}"
    done
  fi
  export PIP_FIND_LINKS="$PWD/$ORT"
fi
python -m pip install --prefer-binary -c platform/macos/pyinstaller/constraints-macos.txt \
  -r .buildenv/requirements-slim.txt pyinstaller

say_step "3. self-contained tools into bin/"
bash platform/macos/pyinstaller/fetch_mac_binaries.sh "$ARCH"

say_step "4. PyInstaller"
rm -rf build "dist/Whisper Transcriber Suite" "dist/Whisper Transcriber Suite.app"
pyinstaller --noconfirm --clean platform/macos/pyinstaller/whisper_project_mac.spec
APP="dist/Whisper Transcriber Suite.app"

say_step "5. checks"
bash platform/macos/pyinstaller/verify_mac_bundle.sh "$APP" "$ARCH"
if [ "$SMOKE" = 1 ]; then
  # Needs a logged-in desktop session (GUI launch) and the network (model
  # download, one real YouTube download).
  bash platform/macos/pyinstaller/smoke_test_app.sh "$APP" python tiny
else
  echo "smoke test skipped (--no-smoke)"
fi

say_step "6. .dmg"
WTS_DMG_SUFFIX="$SUFFIX" bash platform/macos/pyinstaller/builddmg.command
OUT="WhisperTranscriberSuite-v$VERSION-macOS-$SUFFIX.dmg"
mv -f "dist/Whisper Transcriber Suite-$SUFFIX.dmg" "dist/$OUT"
if [ "$SMOKE" = 1 ]; then
  bash platform/macos/pyinstaller/test_dmg.sh "dist/$OUT"
else
  bash platform/macos/pyinstaller/test_dmg.sh "dist/$OUT" --no-gui
fi
echo
echo "Done: dist/$OUT"
echo "Minimum macOS: $(/usr/libexec/PlistBuddy -c 'Print :LSMinimumSystemVersion' "$APP/Contents/Info.plist")"
