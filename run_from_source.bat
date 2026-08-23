@echo off
REM ===================================================================
REM  run_from_source.bat  -  always-up-to-date launcher for this repo.
REM
REM  Unlike embed_build\Run Whisper Transcriber Suite.bat (a frozen, packaged
REM  snapshot that only changes when someone deliberately rebuilds
REM  it), this launches the app DIRECTLY from this git checkout. Any
REM  commit landed in this folder (by this Claude session, or a
REM  "git pull" from anywhere else) takes effect on the very next
REM  double-click -- no build step, no install.
REM
REM  Each run does a quick "git pull --ff-only" first, so you always
REM  get the latest source. Failures there (no git on PATH, local
REM  changes, a diverged branch) are non-fatal -- the app still
REM  launches with whatever source is currently on disk.
REM
REM  This does NOT refresh Python dependencies -- run
REM  platform\windows\update.bat instead when requirements.txt has
REM  changed (rare). One-time setup, if you have not already:
REM     pip install -r requirements.txt
REM ===================================================================
setlocal
cd /d "%~dp0"

where git >nul 2>&1
if not errorlevel 1 (
    if exist ".git" (
        echo [whisper] pulling latest source...
        git pull --ff-only
        if errorlevel 1 echo [whisper] WARNING: git pull failed - launching with the current source anyway.
    )
)

echo [whisper] starting...
python gui.py
endlocal
