# AGENTS.md — Whisper Transcriber Suite

Instructions for AI coding agents (Claude Code, Codex, Cursor, Copilot, …) and CI.

- Project-specific Claude guidance lives in `CLAUDE.md`.

## Build and test

- Setup: `pip install -r requirements.txt` and `pip install pyright pytest`.
- Gate before every commit: `run_tests.bat` (Windows), or by hand:
  `python -m pyright app core` (0 errors, 0 warnings) and
  `python -m pytest tests/ --ignore=tests/smoke` (hermetic suite, must pass).
- `tests/smoke/` needs a real Whisper model and a test video; see `docs/TESTING.md`.
- Windows build and release steps: `docs/BUILD.md`, `docs/RELEASE_PROCESS.md`.
