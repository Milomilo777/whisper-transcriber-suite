#!/usr/bin/env bash
# Test the finished .dmg the way a user meets it: mount it, check the
# drag-to-Applications layout, copy the app out of it like Finder does, run
# the CLI and open the GUI from that copy, then unmount. The .app in dist/
# was already smoke-tested; this checks that the .dmg step (create-dmg or
# hdiutil) did not lose or break anything. Runs from build_mac.sh step 6 and
# from macos-app.yml after the dmg is made.
#
# Usage: bash platform/macos/pyinstaller/test_dmg.sh <path.dmg> [--no-gui] [--arch x86_64|arm64|universal2]
#   --no-gui   skip the GUI launch (no logged-in desktop session)
set -uo pipefail
DMG="${1:?usage: test_dmg.sh <path.dmg> [--no-gui]}"
shift
GUI=1; MANIFEST=""; VERIFY_PYTHON="${PYTHON:-python3}"
WANT="$(uname -m)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --no-gui) GUI=0; shift ;;
    --manifest) MANIFEST="${2:?missing verified-app manifest}"; shift 2 ;;
    --verify-python) VERIFY_PYTHON="${2:?missing verification Python}"; shift 2 ;;
    --arch) WANT="${2:?missing application architecture}"; shift 2 ;;
    *) echo "error: unknown option $1" >&2; exit 2 ;;
  esac
done
case "$WANT" in
  x86_64|arm64|universal2) ;;
  *) echo "error: unsupported application architecture $WANT" >&2; exit 2 ;;
esac
[ -f "$DMG" ] || { echo "error: $DMG not found" >&2; exit 1; }
NAME="Whisper Transcriber Suite"
fail=0
if [ "$GUI" = 1 ]; then
  "$VERIFY_PYTHON" "$SCRIPT_DIR/copied_gui_process.py" preflight || {
    echo "error: GUI verification needs psutil in the verification Python; use the build environment" >&2
    exit 1
  }
fi
# LaunchServices reports the physical executable path. Resolve aliases such as
# /var -> /private/var and trailing separators before creating owned paths.
TMP_ROOT="$(cd -- "${TMPDIR:-/tmp}" && pwd -P)" || { echo "error: invalid temporary directory" >&2; exit 1; }
MNT=""; DEST=""; GUI_STARTED=""; GUI_STOP_FAILED=0
stop_copied_gui() {
  [ -n "$GUI_STARTED" ] || return 0
  [ "$GUI_STOP_FAILED" = 0 ] || return 1
  local receipt="$DEST/gui-processes.json" capture_status=0
  if [ ! -f "$receipt" ]; then
    "$VERIFY_PYTHON" "$SCRIPT_DIR/copied_gui_process.py" capture "$DEST/$NAME.app/Contents/MacOS/$NAME" "$GUI_STARTED" "$receipt" || capture_status=$?
    [ "$capture_status" -le 1 ] || return 1
  fi
  "$VERIFY_PYTHON" "$SCRIPT_DIR/copied_gui_process.py" stop "$DEST/$NAME.app/Contents/MacOS/$NAME" "$GUI_STARTED" "$receipt"
}
cleanup() {
  local cleanup_status=0
  if [ -n "$DEST" ]; then
    if stop_copied_gui; then
      rm -rf -- "$DEST"
    else
      echo "FAIL copied GUI cleanup unresolved; preserving $DEST" >&2
      cleanup_status=1
    fi
  fi
  if [ -n "$MNT" ]; then
    hdiutil detach "$MNT" -quiet 2>/dev/null || hdiutil detach "$MNT" -force -quiet 2>/dev/null || true
    rmdir "$MNT" 2>/dev/null || true
  fi
  return "$cleanup_status"
}
trap 'cleanup || exit 1' EXIT
MNT="$(mktemp -d "${TMP_ROOT%/}/wts-dmg.XXXXXX")" || exit 1
DEST="$(mktemp -d "${TMP_ROOT%/}/wts-apps.XXXXXX")" || exit 1

