#!/usr/bin/env bash
# Fetch SELF-CONTAINED macOS ffmpeg/ffprobe/ffplay + yt-dlp into ./bin for the
# PyInstaller .app build (whisper_project_mac.spec), then VERIFY them.
#
# Why not Homebrew: `brew install ffmpeg` gives an ffmpeg that links ~18
# dylibs under /opt/homebrew (or /usr/local), and PyInstaller does not bundle
# the dylibs of executables copied into bin/. The resulting .app only works on
# a Mac that happens to have the same Homebrew ffmpeg installed. Homebrew's
# bottles are also built for the runner's own macOS (minos 15.0 on macos-15),
# and there is no Intel-macOS ffmpeg bottle at all any more.
#
# Usage:  bash platform/macos/pyinstaller/fetch_mac_binaries.sh [x86_64|arm64|universal2]
#         (default: the host arch, from uname -m)
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../../.." && pwd)"

ARCH="${1:-$(uname -m)}"
BIN="bin"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$BIN"

fetch_zip() {  # fetch_zip <url> <member> <dest>
  curl -fsSL --retry 3 "$1" -o "$TMP/dl.zip"
  rm -rf "$TMP/x" && mkdir -p "$TMP/x"
  unzip -oq "$TMP/dl.zip" -d "$TMP/x"
  local f
  f="$(find "$TMP/x" -type f -name "$2" | head -1)"
  [ -n "$f" ] || { echo "error: $2 not found in $1" >&2; exit 1; }
  cp "$f" "$3"
  chmod +x "$3"
}

fetch_tool() {  # fetch_tool <name> <arch> <dest>
  case "$2" in
    # evermeet.cx: long-standing static x86_64 builds (min macOS 10.13).
    x86_64) fetch_zip "https://evermeet.cx/ffmpeg/getrelease/$1/zip" "$1" "$3" ;;
    # martin-riedl.de: static builds for Apple Silicon.
    arm64)  fetch_zip "https://ffmpeg.martin-riedl.de/redirect/latest/macos/arm64/release/$1.zip" "$1" "$3" ;;
    *) echo "error: unknown arch $2" >&2; exit 1 ;;
  esac
}

for t in ffmpeg ffprobe ffplay; do
  if [ "$ARCH" = "universal2" ]; then
    fetch_tool "$t" x86_64 "$TMP/$t.x86_64"
    fetch_tool "$t" arm64 "$TMP/$t.arm64"
    lipo -create "$TMP/$t.x86_64" "$TMP/$t.arm64" -output "$BIN/$t"
    chmod +x "$BIN/$t"
  else
    fetch_tool "$t" "$ARCH" "$BIN/$t"
  fi
done

# yt-dlp_macos is already universal2. Keep the name "yt-dlp": that is what
# core.paths.bundled_binary("yt-dlp") resolves on macOS.
curl -fsSL --retry 3 -o "$BIN/yt-dlp" \
  "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos"
chmod +x "$BIN/yt-dlp"
xattr -dr com.apple.quarantine "$BIN" 2>/dev/null || true

# ---- verify ----------------------------------------------------------------
fail=0
for f in "$BIN"/ffmpeg "$BIN"/ffprobe "$BIN"/ffplay "$BIN"/yt-dlp; do
  # otool prints one "<file> (architecture X):" header per slice of a fat file; drop them all.
  ext="$(otool -L "$f" | grep -v ':$' | grep -vE '^[[:space:]]*(/usr/lib/|/System/Library/)' || true)"
  minos="$(otool -l "$f" | awk '/LC_BUILD_VERSION/{b=1} b&&/minos/{print $2; exit} /LC_VERSION_MIN_MACOSX/{v=1} v&&/ version/{print $2; exit}')"
  printf '%-14s archs=%-14s minos=%s\n' "$(basename "$f")" "$(lipo -archs "$f")" "${minos:-?}"
  if [ -n "$ext" ]; then
    echo "  ERROR: links non-system libraries:" >&2
    echo "$ext" >&2
    fail=1
  fi
done
"$BIN/ffmpeg" -hide_banner -version | head -1
echo "yt-dlp $("$BIN/yt-dlp" --version)"
[ "$fail" = 0 ] || { echo "error: bin/ contains dylib-dependent binaries" >&2; exit 1; }
echo "OK: bin/ is self-contained."
