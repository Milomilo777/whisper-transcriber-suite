#!/usr/bin/env bash
# Whisper Transcriber Suite — Linux uninstaller. Removes the launchers, the desktop
# entry, and the virtualenv. Leaves the repo checkout and your user data
# (config + downloaded models under ~/.config and ~/.cache) untouched.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
if [ ! -f "$REPO_ROOT/gui.py" ]; then
  echo "error: gui.py not found at $REPO_ROOT — run this script from inside the repo checkout." >&2
  exit 1
fi

rm -f "$HOME/.local/bin/whisper-transcriber-suite" "$HOME/.local/bin/whisper-transcribe"
rm -f "$HOME/.local/share/applications/whisper-transcriber-suite.desktop"
rm -rf "$REPO_ROOT/.venv"

echo "[whisper] removed launchers, desktop entry, and the virtualenv."
echo "[whisper] kept: the repo checkout + your config/models under ~/.config and ~/.cache."
echo "[whisper] to wipe those too: rm -rf ~/.config/WhisperTranscriberSuite ~/.cache/WhisperTranscriberSuite"
