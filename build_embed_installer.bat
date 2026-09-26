@echo off
setlocal EnableDelayedExpansion
REM build_embed_installer.bat — produce the embed_build\ tree that
REM installer_embed.iss turns into WhisperTranscriberSuite-vX.Y.Z-Setup-Standard.exe.
REM
REM Why python-build-standalone, not python.org's embeddable zip:
REM the embeddable distro ships *without* tkinter and the Tcl/Tk
REM runtime, which the UI needs. python-build-standalone's
REM "install_only" tarball is a full CPython install (Lib/, DLLs/,
REM tcl/, Scripts/) suitable for embedding, including tkinter.
REM
REM Output layout under embed_build\ at the end:
REM   python\python.exe         — CPython 3.11 interpreter
REM   python\pythonw.exe        — windowed launcher used by shortcuts
REM   python\Lib\               — full stdlib including tkinter
REM   python\DLLs\              — _tkinter.pyd, native deps
REM   python\tcl\               — Tcl runtime
REM   Lib\site-packages\        — runtime deps from requirements.txt
REM   app\                      — Tk UI package
REM   core\                     — transcription / download / paths modules
REM   bin\                      — ffmpeg.exe, ffprobe.exe, yt-dlp.exe
REM   gui.py                    — entry point (pythonw gui.py)

set ROOT=%~dp0
set BUILD=%ROOT%embed_build
set PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe
set PYBSD_VER=3.11.15
set PYBSD_TAG=20260510
set ASSET=cpython-%PYBSD_VER%+%PYBSD_TAG%-x86_64-pc-windows-msvc-install_only.tar.gz
set URL=https://github.com/astral-sh/python-build-standalone/releases/download/%PYBSD_TAG%/%ASSET%

if exist "%BUILD%" rmdir /S /Q "%BUILD%"
mkdir "%BUILD%"

echo [embed] downloading %ASSET%
"%PS%" -NoProfile -Command "Invoke-WebRequest -UseBasicParsing -Uri '%URL%' -OutFile '%BUILD%\python.tar.gz'"
if errorlevel 1 (
  echo [embed] download failed
  exit /b 1
)

echo [embed] extracting Python install_only tarball
REM Use the Windows system tar (bsdtar). Git's tar misinterprets "C:"
REM as a remote-host argument and fails with "Cannot connect to C:".
"%SystemRoot%\System32\tar.exe" -xzf "%BUILD%\python.tar.gz" -C "%BUILD%"
if errorlevel 1 (
  echo [embed] tar extract failed
  exit /b 2
)
del "%BUILD%\python.tar.gz"

echo [embed] verifying tkinter is present in the extracted distro
"%BUILD%\python\python.exe" -c "import tkinter; print('tkinter version', tkinter.TkVersion)"
if errorlevel 1 (
  echo [embed] tkinter not importable — wrong distro variant?
  exit /b 3
)

echo [embed] installing runtime requirements into Lib\site-packages
mkdir "%BUILD%\Lib"
"%BUILD%\python\python.exe" -m pip install --no-warn-script-location --target "%BUILD%\Lib\site-packages" -r "%ROOT%requirements.txt"
if errorlevel 1 (
  echo [embed] pip install failed
  exit /b 4
)

echo [embed] slim: pruning heavy optional packages (installed on-demand at runtime)
REM torch + its deps (sympy/networkx/mpmath) and numba/llvmlite are pulled in
REM ONLY by the optional stable-ts alignment / openai-whisper backend. They are
REM ~750 MB and are installed on first use via core.optional_deps. Removing them
REM here keeps the shipped bundle ~800 MB instead of ~1.5 GB.
pushd "%BUILD%\Lib\site-packages"
for %%P in (torch torchaudio whisper stable_whisper numba llvmlite sympy networkx mpmath functorch torchgen) do if exist "%%P\" rmdir /s /q "%%P"
REM Native-lib sibling dirs left orphaned once their package is gone
REM (llvmlite.libs alone is ~30-40 MB). The if-exist guard skips any
REM that a given torch/numba wheel didn't ship.
for %%P in (llvmlite.libs numba.libs torch.libs torchaudio.libs) do if exist "%%P\" rmdir /s /q "%%P"
for /d %%D in (torch-* torchaudio-* openai_whisper-* stable_ts-* numba-* llvmlite-* sympy-* networkx-* mpmath-* functorch-* torchgen-*) do rmdir /s /q "%%D"
popd

REM Deno for yt-dlp's YouTube JS challenges, next to yt-dlp so it needs no
REM click in the Download tab (core.js_runtime.find_deno checks bin\ first).
REM Official zip, SHA-256 verified by install_deno(); bin\deno.exe is gitignored.
if not exist "%ROOT%bin\deno.exe" (
  echo [embed] fetching Deno into bin\
  pushd "%ROOT%"
  python -c "import shutil; from core.js_runtime import install_deno; shutil.copy2(install_deno(), r'bin\deno.exe')"
  popd
  if not exist "%ROOT%bin\deno.exe" (
    echo [embed] Deno fetch failed
    exit /b 9
  )
)

