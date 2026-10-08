#!/usr/bin/env bash
# Fetch SELF-CONTAINED macOS ffmpeg/ffprobe + yt-dlp + deno and the two speaker
# diarization models into ./bin for the PyInstaller .app build
# (whisper_project_mac.spec), then VERIFY them.
#
# Why not Homebrew: `brew install ffmpeg` gives an ffmpeg that links ~18
# dylibs under /opt/homebrew (or /usr/local), and PyInstaller does not bundle
# the dylibs of executables copied into bin/. The resulting .app only works on
# a Mac that happens to have the same Homebrew ffmpeg installed. Homebrew's
# bottles are also built for the runner's own macOS (minos 15.0 on macos-15),
# and there is no Intel-macOS ffmpeg bottle at all any more.
#
# Every download is pinned by version and SHA-256, like the Windows build
# (platform/windows/build-deps.json): a "latest" download changed what shipped
# between two builds of the same commit, and a newer ffmpeg can raise the
# app's minimum macOS. To move a pin, change the version AND its hash here
# (tests/test_mac_build_pins.py keeps yt-dlp, Deno and the diarization models
# in step with the Windows pins).
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

# ---- pins --------------------------------------------------------------------
# ffmpeg 9.0.2. x86_64: evermeet.cx static build (LC_VERSION_MIN_MACOSX 10.13).
# arm64: ffmpeg.martin-riedl.de static build (minos 12.0). Hashes computed from
# the downloads on 2026-10-08 (neither site publishes a checksum file).
FFMPEG_X86_64_URL="https://evermeet.cx/ffmpeg/ffmpeg-9.0.2.zip"
FFMPEG_X86_64_SHA256="4acc0be580f9b2788029eb7bd4d645ff87968911b0a62aeeb3940d42d54558d5"
FFPROBE_X86_64_URL="https://evermeet.cx/ffmpeg/ffprobe-9.0.2.zip"
FFPROBE_X86_64_SHA256="24a9c968cd4da72d99c7245e914b921815835eb6dff01d99868031aebaf1d439"
FFMPEG_ARM64_URL="https://ffmpeg.martin-riedl.de/download/macos/arm64/1789931890_9.0.2/ffmpeg.zip"
FFMPEG_ARM64_SHA256="c8ed4c4e6978a03c485edbfe4e0a5dc2380f8a30bba5150531b31b094492d924"
FFPROBE_ARM64_URL="https://ffmpeg.martin-riedl.de/download/macos/arm64/1789931890_9.0.2/ffprobe.zip"
FFPROBE_ARM64_SHA256="fcbe839537485eaee7a7a8bc5cbc0f90d53617e80943e8a5b2e31cb851197ea6"
# yt-dlp onedir build (universal2), hash from the release's SHA2-256SUMS.
YTDLP_VERSION="2026.08.19"
YTDLP_MACOS_ZIP_SHA256="07e54b0865303c864006925913bce2604f8ee8cc6f18699bac9c309f9328a6d8"
# Deno, hashes from the release's .sha256sum files.
DENO_VERSION="2.9.7"
DENO_X86_64_SHA256="95daaff11c116a52ad54785e7914c8e9c9cdcaba793c5ed929c74ca2d8e6259a"
DENO_AARCH64_SHA256="5cd46d6268f6f78f5d88bdc7159d20bd44cdaa4b3303474839f87ec6fe7ae25c"
# Speaker diarization models (core.diarization), the same files and hashes as
# the Windows build: Hugging Face LFS object ids at fixed revisions.
DIAR_SEGMENTATION_URL="https://huggingface.co/csukuangfj/sherpa-onnx-pyannote-segmentation-3-0/resolve/9403a6902bb58e3d5ae8c7e77c3422de279db2e0/model.onnx"
DIAR_SEGMENTATION_SHA256="220ad67ca923bef2fa91f2390c786097bf305bceb5e261d4af67b38e938e1079"
DIAR_EMBEDDING_URL="https://huggingface.co/csukuangfj/speaker-embedding-models/resolve/0743f301363dec56491a490f6d6cbc9d67f9a3bf/3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx"
DIAR_EMBEDDING_SHA256="357a834f702b80161e5b981182c038e18553c1f2ca752ed6cec2052365d4129b"

fetch_checked() {  # fetch_checked <url> <sha256> <dest>
  # Download into $TMP and move into place only after the hash matched, so a
  # bad download never leaves a file at <dest> for the spec to bundle.
  local part="$TMP/fetch.part" got
  curl -fsSL --retry 3 "$1" -o "$part"
  got="$(shasum -a 256 "$part" | cut -d' ' -f1)"
  [ "$got" = "$2" ] || { echo "error: $1 checksum mismatch (want $2, got $got)" >&2; exit 1; }
  mv -f "$part" "$3"
}

fetch_zip() {  # fetch_zip <url> <sha256> <member> <dest>
  fetch_checked "$1" "$2" "$TMP/dl.zip"
  rm -rf "$TMP/x" && mkdir -p "$TMP/x"
  unzip -oq "$TMP/dl.zip" -d "$TMP/x"
  local f
  f="$(find "$TMP/x" -type f -name "$3" | head -1)"
  [ -n "$f" ] || { echo "error: $3 not found in $1" >&2; exit 1; }
  rm -f "$4"  # an old copy may be read-only (Homebrew installs its tools 0555)
  cp "$f" "$4"
  chmod +x "$4"
}