CONTRACT="$SCRIPT_DIR/bundle_contract.py"
if [ -z "$MANIFEST" ]; then
  REFERENCE="$(dirname "$DMG")/$NAME.app"
  MANIFEST="$DEST/verified-app.json"
  "$VERIFY_PYTHON" "$CONTRACT" host "$REFERENCE" "$(sw_vers -productVersion)" || exit 1
  "$VERIFY_PYTHON" "$CONTRACT" manifest "$REFERENCE" "$MANIFEST" || exit 1
  bash "$SCRIPT_DIR/verify_mac_bundle.sh" "$REFERENCE" "$WANT" "$VERIFY_PYTHON" || exit 1
  "$VERIFY_PYTHON" "$CONTRACT" verify "$REFERENCE" "$MANIFEST" || exit 1
fi

echo "== 1. hdiutil verify + attach"
if hdiutil verify -quiet "$DMG"; then echo "OK   image checksum"; else echo "FAIL hdiutil verify"; fail=1; fi
hdiutil attach -nobrowse -readonly -noautoopen -quiet -mountpoint "$MNT" "$DMG" \
  || { echo "FAIL could not mount $DMG"; exit 1; }
[ -d "$MNT/$NAME.app" ] || { echo "FAIL '$NAME.app' is not in the dmg:"; ls -la "$MNT"; exit 1; }
if [ -L "$MNT/Applications" ] && [ "$(readlink "$MNT/Applications")" = "/Applications" ]; then
  echo "OK   Applications -> /Applications link (drag-to-install layout)"
else
  echo "FAIL no Applications -> /Applications link in the dmg"; fail=1
fi

echo "== 2. copy out like Finder, then check the copy"
cp -R "$MNT/$NAME.app" "$DEST/" || { echo "FAIL copying the app out of the dmg"; exit 1; }
APP="$DEST/$NAME.app"
PL="$APP/Contents/Info.plist"
"$VERIFY_PYTHON" "$CONTRACT" verify "$APP" "$MANIFEST" || exit 1
"$VERIFY_PYTHON" "$CONTRACT" host "$APP" "$(sw_vers -productVersion)" || exit 1
bash "$SCRIPT_DIR/verify_mac_bundle.sh" "$APP" "$WANT" "$VERIFY_PYTHON" || exit 1
if plutil -lint "$PL" >/dev/null; then echo "OK   Info.plist parses"; else echo "FAIL Info.plist does not parse"; fail=1; fi
for k in CFBundleIdentifier CFBundleShortVersionString LSMinimumSystemVersion NSMicrophoneUsageDescription CFBundleDocumentTypes:0:CFBundleTypeRole CFBundleDocumentTypes:0:LSHandlerRank; do
  v="$(/usr/libexec/PlistBuddy -c "Print :$k" "$PL" 2>/dev/null)"
  if [ -n "$v" ]; then echo "     $k = $v"; else echo "FAIL Info.plist lacks $k"; fail=1; fi
done
if codesign --verify --deep --strict "$APP" 2>/dev/null; then echo "OK   signature intact after the dmg round trip"; else echo "FAIL codesign on the copied app"; fail=1; fi
for t in ffmpeg ffprobe yt-dlp deno; do
  [ -f "$APP/Contents/MacOS/bin/$t" ] || { echo "FAIL runtime tool missing in the copy: Contents/MacOS/bin/$t"; fail=1; }
