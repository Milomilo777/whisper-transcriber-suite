#!/usr/bin/env bash
# Package the PyInstaller-built "Whisper Transcriber Suite.app" into a drag-to-
# Applications .dmg, using create-dmg (`brew install create-dmg`). Mirrors
# the maintainer's machine-translate-docx/compile/mac/builddmg-gui.sh.
# Run on a Mac, AFTER building the .app from whisper_project_mac.spec.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../../.." && pwd)"

APP="dist/Whisper Transcriber Suite.app"
if [ ! -d "$APP" ]; then
  echo "error: $APP not found. Build it first:" >&2
  echo "  pyinstaller --noconfirm --clean platform/macos/pyinstaller/whisper_project_mac.spec" >&2
  exit 1
fi
# create-dmg (brew install create-dmg) gives the styled Finder window. When it
# is missing (e.g. a build host without Homebrew), fall back to plain hdiutil,
# which ships with macOS: same drag-to-Applications contents, default layout.
HAVE_CREATE_DMG=1
if ! command -v create-dmg >/dev/null 2>&1; then
  echo "note: create-dmg not found - falling back to hdiutil (brew install create-dmg for the styled window)." >&2
  HAVE_CREATE_DMG=0
fi

mkdir -p dist/dmg
rm -rf dist/dmg/*
cp -R "$APP" dist/dmg/

# Arch-suffix the .dmg name so a single-arch build is never mistaken for
# a universal one (a real mixup: an x64-only build shipped under a
# "universal" name in v1.5.0). x86_64 -> "x64" per the team's convention.
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64) SUFFIX="x64" ;;
  *)      SUFFIX="$ARCH" ;;
esac
# uname -m is the BUILD HOST arch; a universal2 build sets WTS_DMG_SUFFIX=universal.
SUFFIX="${WTS_DMG_SUFFIX:-$SUFFIX}"
DMG="dist/Whisper Transcriber Suite-${SUFFIX}.dmg"
rm -f "$DMG" "dist/Whisper Transcriber Suite.dmg"

if [ "$HAVE_CREATE_DMG" = 0 ]; then
  ln -s /Applications "dist/dmg/Applications"
  hdiutil create -volname "Whisper Transcriber Suite" -srcfolder "dist/dmg/" \
    -ov -format UDZO -fs HFS+ "$DMG"
  echo "Built: $DMG"
  exit 0
fi

create-dmg \
  --volname "Whisper Transcriber Suite" \
  --window-pos 200 120 \
  --window-size 600 320 \
  --icon-size 100 \
  --icon "Whisper Transcriber Suite.app" 170 130 \
  --hide-extension "Whisper Transcriber Suite.app" \
  --app-drop-link 430 130 \
  "$DMG" \
  "dist/dmg/"

echo "Built: $DMG"