fetch_tool() {  # fetch_tool <ffmpeg|ffprobe> <x86_64|arm64> <dest>
  local key url sha
  key="$(echo "$1_$2" | tr '[:lower:]' '[:upper:]')"
  url="${key}_URL"; sha="${key}_SHA256"
  [ -n "${!url:-}" ] || { echo "error: no pinned $1 for $2" >&2; exit 1; }
  fetch_zip "${!url}" "${!sha}" "$1" "$3"
}

# ffplay is not used by the app (it served the removed Video Tiling feature):
# drop a copy left by an older fetch so the spec does not bundle it.
rm -f "$BIN/ffplay"
for t in ffmpeg ffprobe; do
  if [ "$ARCH" = "universal2" ]; then
    fetch_tool "$t" x86_64 "$TMP/$t.x86_64"
    fetch_tool "$t" arm64 "$TMP/$t.arm64"
    rm -f "$BIN/$t"
    lipo -create "$TMP/$t.x86_64" "$TMP/$t.arm64" -output "$BIN/$t"
    chmod +x "$BIN/$t"
  else
    fetch_tool "$t" "$ARCH" "$BIN/$t"
  fi
done

# yt-dlp: the official ONEDIR build (yt-dlp_macos.zip, universal2): the
# yt-dlp_macos executable next to its _internal/ folder, unpacked once into
# bin/yt-dlp_dist/. The onefile yt-dlp_macos unpacked itself into a new temp
# dir on every run, and dyld re-validated those fresh libraries each time:
# 25-29 s per start (66 s cold). The onedir build pays that once, then starts
# in about 0.5 s (both measured on macOS 10.15). bin/yt-dlp is a relative
# symlink to the executable -- the name core.paths.bundled_binary("yt-dlp")
# resolves; the PyInstaller bootloader follows symlinks to find _internal/.
# ditto keeps the exec bits.
fetch_checked "https://github.com/yt-dlp/yt-dlp/releases/download/$YTDLP_VERSION/yt-dlp_macos.zip" \
  "$YTDLP_MACOS_ZIP_SHA256" "$TMP/yt-dlp_macos.zip"
rm -rf "${BIN:?}/yt-dlp" "${BIN:?}/yt-dlp_dist"
ditto -x -k "$TMP/yt-dlp_macos.zip" "$BIN/yt-dlp_dist"
[ -x "$BIN/yt-dlp_dist/yt-dlp_macos" ] && [ -d "$BIN/yt-dlp_dist/_internal" ] \
  || { echo "error: yt-dlp_macos.zip lacks yt-dlp_macos + _internal/" >&2; exit 1; }
ln -s yt-dlp_dist/yt-dlp_macos "$BIN/yt-dlp"

# Deno: yt-dlp's JavaScript runtime for YouTube's challenges. Bundled next to
# yt-dlp so the app needs no "Install YouTube helper" click
# (core.js_runtime.find_deno checks bin/ first). Official release zip.
fetch_deno() {  # fetch_deno <x86_64|aarch64> <sha256> <dest>
  local zip="deno-$1-apple-darwin.zip"
  fetch_checked "https://github.com/denoland/deno/releases/download/v$DENO_VERSION/$zip" "$2" "$TMP/$zip"
  rm -rf "$TMP/deno-x" && unzip -oq "$TMP/$zip" deno -d "$TMP/deno-x"
  rm -f "$3"
  cp "$TMP/deno-x/deno" "$3"
  chmod +x "$3"
}
case "$ARCH" in
  x86_64) fetch_deno x86_64 "$DENO_X86_64_SHA256" "$BIN/deno" ;;
  arm64)  fetch_deno aarch64 "$DENO_AARCH64_SHA256" "$BIN/deno" ;;
  universal2)
    fetch_deno x86_64 "$DENO_X86_64_SHA256" "$TMP/deno.x86_64"
    fetch_deno aarch64 "$DENO_AARCH64_SHA256" "$TMP/deno.arm64"
    rm -f "$BIN/deno"
    lipo -create "$TMP/deno.x86_64" "$TMP/deno.arm64" -output "$BIN/deno"
    chmod +x "$BIN/deno" ;;
  *) echo "error: unknown arch $ARCH" >&2; exit 1 ;;
esac

# Diarization models: plain data files, the spec bundles bin/diarization/ as a
# folder (core.diarization looks for bin/diarization/*.onnx).
mkdir -p "$BIN/diarization"
fetch_checked "$DIAR_SEGMENTATION_URL" "$DIAR_SEGMENTATION_SHA256" "$BIN/diarization/segmentation.onnx"
fetch_checked "$DIAR_EMBEDDING_URL" "$DIAR_EMBEDDING_SHA256" "$BIN/diarization/embedding.onnx"
xattr -dr com.apple.quarantine "$BIN" 2>/dev/null || true

# ---- verify ----------------------------------------------------------------
fail=0
for f in "$BIN"/ffmpeg "$BIN"/ffprobe "$BIN"/yt-dlp "$BIN"/deno; do
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
"$BIN/yt-dlp" --version >/dev/null  # first run: dyld validates the new files once
t0=$(date +%s); v="$("$BIN/yt-dlp" --version)"; t1=$(date +%s)
echo "yt-dlp $v (second start: $((t1 - t0)) s)"
"$BIN/deno" --version | head -1
ls -l "$BIN/diarization"
[ "$fail" = 0 ] || { echo "error: bin/ contains dylib-dependent binaries" >&2; exit 1; }
echo "OK: bin/ is self-contained."
