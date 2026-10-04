#!/usr/bin/env bash
# Test the finished .dmg the way a user meets it: mount it, check the
# drag-to-Applications layout, copy the app out of it like Finder does, run
# the CLI and open the GUI from that copy, then unmount. The .app in dist/
# was already smoke-tested; this checks that the .dmg step (create-dmg or
# hdiutil) did not lose or break anything. Runs from build_mac.sh step 6 and
# from macos-app.yml after the dmg is made.
#
# Usage: bash platform/macos/pyinstaller/test_dmg.sh <path.dmg> [--no-gui]
#   --no-gui   skip the GUI launch (no logged-in desktop session)
set -uo pipefail
DMG="${1:?usage: test_dmg.sh <path.dmg> [--no-gui]}"
GUI=1; [ "${2:-}" = "--no-gui" ] && GUI=0
[ -f "$DMG" ] || { echo "error: $DMG not found" >&2; exit 1; }
NAME="Whisper Transcriber Suite"
fail=0
MNT="$(mktemp -d /tmp/wts-dmg.XXXXXX)"
DEST="$(mktemp -d /tmp/wts-apps.XXXXXX)"
cleanup() {
  pkill -f "$DEST/$NAME.app/Contents/MacOS/" 2>/dev/null || true
  hdiutil detach "$MNT" -quiet 2>/dev/null || hdiutil detach "$MNT" -force -quiet 2>/dev/null || true
  rm -rf "$DEST"; rmdir "$MNT" 2>/dev/null || true
}
trap cleanup EXIT

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
if plutil -lint "$PL" >/dev/null; then echo "OK   Info.plist parses"; else echo "FAIL Info.plist does not parse"; fail=1; fi
for k in CFBundleIdentifier CFBundleShortVersionString LSMinimumSystemVersion NSMicrophoneUsageDescription; do
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
# Gatekeeper holds and kills yt-dlp when it runs.
QTN="0083;$(printf %x "$(date +%s)");Safari;$(uuidgen)"
for t in yt-dlp deno ffmpeg; do xattr -w com.apple.quarantine "$QTN" "$APP/Contents/Frameworks/bin/$t"; done
if "$APP/Contents/MacOS/$NAME" transcribe --help >/dev/null 2>&1; then echo "OK   CLI runs from the copy"; else echo "FAIL CLI boot from the copy"; fail=1; fi
qleft=""
for t in yt-dlp deno ffmpeg; do
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
  open "$APP"
  ok=0
  for _ in $(seq 1 90); do
    now="$(grep -c 'App startup' "$LOG_DIR/app.log" 2>/dev/null || true)"
    if [ "${now:-0}" -gt "${before:-0}" ]; then ok=1; break; fi
    sleep 1
  done
  sleep 5
  if [ "$ok" = 1 ] && pgrep -f "$APP/Contents/MacOS/" >/dev/null; then
    echo "OK   GUI started from the copy and is still running"
  else
    echo "FAIL GUI did not start from the copy (or died)"; tail -30 "$LOG_DIR/app.log" 2>/dev/null || true; fail=1
  fi
  pkill -f "$APP/Contents/MacOS/" 2>/dev/null || true
  sleep 2
else
  echo "== 3. GUI launch skipped (--no-gui)"
fi

echo "== 4. detach"
if hdiutil detach "$MNT" -quiet; then echo "OK   unmounted"; else echo "FAIL detach"; fail=1; fi
[ "$fail" = 0 ] && echo "DMG TEST PASSED" || { echo "DMG TEST FAILED" >&2; exit 1; }
