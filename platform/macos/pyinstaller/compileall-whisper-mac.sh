set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../../.." && pwd)"

if ! command -v create-dmg >/dev/null 2>&1; then
  echo "error: create-dmg not found. Install it: brew install create-dmg" >&2
  exit 1
fi

rm -rf dist

pyinstaller --noconfirm --clean platform/macos/pyinstaller/whisper_project_mac.spec

rm -rf dist/dmg/
mkdir dist/dmg
cp -R "dist/Whisper Transcriber Suite.app" dist/dmg/

# Arch-suffix the .dmg name so a single-arch build is never mistaken for
# a universal one (a real mixup: an x64-only build shipped under a
# "universal" name in v1.5.0). x86_64 -> "x64" per the team's convention.
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64) SUFFIX="x64" ;;
  *)      SUFFIX="$ARCH" ;;
esac
DMG="dist/Whisper Transcriber Suite-${SUFFIX}.dmg"
rm -f "$DMG" "dist/Whisper Transcriber Suite.dmg"

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
