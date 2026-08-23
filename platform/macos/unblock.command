#!/usr/bin/env bash
# Whisper Transcriber Suite — macOS Gatekeeper unblock helper.
#
# If you downloaded the repo through a browser, macOS tags the files with
# com.apple.quarantine and Gatekeeper blocks the unsigned launchers. This
# strips that flag from the repo + the installed launcher so they open.
# (Files obtained via git clone / curl are not quarantined and don't need
# this.)
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "[whisper] removing the quarantine flag from the repo…"
xattr -dr com.apple.quarantine "$REPO_ROOT" 2>/dev/null || true
APP="$HOME/Applications/Whisper Transcriber Suite.app"
[ -e "$APP" ] && xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true
echo "[whisper] done. Try opening the app again."
echo "[whisper] still blocked? System Settings → Privacy & Security → 'Open Anyway'."
