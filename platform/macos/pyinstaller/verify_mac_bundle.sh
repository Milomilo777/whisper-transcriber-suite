#!/usr/bin/env bash
# Verify a built "Whisper Transcriber Suite.app" BEFORE it is shipped.
# Fails (exit 1) if any Mach-O in the bundle:
#   * links a library outside the bundle other than /usr/lib or /System, or
#   * lacks an expected architecture (pass universal2 to require both).
# Also prints the highest minimum-macOS found vs. the Info.plist
# LSMinimumSystemVersion, and runs the bundled ffmpeg / yt-dlp / CLI once.
#
# Usage: bash platform/macos/pyinstaller/verify_mac_bundle.sh [app-path] [x86_64|arm64|universal2]
set -uo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../../.." && pwd)"

APP="${1:-dist/Whisper Transcriber Suite.app}"
WANT="${2:-$(uname -m)}"
[ -d "$APP" ] || { echo "error: $APP not found" >&2; exit 1; }

n=0; bad=0; max="0.0"; maxfile=""
while IFS= read -r -d '' f; do
  file "$f" | grep -q 'Mach-O' || continue
  n=$((n + 1))
  rel="${f#"$APP"/}"
  archs="$(lipo -archs "$f" 2>/dev/null)"
  case "$WANT" in
    universal2) { [[ " $archs " == *" x86_64 "* ]] && [[ " $archs " == *" arm64 "* ]]; } || { echo "ARCH  $rel: $archs"; bad=$((bad + 1)); } ;;
    *) [[ " $archs " == *" $WANT "* ]] || { echo "ARCH  $rel: $archs"; bad=$((bad + 1)); } ;;
  esac
  ext="$(otool -L "$f" 2>/dev/null | grep -v ':$' | grep -vE '@rpath|@loader_path|@executable_path|/usr/lib/|/System/Library/' || true)"
  if [ -n "$ext" ]; then
    echo "DEP   $rel:"; echo "$ext"; bad=$((bad + 1))
  fi
  m="$(otool -l "$f" | awk '/LC_BUILD_VERSION/{b=1} b&&/minos/{print $2; exit} /LC_VERSION_MIN_MACOSX/{v=1} v&&/ version/{print $2; exit}')"
  if [ -n "$m" ] && [ "$(printf '%s\n%s\n' "$max" "$m" | sort -V | tail -1)" = "$m" ] && [ "$m" != "$max" ]; then
    max="$m"; maxfile="$rel"
  fi
done < <(find "$APP" -type f \( -perm -u+x -o -name '*.dylib' -o -name '*.so' \) -print0)

plist_min="$(/usr/libexec/PlistBuddy -c 'Print :LSMinimumSystemVersion' "$APP/Contents/Info.plist" 2>/dev/null)"
echo "Mach-O files scanned : $n"
echo "problems             : $bad"
echo "highest minos        : $max  ($maxfile)"
echo "LSMinimumSystemVersion: $plist_min"

B="$APP/Contents/Frameworks/bin"
v="$("$B/ffmpeg" -hide_banner -version 2>&1)" && echo "${v%%$'\n'*}" || { echo "ffmpeg FAILED: $v"; bad=$((bad + 1)); }
# yt-dlp must be the self-contained yt-dlp_macos, run with the PATH an app
# opened from Finder gets: the Python-script "yt-dlp" passes in a shell with a
# venv python3 but fails in the app on Apple's python3 3.9 (needs 3.10+).
# It is the onedir build: Frameworks/bin/yt-dlp is a symlink into yt-dlp_dist/
# (hence file -L). Its 2nd start must be fast; the onefile build took ~25 s
# on every start because it unpacked itself each time.
file -bL "$B/yt-dlp" | grep -q Mach-O || { echo "yt-dlp is not a Mach-O executable (Python-script build?)"; bad=$((bad + 1)); }
[ -d "$B/yt-dlp_dist/_internal" ] || { echo "yt-dlp is not the onedir build (no yt-dlp_dist/_internal)"; bad=$((bad + 1)); }
ran_ok=1
for _run in 1 2; do
  t0=$SECONDS
  v="$(env -i HOME="$HOME" TMPDIR="${TMPDIR:-/tmp}" PATH=/usr/bin:/bin:/usr/sbin:/sbin "$B/yt-dlp" --version 2>&1)" || { echo "yt-dlp FAILED: $v"; bad=$((bad + 1)); ran_ok=0; break; }
done
if [ "$ran_ok" = 1 ]; then
  secs=$((SECONDS - t0))
  echo "yt-dlp $v (second start: ${secs} s)"
  [ "$secs" -le 15 ] || { echo "yt-dlp needs ${secs} s per start (onefile build?)"; bad=$((bad + 1)); }
fi
v="$("$B/deno" --version 2>&1)" && echo "${v%%$'\n'*}" || { echo "deno FAILED: $v"; bad=$((bad + 1)); }

# core.paths.bundled_binary() resolves tools via dirname(sys.executable)/bin,
# i.e. Contents/MacOS/bin/ -- NOT the Contents/Frameworks/bin/ copies above.
# PyInstaller symlinks ffmpeg/ffprobe/ffplay there automatically; yt-dlp is
# copied in post-BUNDLE by the spec and must get a matching symlink, or the
# real app's downloads silently fall back to a missing "yt-dlp" on PATH
# (the 2026-09-24 regression). Check the exact path the app actually uses.
RB="$APP/Contents/MacOS/bin"
for _n in ffmpeg yt-dlp deno; do
  [ -f "$RB/$_n" ] || { echo "RUNTIME-PATH $RB/$_n missing (core.paths.bundled_binary would fall back to PATH)"; bad=$((bad + 1)); }
done
# clear_bundled_quarantine() walks this dir; it must reach the onedir files.
[ -d "$RB/yt-dlp_dist/_internal" ] || { echo "RUNTIME-PATH $RB/yt-dlp_dist missing (quarantine clear would miss yt-dlp's files)"; bad=$((bad + 1)); }
"$APP/Contents/MacOS/Whisper Transcriber Suite" transcribe --help >/dev/null || { echo "CLI boot FAILED"; bad=$((bad + 1)); }
codesign --verify --deep --strict "$APP" || bad=$((bad + 1))
plutil -lint "$APP/Contents/Info.plist" >/dev/null || { echo "Info.plist does not parse"; bad=$((bad + 1)); }
# macOS 10.14+ (TCC) terminates an app that opens the microphone without this
# key; the Live tab records through sounddevice. The spec sets it.
/usr/libexec/PlistBuddy -c 'Print :NSMicrophoneUsageDescription' "$APP/Contents/Info.plist" >/dev/null 2>&1 \
  || { echo "Info.plist lacks NSMicrophoneUsageDescription (the Live tab would be killed by TCC)"; bad=$((bad + 1)); }

[ "$bad" = 0 ] && echo "OK: bundle is self-contained." || { echo "FAILED: $bad problem(s)" >&2; exit 1; }
