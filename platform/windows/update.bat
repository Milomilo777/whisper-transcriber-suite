@echo off
REM ============================================================================
REM  Whisper Transcriber Suite - Windows updater for a SOURCE (git clone) install.
REM
REM  Mirrors platform/linux/update.sh: pull the latest source, then refresh
REM  the Python dependencies. An update is just new source + upgraded deps.
REM
REM  This is NOT for the installed app. If you used Setup-Standard.exe, do
REM  not run this - download the newer installer and run it, it upgrades in
REM  place. The app's own update check stays notify-only on purpose: an
REM  installed application that rewrites itself is a support nightmare, and
REM  a half-applied self-update leaves a user with nothing that runs.
REM  See core/updates.py and docs/INSTALL.md.
REM
REM  Usage:  double-click, or  platform\windows\update.bat
REM ============================================================================
setlocal EnableExtensions EnableDelayedExpansion

REM %~dp0 ends with a backslash; ..\.. walks up to the repo root.
set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%..\.." || (
    echo [whisper] ERROR: could not enter the repository root.
    exit /b 1
)
set "REPO_ROOT=%CD%"

echo [whisper] repository: %REPO_ROOT%
echo.

REM --- Refuse to touch a packaged install -----------------------------------
REM embed_build\ is the bundled-Python tree the installer ships. Running a
REM source update against it would mix a git checkout into a packaged app.
if not exist "%REPO_ROOT%\gui.py" (
    echo [whisper] ERROR: gui.py not found - this does not look like a
    echo           source checkout. If you installed with Setup-Standard.exe,
    echo           download the newer installer instead; it upgrades in place.
    popd
    exit /b 1
)

REM --- 1. Update the source --------------------------------------------------
if exist "%REPO_ROOT%\.git" (
    where git >nul 2>&1
    if errorlevel 1 (
        echo [whisper] git is not on PATH - skipping the source update.
    ) else (
        echo [whisper] updating source ^(git pull --ff-only^)...
        git -C "%REPO_ROOT%" pull --ff-only
        if errorlevel 1 (
            echo [whisper] WARNING: git pull failed. You may have local changes,
            echo           or the branch may have diverged. The dependency
            echo           refresh below still runs against the current source.
        )
    )
) else (
    echo [whisper] not a git checkout - skipping the source update.
)
echo.

REM --- 2. Pick an interpreter ------------------------------------------------
REM A .venv next to the source wins, so the update lands in the same place
REM a source install put the packages.
set "PY="
if exist "%REPO_ROOT%\.venv\Scripts\python.exe" (
    set "PY=%REPO_ROOT%\.venv\Scripts\python.exe"
    echo [whisper] using the project virtualenv: .venv
) else (
    where py >nul 2>&1
    if not errorlevel 1 (
        set "PY=py -3"
    ) else (
        where python >nul 2>&1
        if not errorlevel 1 (
            set "PY=python"
        )
    )
    if defined PY echo [whisper] no .venv found - using the system Python.
)

if not defined PY (
    echo [whisper] ERROR: no Python found. Install Python 3.11+ from
    echo           https://www.python.org/downloads/ and re-run this script.
    popd
    exit /b 1
)

REM --- 3. Refresh dependencies ----------------------------------------------
echo [whisper] upgrading pip...
%PY% -m pip install --upgrade pip wheel >nul 2>&1

echo [whisper] installing/upgrading requirements...
%PY% -m pip install --upgrade -r "%REPO_ROOT%\requirements.txt"
if errorlevel 1 (
    echo [whisper] ERROR: dependency install failed - see the output above.
    popd
    exit /b 1
)
echo.

REM --- 4. Refresh the bundled yt-dlp ----------------------------------------
REM Sites change their players constantly; a stale yt-dlp is the single most
REM common cause of "the download suddenly stopped working".
if exist "%REPO_ROOT%\bin\yt-dlp.exe" (
    echo [whisper] updating bin\yt-dlp.exe...
    "%REPO_ROOT%\bin\yt-dlp.exe" -U
    if errorlevel 1 echo [whisper] WARNING: yt-dlp self-update failed - continuing.
) else (
    echo [whisper] bin\yt-dlp.exe not present - skipping its update.
)
echo.

REM --- 5. Sanity check -------------------------------------------------------
REM Import the app rather than only trusting pip's exit code: a resolver
REM conflict can install "successfully" and still leave a tree that cannot
REM start. Better to fail here than on the user's next launch.
echo [whisper] verifying the install...
%PY% -c "import core, sys; print('[whisper] core version', core.__version__); sys.exit(0)"
if errorlevel 1 (
    echo [whisper] ERROR: the app does not import after the update.
    echo           Fix the errors above before launching.
    popd
    exit /b 1
)

echo.
echo [whisper] update complete. Launch with:  python gui.py
popd
endlocal
exit /b 0
