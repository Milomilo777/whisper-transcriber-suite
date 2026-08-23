#!/usr/bin/env bash
# Whisper Transcriber Suite — macOS installer (double-clickable .command).
#
# Same idea as the Linux installer: a self-contained virtualenv next to the
# repo, deps + yt-dlp, a static ffmpeg when the system has none, and two
# launchers (a double-clickable "Whisper Transcriber Suite.command" for the GUI and a
# "whisper-transcribe" CLI for headless use).
#
# Gatekeeper: this app is UNSIGNED (no paid Apple Developer cert). The
# cleanest way to avoid Gatekeeper entirely is to get the repo via
# `git clone` or `curl` and run this from Terminal — files fetched that way
# are NOT quarantined. As a belt-and-braces step this script also strips the
# quarantine flag from the repo folder. See README.md for the full story.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
if [ ! -f "$REPO_ROOT/gui.py" ]; then
  echo "error: gui.py not found at $REPO_ROOT — run this from inside the repo checkout." >&2
  exit 1
fi
VENV="$REPO_ROOT/.venv"
APPS_DIR="$HOME/Applications"
BIN_LOCAL="$HOME/.local/bin"

say() { printf '\033[1;36m[whisper]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[whisper] WARN:\033[0m %s\n' "$*" >&2; }

# ---- de-quarantine the repo so Gatekeeper doesn't block our own scripts.
xattr -dr com.apple.quarantine "$REPO_ROOT" 2>/dev/null || true

# ---- python (need a GOOD Tk for the GUI; headless CLI works without it) --
# Prefer a python.org / Homebrew Python over Apple's system python3: the
# system one historically links Apple's deprecated Tcl/Tk 8.5, which
# *imports* fine but renders a blurry/unstable GUI. We therefore check the
# Tk PATCH version, not just that tkinter imports.
PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for cand in /usr/local/bin/python3 /opt/homebrew/bin/python3 python3; do
    if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
  done
fi
if [ -z "$PY" ] || ! command -v "$PY" >/dev/null 2>&1; then
  echo "error: python3 not found. Install Python 3.11+ from https://www.python.org/downloads/macos/ (its installer includes a good Tk)." >&2
  exit 1
fi
PYVER="$("$PY" -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
say "using Python $PYVER at $("$PY" -c 'import sys;print(sys.executable)')"
TKVER="$("$PY" -c 'import tkinter;print(tkinter.TkVersion)' 2>/dev/null || echo none)"
if [ "$TKVER" = "none" ]; then
  warn "tkinter missing — the GUI won't start. Use the python.org build (bundles Tk 8.6)"
  warn "or 'brew install python-tk'. The headless CLI works without it."
elif [ "$TKVER" = "8.5" ]; then
  warn "this Python links Tk 8.5 (Apple's deprecated build) — the GUI will look"
  warn "blurry/unstable. Strongly prefer the python.org Python (Tk 8.6):"
  warn "    https://www.python.org/downloads/macos/  then: PYTHON=/usr/local/bin/python3 bash platform/macos/install.command"
else
  say "Tk $TKVER OK"
fi

# ---- venv + deps --------------------------------------------------------
# Rebuild from scratch so a re-run after switching Python (e.g. Apple →
# python.org) doesn't silently reuse a stale venv built against the old Tk.
say "creating virtualenv at $VENV"
rm -rf "$VENV"
"$PY" -m venv "$VENV"
# shellcheck disable=SC1091
. "$VENV/bin/activate"
python -m pip install --upgrade pip wheel >/dev/null
say "installing dependencies (a few minutes)…"
python -m pip install -r "$REPO_ROOT/requirements.txt"
python -m pip install --upgrade yt-dlp

# ---- ffmpeg -------------------------------------------------------------
# Always materialise ffmpeg/ffprobe/ffplay INTO bin/ (symlink), even when
# they come from the system or Homebrew. The .app launcher sets
# PATH="$REPO_ROOT/bin:$VENV/bin:$PATH", but a Finder/LaunchServices-launched
# .app inherits only the minimal /usr/bin:/bin PATH — NOT /opt/homebrew/bin
# or /usr/local/bin — so without the symlink core.paths.bundled_binary()
# falls back to the bare "ffmpeg" name and the GUI worker can't find it.
# ffplay (no .exe on macOS — core.paths.bundled_binary() drops the suffix off
# Windows) is what the Video Tiling tab needs; brew's ffmpeg ships it, so we
# link it too when present (it is missing from some minimal static builds —
# the tab then shows its clear "add ffplay" message / Download ffplay button).
link_ffmpeg_into_bin() {
  local f p
  for f in ffmpeg ffprobe ffplay; do
    p="$(command -v "$f" 2>/dev/null || true)"
    [ -n "$p" ] && ln -sf "$p" "$REPO_ROOT/bin/$f"
  done
}
mkdir -p "$REPO_ROOT/bin"
if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
  say "system ffmpeg/ffprobe found: $(command -v ffmpeg)"
  link_ffmpeg_into_bin
elif command -v brew >/dev/null 2>&1; then
  say "installing ffmpeg via Homebrew…"
  brew install ffmpeg || warn "brew install ffmpeg failed — install it manually."
  # Re-resolve after the install so the freshly-installed binaries are linked.
  link_ffmpeg_into_bin
