#!/usr/bin/env bash
# End-to-end smoke test of a BUILT "Whisper Transcriber Suite.app" — the
# checks that matter to a user, not just "the bundle exists":
#   1. real speech (macOS `say`) -> WAV + MP4 made with the app's OWN ffmpeg
#   2. a Whisper model fetched with the app's own core.model_manager
#   3. the frozen app's CLI transcribes the WAV and the MP4 with an EMPTY
#      PATH (so nothing from Homebrew/the system can mask a missing binary),
#      and the transcript must contain the spoken words
#   4. the GUI launches through LaunchServices (`open`) and logs its startup
#   5. (best-effort) the RUNTIME-resolved yt-dlp/ffmpeg (core.paths.bundled_binary(), i.e.
#      Contents/MacOS/bin/ -- what the app itself actually calls, not the
#      Contents/Frameworks/bin/ copies) perform a real download + ffmpeg
#      merge of a short public video end-to-end. Hard failure, not
#      best-effort: this is the exact path a 2026-09-24 regression broke
#      (yt-dlp had no Contents/MacOS/bin symlink, so every real download in
#      the packaged app silently fell back to a missing "yt-dlp" on PATH).
#
# Usage: bash platform/macos/pyinstaller/smoke_test_app.sh [app] [python-with-repo-deps] [model-slug]
# The user's WhisperTranscriberSuite config.json is backed up and restored.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../../.." && pwd)"
REPO="$PWD"

