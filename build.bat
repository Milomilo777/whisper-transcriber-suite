@echo off
REM build.bat - Windows production build script for whisper_app
REM Runs PyInstaller, then verifies the bundled binaries actually landed in dist/.
REM
REM Usage:
REM   build.bat              (full build)
REM   build.bat clean        (wipe build/ and dist/ first)
REM   build.bat verify       (skip PyInstaller, just verify the existing dist/)
REM   build.bat smoke        (verify and then launch the exe for 5 seconds)
REM
REM Exit codes:
REM   0  success
REM   1  PyInstaller failure
REM   2  post-build verification failure (a required file is missing)
REM   3  smoke launch failure (exe died within 5 seconds)

setlocal EnableDelayedExpansion

set REPO=%~dp0
set DIST=%REPO%dist\WhisperTranscriberSuite
set EXE=%DIST%\WhisperTranscriberSuite.exe

if "%1"=="clean" (
    echo [build] Cleaning build\ and dist\ ...
    if exist "%REPO%build" rmdir /S /Q "%REPO%build"
    if exist "%REPO%dist"  rmdir /S /Q "%REPO%dist"
)

if not "%1"=="verify" (
    echo [build] Running PyInstaller...
    pyinstaller --noconfirm "%REPO%whisper_project.spec"
    if errorlevel 1 (
        echo [build] PyInstaller FAILED.
        exit /b 1
    )
)

echo [build] Verifying required runtime files in dist\ ...

REM Belt-and-suspenders copy: if the .spec file dropped bin\, copy it now.
REM No-op if PyInstaller already placed it correctly.
if not exist "%DIST%\bin" (
    echo [build] dist\bin missing - copying from repo root as a fallback.
    xcopy /E /I /Q "%REPO%bin" "%DIST%\bin" >nul
)

REM Required files. The check is explicit so a future spec-file regression
REM fails the build loudly instead of producing a silently-broken exe.
set MISSING=
for %%F in (
    "%EXE%"
    "%DIST%\bin\ffmpeg.exe"
    "%DIST%\bin\ffprobe.exe"
    "%DIST%\bin\yt-dlp.exe"
) do (
    if not exist %%F (
        echo [build]   MISSING: %%F
        set MISSING=1
    ) else (
        echo [build]   OK     : %%F
    )
)

if defined MISSING (
    echo [build] Verification FAILED. dist\ is incomplete.
    exit /b 2
)

REM Note: config.json is intentionally NOT copied to dist\.
REM Phase 1.2 migrated config to %%LOCALAPPDATA%%\WhisperTranscriberSuite\config.json,
REM and load_config() now produces it on first launch from DEFAULT_CONFIG.
REM If you ever need a portable build that keeps config next to the exe,
REM add a "portable" build mode that copies config.json explicitly.

REM Optional smoke launch (only when called with `build.bat smoke`)
if "%1"=="smoke" goto smoke
if "%2"=="smoke" goto smoke
goto done

:smoke
echo [build] Launching exe for a 5-second smoke check...
start "" "%EXE%"
timeout /T 5 /NOBREAK >nul
tasklist /FI "IMAGENAME eq WhisperTranscriberSuite.exe" | find /I "WhisperTranscriberSuite.exe" >nul
if errorlevel 1 (
    echo [build] Smoke FAILED: process died within 5 seconds.
    exit /b 3
)
taskkill /IM WhisperTranscriberSuite.exe /F >nul 2>&1
echo [build] Smoke OK.

:done
echo [build] Done. Output: %DIST%
exit /b 0