echo [embed] copying source tree
xcopy /E /I /Y "%ROOT%app" "%BUILD%\app" >nul
xcopy /E /I /Y "%ROOT%core" "%BUILD%\core" >nul
xcopy /E /I /Y "%ROOT%bin" "%BUILD%\bin" >nul
copy "%ROOT%gui.py" "%BUILD%\" >nul

REM NO credentials are bundled. Until 2026-08 this step copied a
REM maintainer-owned Google Cloud service-account key into the build so cloud
REM STT worked out of the box; that shipped one shared credential to every
REM person who downloaded the installer. It was extractable from the package,
REM billed to the maintainer's project, and answerable for whatever anyone
REM used it to transcribe. The key is revoked and the step is gone for good.
REM Cloud STT is now opt-in with the user's OWN service-account JSON, picked
REM in Advanced ^> Backend. See SECURITY.md and docs/CLOUD_STT_GOOGLE.md.
REM Do not re-add a credential copy here.
if exist "%ROOT%creds\gcloud_stt.json" (
    echo [embed] ERROR: creds\gcloud_stt.json exists but is deliberately NOT bundled.
    echo [embed]        Shipping a shared cloud key is banned - see SECURITY.md.
)

REM The xcopy /E above already brings core\server\ (incl. static\) along.
REM Verify the optional LAN/web server's static page shipped so a broken
REM "gui.py serve" mode fails the build loudly instead of silently.
if not exist "%BUILD%\core\server\static\index.html" (
    echo [embed] ERROR: core\server\static\index.html missing from embed tree
    exit /b 1
)

echo [embed] writing the portable launcher
> "%BUILD%\Run Whisper Transcriber Suite.bat" echo @echo off
>> "%BUILD%\Run Whisper Transcriber Suite.bat" echo cd /d "%%~dp0"
>> "%BUILD%\Run Whisper Transcriber Suite.bat" echo start "" "python\pythonw.exe" "gui.py"

echo [embed] writing no_voice_clone.flag (Portable ships this feature OFF by default; the Setup-Standard installer removes this marker if the user opts in via the "voiceclone" task)
type nul > "%BUILD%\no_voice_clone.flag"

echo [embed] writing sitecustomize.py to teach python where site-packages lives
> "%BUILD%\python\Lib\sitecustomize.py" echo import sys, os
>> "%BUILD%\python\Lib\sitecustomize.py" echo _here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
>> "%BUILD%\python\Lib\sitecustomize.py" echo _site = os.path.join(_here, "Lib", "site-packages")
>> "%BUILD%\python\Lib\sitecustomize.py" echo if os.path.isdir(_site) and _site not in sys.path:
>> "%BUILD%\python\Lib\sitecustomize.py" echo     sys.path.insert(0, _site)

echo [embed] sanity import check (full stack)
REM docx + reportlab are bundled (NOT pruned) — they back the docx/pdf
REM writers. Import them here so a future prune mistake fails the build
REM loudly instead of silently re-introducing the docx-never-written bug.
"%BUILD%\python\python.exe" -c "import faster_whisper, ctranslate2, sv_ttk, platformdirs, tkinter, docx, reportlab; print('embed_import_ok')"
if errorlevel 1 (
  echo [embed] sanity import failed — bundle is incomplete
  exit /b 5
)

REM Google Cloud STT's client libs (google-cloud-speech, grpc, protobuf)
REM are deliberately NOT in requirements.txt / this embed tree — see the
REM comment above the (now-absent) pin in requirements.txt and
REM SECURITY.md's "Retired: the bundled Google Cloud key". They install
REM on demand via core/optional_deps.py the first time a user picks their
REM own service-account JSON. Do not re-add a "bundled Google Cloud STT
REM stack" sanity import here — it would fail every build, correctly,
REM because the package is no longer meant to be present.

REM Import the newer core modules too (they are Tk-free + dependency-light)
REM so a future prune or a syntax error in any of them fails the build
REM loudly here instead of only crashing at runtime: the format converter,
REM usage stats, LAN/web server, the Google Cloud STT backend, the SMTV
REM docx writer, and the monitors / updates helpers.
echo [embed] sanity import check (core modules)
REM Run with the bundle root as cwd so the bundled core/ package is on
REM sys.path (site-packages alone does not contain it).
pushd "%BUILD%"
"%BUILD%\python\python.exe" -c "import core.convert, core.stats, core.server, core.backends.google_cloud_stt, core.writers.smtv_docx_writer, core.monitors, core.updates; print('embed_core_import_ok')"
set _CORE_RC=%errorlevel%
popd
if not "%_CORE_RC%"=="0" (
  echo [embed] core sanity import failed — a core module is missing or broken
  exit /b 5
)

echo [embed] verifying gui.py worker entry point parses
"%BUILD%\python\python.exe" -c "import ast; ast.parse(open(r'%BUILD%\gui.py').read())"
if errorlevel 1 (
  echo [embed] gui.py parse failed
  exit /b 6
)

echo [embed] build complete: %BUILD%
exit /b 0
