#!/usr/bin/env bash
# Package the PyInstaller-built "Whisper Transcriber Suite.app" into a drag-to-
# Applications .dmg after supported-host, native and copied-image checks.
# Run on a Mac after building the .app. --no-gui is packaging-only validation.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../../.." && pwd)"

APP="dist/Whisper Transcriber Suite.app"
VERIFY_PYTHON="${PYTHON:-python3}"
REFERENCE_MANIFEST=""
GUI=1
while [ "$#" -gt 0 ]; do
  case "$1" in
    --no-gui) GUI=0; shift ;;
    --manifest) REFERENCE_MANIFEST="${2:?missing verified-app manifest}"; shift 2 ;;
    *) echo "error: unknown option $1" >&2; exit 2 ;;
  esac
done
if [ ! -d "$APP" ]; then
  echo "error: $APP not found. Build it first:" >&2
  echo "  pyinstaller --noconfirm --clean platform/macos/pyinstaller/whisper_project_mac.spec" >&2
  exit 1
fi
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
case "$SUFFIX" in
  x64) WANT=x86_64 ;;
  arm64) WANT=arm64 ;;
  universal) WANT=universal2 ;;
  *) echo "error: unsupported DMG suffix $SUFFIX" >&2; exit 2 ;;
esac
[ ! -e "$DMG" ] && [ ! -L "$DMG" ] || { echo "error: output already exists: $DMG" >&2; exit 1; }
CONTRACT=platform/macos/pyinstaller/bundle_contract.py
"$VERIFY_PYTHON" "$CONTRACT" host "$APP" "$(sw_vers -productVersion)"
if [ -n "$REFERENCE_MANIFEST" ]; then
  "$VERIFY_PYTHON" "$CONTRACT" verify "$APP" "$REFERENCE_MANIFEST"
fi
WORK="$(mktemp -d "dist/.wts-dmg.XXXXXX")"
cleanup() { rm -rf -- "$WORK"; }
trap cleanup EXIT
MANIFEST="$WORK/verified-app.json"
STAGE="$WORK/source"
IMAGE="$WORK/image.dmg"
"$VERIFY_PYTHON" "$CONTRACT" manifest "$APP" "$MANIFEST"
bash platform/macos/pyinstaller/verify_mac_bundle.sh "$APP" "$WANT" "$VERIFY_PYTHON"
"$VERIFY_PYTHON" "$CONTRACT" verify "$APP" "$MANIFEST"
mkdir "$STAGE"
cp -R "$APP" "$STAGE/"
"$VERIFY_PYTHON" "$CONTRACT" verify "$STAGE/Whisper Transcriber Suite.app" "$MANIFEST"

if command -v create-dmg >/dev/null 2>&1; then
  create-dmg \
  --volname "Whisper Transcriber Suite" \
  --window-pos 200 120 \
  --window-size 600 320 \
  --icon-size 100 \
  --icon "Whisper Transcriber Suite.app" 170 130 \
  --hide-extension "Whisper Transcriber Suite.app" \
  --app-drop-link 430 130 \
    "$IMAGE" \
    "$STAGE/"
else
  ln -s /Applications "$STAGE/Applications"
  hdiutil create -volname "Whisper Transcriber Suite" -srcfolder "$STAGE/" \
    -format UDZO -fs HFS+ "$IMAGE"
fi
[ -f "$IMAGE" ] && [ ! -L "$IMAGE" ] && [ -s "$IMAGE" ] || { echo "error: image builder produced no fresh nonempty image" >&2; exit 1; }
"$VERIFY_PYTHON" "$CONTRACT" verify "$APP" "$MANIFEST"
AUDIT_ARGS=("$IMAGE" --manifest "$MANIFEST" --verify-python "$VERIFY_PYTHON" --arch "$WANT")
if [ "$GUI" = 0 ]; then AUDIT_ARGS+=(--no-gui); fi
bash platform/macos/pyinstaller/test_dmg.sh "${AUDIT_ARGS[@]}"
"$VERIFY_PYTHON" "$CONTRACT" verify "$APP" "$MANIFEST"
# Never replace an existing output, including one created during the audit.
mv -n "$IMAGE" "$DMG"
[ ! -e "$IMAGE" ] || { echo "error: output appeared during packaging: $DMG" >&2; exit 1; }
if [ "$GUI" = 1 ]; then
  echo "Built and copied-image checked: $DMG"
else
  echo "Packaging only: $DMG (GUI skipped; not release validated)"
fi
