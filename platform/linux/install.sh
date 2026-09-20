#!/usr/bin/env bash
# Whisper Transcriber Suite — Linux installer.
#
# Installs IN PLACE from a checkout of the repo: creates a virtualenv,
# installs the Python deps + yt-dlp, fetches a static ffmpeg/ffprobe when
# the system has none, and drops two launchers + a desktop entry:
#
#   whisper-transcriber-suite      → the desktop app  (needs python3-tk + a display)
#   whisper-transcribe   → headless CLI     (works on a server, no display)
#
# Re-run any time to update the venv after a `git pull` (idempotent), or
# use ./platform/linux/update.sh.
#
# One-liner (only works if the repo is reachable — public, or with a token
# baked into the URL; this repo is private, so the normal path is to clone
# it first and run this script from the checkout):
#   curl -fsSL <raw-url>/platform/linux/install.sh | bash
set -euo pipefail

# ---------------------------------------------------------------- paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
if [ ! -f "$REPO_ROOT/gui.py" ]; then
  echo "error: gui.py not found at $REPO_ROOT — run this script from inside the repo checkout." >&2
  exit 1
fi
VENV="$REPO_ROOT/.venv"
BIN_LOCAL="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_SRC="$REPO_ROOT/assets/whisper.png"

say() { printf '\033[1;36m[whisper]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[whisper] WARN:\033[0m %s\n' "$*" >&2; }

# ---------------------------------------------------------------- python
PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "error: python3 not found. Install Python 3.11+ (e.g. 'sudo apt install python3 python3-venv python3-pip')." >&2
  exit 1
fi
PYVER="$("$PY" -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
say "using Python $PYVER at $("$PY" -c 'import sys;print(sys.executable)')"
"$PY" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,11) else 1)' || {
  warn "Python $PYVER is older than 3.11 — the app targets 3.11+. Continuing, but upgrade if you hit issues."
}

# tkinter is needed ONLY for the GUI; the headless CLI runs without it.
if ! "$PY" -c 'import tkinter' >/dev/null 2>&1; then
  warn "python3-tk (tkinter) is missing — the GUI won't start. Install it for the desktop app:"
  warn "    Debian/Ubuntu: sudo apt install python3-tk"
  warn "    Fedora:        sudo dnf install python3-tkinter"
  warn "    Arch:          sudo pacman -S tk"
  warn "The headless 'whisper-transcribe' command works without it."
fi

# ---------------------------------------------------------------- venv
say "creating virtualenv at $VENV"
"$PY" -m venv "$VENV"
# shellcheck disable=SC1091
. "$VENV/bin/activate"
python -m pip install --upgrade pip wheel >/dev/null
say "installing Python dependencies (this can take a few minutes)…"
python -m pip install -r "$REPO_ROOT/requirements.txt"
# yt-dlp ships as a binary on Windows; on Linux pull it from PyPI so the
# Download tab + the URL handoff work. Lives in the venv's bin/.
python -m pip install --upgrade yt-dlp

# ---------------------------------------------------------------- ffmpeg
mkdir -p "$REPO_ROOT/bin"
if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
  say "system ffmpeg/ffprobe found: $(command -v ffmpeg)"
else
  ARCH="$(uname -m)"
  case "$ARCH" in
    x86_64|amd64) FF_ARCH="amd64" ;;
    aarch64|arm64) FF_ARCH="arm64" ;;
    *) FF_ARCH="" ;;
  esac
  if [ -n "$FF_ARCH" ]; then
    say "no system ffmpeg — fetching a static build ($FF_ARCH) into bin/…"
    TMP="$(mktemp -d)"
    trap 'rm -rf "$TMP"' EXIT
    URL="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-${FF_ARCH}-static.tar.xz"
    if curl -fsSL "$URL" -o "$TMP/ffmpeg.tar.xz" && tar -xf "$TMP/ffmpeg.tar.xz" -C "$TMP"; then
      D="$(find "$TMP" -maxdepth 1 -type d -name 'ffmpeg-*-static' | head -n1)"
      if [ -n "$D" ]; then
        cp "$D/ffmpeg" "$D/ffprobe" "$REPO_ROOT/bin/"
        chmod +x "$REPO_ROOT/bin/ffmpeg" "$REPO_ROOT/bin/ffprobe"
        say "installed ffmpeg + ffprobe into $REPO_ROOT/bin"
      else
        warn "unexpected static ffmpeg archive layout — install it with your package manager (e.g. 'sudo apt install ffmpeg')."
      fi
    else
      warn "static ffmpeg download failed — install it with your package manager (e.g. 'sudo apt install ffmpeg')."
    fi
    rm -rf "$TMP"
  else
    warn "unknown CPU arch '$ARCH' — install ffmpeg with your package manager (e.g. 'sudo apt install ffmpeg')."
  fi
fi
deactivate

# ---------------------------------------------------------------- launchers
mkdir -p "$BIN_LOCAL"
# GUI launcher — activates the venv, puts the venv + repo bin on PATH so
# yt-dlp / ffmpeg resolve, then runs the app.
cat > "$BIN_LOCAL/whisper-transcriber-suite" <<EOF
#!/usr/bin/env bash
export PATH="$REPO_ROOT/bin:$VENV/bin:\$PATH"
exec "$VENV/bin/python" "$REPO_ROOT/gui.py" "\$@"
EOF
chmod +x "$BIN_LOCAL/whisper-transcriber-suite"
# Headless CLI launcher for servers: whisper-transcribe FILE [--language ..]
cat > "$BIN_LOCAL/whisper-transcribe" <<EOF
#!/usr/bin/env bash
export PATH="$REPO_ROOT/bin:$VENV/bin:\$PATH"
exec "$VENV/bin/python" "$REPO_ROOT/gui.py" transcribe "\$@"
EOF
chmod +x "$BIN_LOCAL/whisper-transcribe"
say "installed launchers: $BIN_LOCAL/whisper-transcriber-suite and whisper-transcribe"

# ---------------------------------------------------------------- desktop entry
mkdir -p "$DESKTOP_DIR"
cat > "$DESKTOP_DIR/whisper-transcriber-suite.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Whisper Transcriber Suite
Comment=Offline transcription + subtitle downloader
Exec="$BIN_LOCAL/whisper-transcriber-suite"
Icon=$ICON_SRC
Terminal=false
Categories=AudioVideo;Audio;Utility;
EOF
say "installed desktop entry"

# ---------------------------------------------------------------- done
echo
say "Done. If $BIN_LOCAL isn't on your PATH, add this to ~/.bashrc:"
echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
echo
say "Desktop app : whisper-transcriber-suite"
say "Server / CLI: whisper-transcribe /path/to/media.mp4 --formats srt json"
say "Update later: ./platform/linux/update.sh   (or re-run this installer)"