done
# A browser download quarantines every file in the app. Tag the bundled tools
# that way (not the app itself, which would need a Gatekeeper click) and check
# that starting the app clears them (core.paths.clear_bundled_quarantine), or
# Gatekeeper holds and kills yt-dlp when it runs. yt-dlp is the onedir build,
# so also tag a library inside its folder (the clear must be recursive).
QTN="0083;$(printf %x "$(date +%s)");Safari;$(uuidgen)"
QTOOLS="yt-dlp deno ffmpeg yt-dlp_dist/_internal/Python"
for t in $QTOOLS; do xattr -w com.apple.quarantine "$QTN" "$APP/Contents/Frameworks/bin/$t"; done
if "$APP/Contents/MacOS/$NAME" transcribe --help >/dev/null 2>&1; then echo "OK   CLI runs from the copy"; else echo "FAIL CLI boot from the copy"; fail=1; fi
qleft=""
for t in $QTOOLS; do
  xattr -p com.apple.quarantine "$APP/Contents/Frameworks/bin/$t" >/dev/null 2>&1 && qleft="$qleft $t"
done
if [ -z "$qleft" ]; then echo "OK   app start cleared the quarantine flag from its bundled tools"; else echo "FAIL still quarantined after app start:$qleft"; fail=1; fi
# Gatekeeper's verdict, for the record only: an ad-hoc signed app is
# "rejected" (no Developer ID); the wording tells unsigned from damaged.
echo "     spctl: $(spctl --assess --type exec -vv "$APP" 2>&1 | tr '\n' ' ')"

if [ "$GUI" = 1 ]; then
  echo "== 3. GUI launch from the copy (LaunchServices)"
  LOG_DIR="$HOME/Library/Logs/WhisperTranscriberSuite"
  before="$(grep -c 'App startup' "$LOG_DIR/app.log" 2>/dev/null || true)"
  GUI_STARTED="$("$VERIFY_PYTHON" -c 'import time; print(time.time())')" || exit 1
  open "$APP" || exit 1
  ok=0
  for _ in $(seq 1 90); do
    now="$(grep -c 'App startup' "$LOG_DIR/app.log" 2>/dev/null || true)"
    if [ "${now:-0}" -gt "${before:-0}" ]; then ok=1; break; fi
    sleep 1
  done
  sleep 5
  alive=0
  if "$VERIFY_PYTHON" "$SCRIPT_DIR/copied_gui_process.py" capture "$APP/Contents/MacOS/$NAME" "$GUI_STARTED" "$DEST/gui-processes.json"; then alive=1; fi
  if [ "$ok" = 1 ] && [ "$alive" = 1 ]; then
    echo "OK   GUI started from the copy and is still running"
  else
    echo "FAIL GUI did not start from the copy (or died)"; tail -30 "$LOG_DIR/app.log" 2>/dev/null || true; fail=1
    # Paths and process identity only: never emit argv or environment values.
    "$VERIFY_PYTHON" - "$APP/Contents/MacOS/$NAME" <<'PY' || true
import json
import os
import sys
print("GUI expected executable: " + os.path.realpath(sys.argv[1]))
try:
    import psutil
    count = 0
    for process in psutil.process_iter(["pid", "create_time", "exe", "status", "name"]):
        info = process.info
        if "whisper" not in (info.get("name") or "").lower():
            continue
        print("GUI candidate: " + json.dumps({key: info.get(key) for key in ("pid", "create_time", "exe", "status")}))
        count += 1
        if count >= 20:
            break
except Exception as error:
    print("GUI process diagnostic unavailable: " + type(error).__name__)
PY
  fi
  if ! stop_copied_gui; then
    echo "FAIL copied GUI cleanup unresolved" >&2
    GUI_STOP_FAILED=1; fail=1
  fi
  sleep 2
else
  echo "== 3. GUI launch skipped (--no-gui)"
fi

echo "== 4. detach"
if hdiutil detach "$MNT" -quiet; then echo "OK   unmounted"; else echo "FAIL detach"; fail=1; fi
[ "$fail" = 0 ] || { echo "DMG TEST FAILED" >&2; exit 1; }
if [ "$GUI" = 1 ]; then
  echo "DMG TEST PASSED"
else
  echo "DMG PACKAGING CHECKS PASSED (GUI not validated)"
fi