APP="${1:-dist/Whisper Transcriber Suite.app}"
PY="${2:-python3}"
MODEL="${3:-tiny}"
case "$APP" in /*) ;; *) APP="$REPO/$APP" ;; esac
BIN="$APP/Contents/MacOS/Whisper Transcriber Suite"
TOOLS="$APP/Contents/Frameworks/bin"
# The path the app itself resolves at runtime via core.paths.bundled_binary()
# (core.paths.resource_base() = dirname(sys.executable) = Contents/MacOS/).
RUNTIME_BIN="$APP/Contents/MacOS/bin"
CFG_DIR="$HOME/Library/Application Support/WhisperTranscriberSuite"
LOG_DIR="$HOME/Library/Logs/WhisperTranscriberSuite"
WORK="$(mktemp -d)"
fail=0

cleanup() {
  pkill -f "$APP/Contents/MacOS/" 2>/dev/null || true
  if [ -f "$WORK/config.json.bak" ]; then cp "$WORK/config.json.bak" "$CFG_DIR/config.json"; fi
  rm -rf "$WORK"
}
trap cleanup EXIT
mkdir -p "$CFG_DIR"
[ -f "$CFG_DIR/config.json" ] && cp "$CFG_DIR/config.json" "$WORK/config.json.bak"

echo "== 1. test media (say + bundled ffmpeg)"
SENTENCE="The quick brown fox jumps over the lazy dog. Whisper Transcriber Suite is now running on a Mac."
say -o "$WORK/sample.aiff" "$SENTENCE"
"$TOOLS/ffmpeg" -hide_banner -loglevel error -y -i "$WORK/sample.aiff" "$WORK/sample.wav"
"$TOOLS/ffmpeg" -hide_banner -loglevel error -y -f lavfi -i color=c=black:s=320x240:d=10 \
  -i "$WORK/sample.wav" -shortest -c:v libx264 -c:a aac "$WORK/sample.mp4"
ls -la "$WORK"/sample.*

echo "== 2. model '$MODEL' via core.model_manager.ensure_model"
"$PY" - "$MODEL" <<'EOF'
import json, os, sys
sys.path.insert(0, os.getcwd())
from core.model_manager import resolve_model_entry, ensure_model
from core import config as c
entry = resolve_model_entry(sys.argv[1])
p = c.config_path()
cfg = json.load(open(p)) if os.path.exists(p) else {}
cfg["model"] = {k: entry[k] for k in ("name", "url", "md5", "hf_repo")}
os.makedirs(os.path.dirname(p), exist_ok=True)
json.dump(cfg, open(p, "w"), indent=2)
print("model ready:", ensure_model(c.load_config(fetch_online=False), status_cb=print))
EOF

echo "== 3. frozen CLI transcription with an empty PATH"
for media in sample.wav sample.mp4; do
  # Own folder per input: the app never overwrites existing outputs (a
  # second "sample.*" in the same folder would get "sample (1).srt").
  d="$WORK/run-${media##*.}"; mkdir -p "$d"; cp "$WORK/$media" "$d/"
  if env -i HOME="$HOME" PATH=/usr/bin:/bin "$BIN" transcribe "$d/$media" --formats srt --language en \
       > "$WORK/$media.log" 2>&1; then
    srt="$d/${media%.*}.srt"
    if grep -qi "quick brown fox" "$srt"; then
      echo "OK   $media -> $(tr '\n' ' ' < "$srt" | cut -c1-160)"
    else
      echo "FAIL $media: transcript does not contain the spoken words"; cat "$srt" || true; fail=1
    fi
    rm -f "$srt"
  else
    echo "FAIL $media: CLI exit $?"; tail -30 "$WORK/$media.log"; fail=1
  fi
  if grep -q "invalid choice" "$WORK/$media.log"; then
    echo "FAIL $media: a helper process re-entered the CLI parser"; fail=1
  fi
done

echo "== 4. GUI launch through LaunchServices"
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
  echo "OK   GUI started and is still running"
else
  echo "FAIL GUI did not start (or died)"; tail -30 "$LOG_DIR/app.log" 2>/dev/null || true; fail=1
fi
grep -iE "Traceback|ERROR" "$LOG_DIR/app.log" 2>/dev/null | tail -5 || true
pkill -f "$APP/Contents/MacOS/" 2>/dev/null || true

echo "== 5. runtime-resolved yt-dlp/ffmpeg: real download + merge (Contents/MacOS/bin)"
for _n in yt-dlp ffmpeg; do
  if [ ! -f "$RUNTIME_BIN/$_n" ]; then
    echo "FAIL $RUNTIME_BIN/$_n does not exist (or is a dangling symlink) -- this is exactly"
    echo "     the path core.paths.bundled_binary(\"$_n\") resolves at runtime"
    fail=1
  fi
done
if [ "$fail" = 0 ]; then
  dl_ok=0
  for _try in 1 2; do
    if "$RUNTIME_BIN/yt-dlp" --ffmpeg-location "$RUNTIME_BIN"          -f 'bv*[height<=360]+ba/b[height<=360]' --merge-output-format mp4          -o "$WORK/smoketest.%(ext)s"          "https://www.youtube.com/watch?v=jNQXAC9IVRw" 2>"$WORK/ytdlp.err"; then
      dl_ok=1; break
    fi
    echo "WARN download attempt $_try failed, retrying:"; tail -3 "$WORK/ytdlp.err"
  done
  if [ "$dl_ok" = 1 ] && [ -s "$WORK/smoketest.mp4" ]; then
    echo "OK   real download + ffmpeg merge produced $(du -h "$WORK/smoketest.mp4" | cut -f1)"
  elif [ -n "${GITHUB_ACTIONS:-}" ]; then
    # GitHub-hosted runner IPs are commonly YouTube-bot-blocked (see the
    # ERROR below) -- a known, pre-existing constraint of this environment,
    # not a sign the packaging is broken. The existence checks above already
    # hard-fail the exact regression class (missing runtime-path binary)
    # without touching the network, so treat the live-network leg as
    # best-effort here, same as the pre-2026-09-24 script did.
    echo "WARN real download failed on a CI runner (likely YouTube bot-blocking, not our bug):"
    tail -5 "$WORK/ytdlp.err" 2>/dev/null || true
  else
    echo "FAIL real download via the runtime-resolved binaries did not produce a file:"
    tail -10 "$WORK/ytdlp.err" 2>/dev/null || true
    fail=1
  fi
fi

[ "$fail" = 0 ] && echo "SMOKE TEST PASSED" || { echo "SMOKE TEST FAILED" >&2; exit 1; }
