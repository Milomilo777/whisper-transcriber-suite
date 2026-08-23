#!/usr/bin/env bash
# Whisper Transcriber Suite — Linux updater. Pulls the latest source (if this is a
# git checkout) and refreshes the virtualenv. The embeddable-style layout
# means an update is just new source + upgraded deps — no reinstall.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV="$REPO_ROOT/.venv"
cd "$REPO_ROOT"

if [ -d .git ]; then
  echo "[whisper] updating source (git pull)…"
  git pull --ff-only || echo "[whisper] git pull skipped/failed — update the source manually if needed."
fi

if [ -d "$VENV" ]; then
  # shellcheck disable=SC1091
  . "$VENV/bin/activate"
  python -m pip install --upgrade pip wheel >/dev/null
  python -m pip install --upgrade -r "$REPO_ROOT/requirements.txt" yt-dlp
  deactivate
  echo "[whisper] dependencies updated. Launch with: whisper-transcriber-suite"
else
  echo "[whisper] no virtualenv found — run platform/linux/install.sh first." >&2
  exit 1
fi