else
  if [ "$(uname -m)" = "arm64" ]; then
    warn "no Homebrew on Apple Silicon: the static ffmpeg below is Intel"
    warn "(x86_64) and needs Rosetta 2 (softwareupdate --install-rosetta)."
    warn "Better: install Homebrew then 'brew install ffmpeg' for a native build."
  fi
  say "no ffmpeg + no Homebrew — fetching a static build into bin/…"
  TMP="$(mktemp -d)"
  ok=1
  curl -fsSL "https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip" -o "$TMP/ffmpeg.zip" || ok=0
  curl -fsSL "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip" -o "$TMP/ffprobe.zip" || ok=0
  if [ "$ok" = 1 ]; then
    # Non-fatal under `set -e`: a truncated-but-HTTP-200 download can make
    # unzip exit non-zero, which would otherwise abort the whole installer
    # before the friendly warn below ever runs.
    (cd "$TMP" && unzip -oq ffmpeg.zip && unzip -oq ffprobe.zip) || ok=0
    cp "$TMP/ffmpeg" "$TMP/ffprobe" "$REPO_ROOT/bin/" 2>/dev/null || ok=0
    chmod +x "$REPO_ROOT/bin/ffmpeg" "$REPO_ROOT/bin/ffprobe" 2>/dev/null || true
    xattr -dr com.apple.quarantine "$REPO_ROOT/bin" 2>/dev/null || true
  fi
  [ "$ok" = 1 ] && say "installed static ffmpeg + ffprobe into bin/" || \
    warn "static ffmpeg fetch failed — install Homebrew then 'brew install ffmpeg'."
  # ffplay too (separate evermeet zip) so Video Tiling works on this path.
  # Best-effort + non-fatal: a missing ffplay only disables that one tab,
  # and the app's "Download ffplay" button can fetch it later.
  ffplay_ok=1
  curl -fsSL "https://evermeet.cx/ffmpeg/getrelease/ffplay/zip" -o "$TMP/ffplay.zip" || ffplay_ok=0
  if [ "$ffplay_ok" = 1 ]; then
    (cd "$TMP" && unzip -oq ffplay.zip) || ffplay_ok=0
    cp "$TMP/ffplay" "$REPO_ROOT/bin/" 2>/dev/null || ffplay_ok=0
    chmod +x "$REPO_ROOT/bin/ffplay" 2>/dev/null || true
    xattr -dr com.apple.quarantine "$REPO_ROOT/bin/ffplay" 2>/dev/null || true
  fi
  [ "$ffplay_ok" = 1 ] && say "installed static ffplay into bin/ (Video Tiling)" || \
    warn "ffplay fetch failed — Video Tiling will offer a 'Download ffplay' button."
fi
deactivate

# ---- launcher: a real .app bundle (no lingering Terminal window) --------
# Built locally, so it carries no com.apple.quarantine flag and opens
# without a Gatekeeper prompt — same security posture as a .command but a
# proper double-clickable app with a Dock icon and no Terminal window.
mkdir -p "$APPS_DIR" "$BIN_LOCAL"
APP="$APPS_DIR/Whisper Transcriber Suite.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cat > "$APP/Contents/MacOS/whisper-transcriber-suite" <<EOF
#!/bin/bash
export PATH="$REPO_ROOT/bin:$VENV/bin:\$PATH"
exec "$VENV/bin/python" "$REPO_ROOT/gui.py"
EOF
chmod +x "$APP/Contents/MacOS/whisper-transcriber-suite"
cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Whisper Transcriber Suite</string>
  <key>CFBundleDisplayName</key><string>Whisper Transcriber Suite</string>
  <key>CFBundleIdentifier</key><string>com.translation-robot.whisperproject</string>
  <key>CFBundleVersion</key><string>1.3.6</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>whisper-transcriber-suite</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
EOF
# Ad-hoc sign the bundle ('-s -') so it has a STABLE code identity. Without
# this an unsigned app's TCC grants (Files & Folders, Desktop/Downloads)
# reset whenever the binary changes — e.g. on every re-install. Harmless if
# codesign is unavailable.
codesign --force --deep -s - "$APP" 2>/dev/null || true

# Headless CLI for servers / scripting.
cat > "$BIN_LOCAL/whisper-transcribe" <<EOF
#!/usr/bin/env bash
export PATH="$REPO_ROOT/bin:$VENV/bin:\$PATH"
exec "$VENV/bin/python" "$REPO_ROOT/gui.py" transcribe "\$@"
EOF
chmod +x "$BIN_LOCAL/whisper-transcribe"
say "installed app: $APP"
say "installed CLI: $BIN_LOCAL/whisper-transcribe"

echo
say "Done."
say "Desktop app : double-click \"Whisper Transcriber Suite\" in ~/Applications"
say "              (or: open \"$APP\")"
say "Server / CLI: whisper-transcribe /path/to/media.mp4 --formats srt json"
say "              (add ~/.local/bin to PATH in ~/.zshrc if 'whisper-transcribe' isn't found)"
say "LAN / web   : \"$VENV/bin/python\" \"$REPO_ROOT/gui.py\" serve --lan"
say "              (browser transcription/download over the local network)"
say "Also in-app : Video Tiling video-wall, cloud STT backends (Gemini key /"
say "              Google Cloud service-account), SMTV transcription .docx"
say "              export, and File > Convert transcript (SRT/VTT/TSV/JSON/TXT)."
say "If macOS still blocks the app, see platform/macos/README.md or run:"
say "    bash platform/macos/unblock.command"
