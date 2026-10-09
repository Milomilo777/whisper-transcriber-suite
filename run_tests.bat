@echo off
REM ===================================================================
REM  run_tests.bat  -  run the project's checks and report PASS / FAIL.
REM
REM  Runs the everyday gate (no Whisper model, no network, no GUI):
REM     1) pyright type check on app\ and core\   (must be 0 errors)
REM     2) hermetic unit tests  (tests\ minus tests\smoke\)
REM
REM  Use it after ANY change to see at a glance whether the project is
REM  still green. Double-click it in Explorer, or run it from a
REM  terminal opened in the repo root.
REM
REM  One-time setup:
REM     pip install -r requirements.txt
REM     pip install pyright pytest hypothesis
REM  (hypothesis runs the property-based tests; they are skipped without it)
REM ===================================================================
setlocal
cd /d "%~dp0"

echo.
echo [1/2] pyright  (type check: app\ core\)
echo -------------------------------------------------------------------
pyright app core
set PYRIGHT_RC=%errorlevel%

echo.
echo [2/2] pytest  (hermetic unit suite: tests\ minus tests\smoke\)
echo -------------------------------------------------------------------
python -m pytest tests/ --ignore=tests/smoke -q
set PYTEST_RC=%errorlevel%

set FINAL=0
if not "%PYRIGHT_RC%"=="0" set FINAL=1
if not "%PYTEST_RC%"=="0" set FINAL=1

echo.
echo ===================================================================
echo   RESULT
echo ===================================================================
if "%PYRIGHT_RC%"=="0" (echo   pyright : PASS) else (echo   pyright : FAIL  rc=%PYRIGHT_RC%)
if "%PYTEST_RC%"=="0"  (echo   pytest  : PASS) else (echo   pytest  : FAIL  rc=%PYTEST_RC%)
if "%FINAL%"=="0" (echo   ALL GREEN) else (echo   FAILED - scroll up for the details.)
echo ===================================================================

REM Keep the window open when launched by double-click from Explorer.
echo %cmdcmdline% | find /i "%~nx0" >nul 2>&1 && pause
endlocal & exit /b %FINAL%
