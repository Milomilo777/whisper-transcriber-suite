# Build

**Release file names decide the order on the release page.** GitHub lists a
release's files alphabetically (case-insensitive) with no manual order. The
owner wants the Windows installer first, then the Portable ZIP, then the Mac
builds, *without* number prefixes (2026-09-24), so the names are:

| Order | File |
|---|---|
| 1 | `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` |
| 2 | `WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` |
| 3 | `WhisperTranscriberSuite-vX.Y.Z-macOS-<arch>.dmg` |

"Installer" < "Portable" < "v…" keeps that order. v1.9.0 alone uses a
one-off `-1-`/`-2-`/`-3-` prefix; up to v1.8.0 the older names.

How to produce Windows binaries from source.

**Currently shipped (both from the same `embed_build\` tree):**
Setup-Standard (installer) + Portable (zip of that same tree — NOT
a PyInstaller onefile exe; that changed at v1.3.2, see AGENTS.md
"Shipped builds"). The PyInstaller onefile (Method A below) and
Compact/onedir (Method B) pipelines still exist and still build —
their specs are kept in lock-step so they don't bit-rot — but
neither is published.

## TL;DR — the two shipped deliverables

(replace `X.Y.Z` with the current `core.__version__` / `MyAppVersion`)

```cmd
:: 0. Fill bin\ with the pinned ffmpeg/ffprobe, yt-dlp, Deno and diarization models (SHA-256 checked)
python tools\fetch_windows_build_deps.py

:: 1. Build the embed tree (downloads Python, installs requirements.txt, copies app/core/bin)
build_embed_installer.bat
:: Output: embed_build\

:: 2. Setup-Standard installer, from embed_build\
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer_embed.iss
:: Output: dist_installer\WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe

:: 3. Portable zip — literally the same embed_build\ tree, zipped whole
python -c "import shutil; shutil.make_archive(r'dist_installer\WhisperTranscriberSuite-Portable-Windows-vX.Y.Z', 'zip', r'embed_build')"
:: Output: dist_installer\WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip
```

Re-shipping the SAME version is retired: a fix for already published
files always gets a new patch version (see "Rebuild without bumping
the version" below for why).

## Unshipped / optional pipelines

These two specs are Windows builds. Run on macOS, either one builds the
macOS spec (`platform/macos/pyinstaller/whisper_project_mac.spec`)
instead, because a Windows-style tree cannot become a working `.app`.

```cmd
:: Method A — Portable single-file exe (~447 MB; NOT the shipped "Portable" — unpublished)
pyinstaller --noconfirm --clean whisper_project_onefile.spec
:: Output: dist\WhisperTranscriberSuite-vX.Y.Z-Portable.exe

:: Method B — Compact installer (~326 MB; unshipped, optional)
pyinstaller --noconfirm --clean --distpath dist_onedir whisper_project_onedir.spec
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer.iss
:: Output: dist_installer\WhisperTranscriberSuite-vX.Y.Z-Setup-Compact.exe
```

## Prerequisites

* Python 3.10+ on PATH (used to invoke PyInstaller and pip).
* `pip install pyinstaller` in the working environment.
* `bin\ffmpeg.exe`, `bin\ffprobe.exe`, `bin\yt-dlp.exe`, `bin\deno.exe`
  and `bin\diarization\{segmentation,embedding}.onnx` in the
  git-ignored `bin\` folder — Method A and B bundle them via the
  spec's `('bin', 'bin')` data entry; Method C copies them with
  `xcopy`. `python tools\fetch_windows_build_deps.py` downloads the
  pinned versions listed in `platform\windows\build-deps.json` and
  refuses any file whose size or SHA-256 differs; `--check` verifies an
  existing `bin\` without downloading (`build_embed_installer.bat` runs
  it and warns when `bin\` is not the pinned set).
* Inno Setup 6 for Methods B and C. Install via `winget install
  JRSoftware.InnoSetup`. It lands at
  `%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe`.
* Method C also needs `tar.exe` from `%SystemRoot%\System32\` (the
  Windows-native bsdtar, not Git's tar — Git's tar tries to treat
  the `C:\` path as a remote host).

## Method A — Portable

```cmd
pyinstaller --noconfirm --clean whisper_project_onefile.spec
```

Builds a single self-extracting executable. At launch, PyInstaller
unpacks the bundle to `%TEMP%\_MEI<random>\` (~5 s on a typical
machine) and runs the app from there. `core.paths.resource_base()`
points to that temp dir at runtime.

Output: `dist\WhisperTranscriberSuite-vX.Y.Z-Portable.exe` (~447 MB; the bundled
`stable_whisper` + transitive `torch` pushed the v0.7.0 ~190 MB up by
the audit-2 polish push).

## Method B — Compact installer

Two steps. First produce the onedir tree:

```cmd
pyinstaller --noconfirm --clean --distpath dist_onedir whisper_project_onedir.spec
```

This drops a fully-extracted PyInstaller bundle under
`dist_onedir\WhisperTranscriberSuite\` with the exe and its sibling DLLs
flat at the top (the spec sets `contents_directory='.'`).

Then wrap it in an Inno Setup installer:

```cmd
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer.iss
```

The installer uses LZMA2 ultra compression, packs the ~478 MB
onedir tree to ~137 MB, ships per-user / per-machine shortcuts, and
gives users a real Add/Remove Programs entry.

Output: `dist_installer\WhisperTranscriberSuite-vX.Y.Z-Setup-Compact.exe`
(~137 MB).

## Method C — Standard installer with embeddable Python

```cmd
build_embed_installer.bat
```

The batch script:

1. Downloads
   `cpython-3.11.15+20260510-x86_64-pc-windows-msvc-install_only.tar.gz`
   from
   [python-build-standalone](https://github.com/astral-sh/python-build-standalone)
   through `tools\fetch_windows_build_deps.py`, which stops the build
   unless its size and SHA-256 match the entry in
   `platform\windows\build-deps.json`.
   This is a full CPython install with `tkinter` and the Tcl/Tk
   runtime — python.org's "embeddable" zip is stripped of tkinter,
   so we cannot use it directly.
2. Extracts it with the Windows-native `tar.exe`.
3. Verifies tkinter is importable.
4. Adds the Visual C++ runtime DLLs `msvcp140.dll` and `msvcp140_1.dll`
   to `python\`, next to the `vcruntime140*.dll` that
   python-build-standalone already carries (the `msvc-runtime` entry of
   `platform\windows\build-deps.json`, size and SHA-256 checked, see
   "Visual C++ runtime DLLs" below). `ctranslate2` and `onnxruntime`
   import them, and a Windows 10 PC without the Visual C++
   Redistributable does not have them.
5. `pip install --target` reads `requirements.txt` into the
   embed-build's `Lib\site-packages\`.
6. Copies `app\`, `core\`, `bin\`, and `gui.py` into the embed tree.
   `app\` and `core\` are copied without `__pycache__` and `*.pyc` (the
   bytecode of the build machine's CPython does not belong in a
   CPython 3.11 tree).
7. Writes a `sitecustomize.py` that prepends the bundle's
   `Lib\site-packages\` to `sys.path` whenever the embedded
   interpreter starts.
8. Runs a sanity import (`faster_whisper`, `ctranslate2`, `sv_ttk`,
   `platformdirs`, `tkinter`) to confirm the bundle is complete.
9. Runs `tools\check_embed_tree.py` on the tree and fails the build
   (exit code 11) if a `.dll`, `.pyd` or `.exe` imports a DLL that is not
   in the tree, not an API-set name and not on its list of DLLs every
   Windows 10 has, or if `app\` or `core\` holds any `__pycache__`.

**Before running this script for a release**, re-check the `tokenizers`
pin in `requirements.txt` against the `transformers` pin in
`core/optional_deps.py` (nvidia_asr entry) and `pyproject.toml`
(nvidia_asr extra) — they must agree, or the nvidia_asr backend fails to
import for every user on this build with a "tokenizers>=X,<=Y required"
error (see the comment above the `tokenizers` line in `requirements.txt`
for why: this bundled copy always wins over whatever nvidia_asr installs
on demand later). Quick check:

```
pip index versions tokenizers
python -c "from transformers.dependency_versions_table import deps; print(deps['tokenizers'])"
```

Then wrap the tree in an Inno Setup installer:

```cmd
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer_embed.iss
```

Output: `dist_installer\WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe`
(~150-400 MB depending on which optional heavy deps — torch/stable-ts
— happen to be present; the batch script prunes them from
`embed_build\`, see its "slim" step).

Method C's shortcuts launch `pythonw.exe gui.py` rather than a
frozen exe, so the entire Python source tree lives on disk after
install — friendlier for debugging or local patching at the cost
of a slightly larger installed footprint.

**This is also how the shipped Portable is built** — it is the exact
same `embed_build\` tree, just zipped whole instead of wrapped by
Inno Setup:

```cmd
python -c "import shutil; shutil.make_archive(r'dist_installer\WhisperTranscriberSuite-Portable-Windows-vX.Y.Z', 'zip', r'embed_build')"
```

`WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip` and
`WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe` are the two files that get
uploaded to a new GitHub release (see `docs/RELEASE_PROCESS.md`; the
"Rebuild without bumping the version" section below is retired).

**Visual C++ runtime DLLs.** The tree carries `msvcp140.dll` and
`msvcp140_1.dll` itself (app-local deployment, which Microsoft allows
for these files when they are shipped unmodified; see
`THIRD_PARTY_NOTICES.md`), so the installer and the Portable ZIP start on
a Windows 10 PC that never installed the Visual C++ Redistributable. They
sit in `python\`, the folder of `python.exe`: Python loads every extension
module with the application folder on the DLL search path, and the
`ctranslate2` and `onnxruntime` DLLs they pull in are found there before
any copy in `System32`. The pin is the `msvc-runtime` 14.44.35112 wheel
for CPython 3.11 (PyPI repackages Microsoft's files; every DLL has a valid
Microsoft signature and its `vcruntime140*.dll` are byte for byte the ones
in the pinned Python build). It is marked `"explicit": true`, so a plain
`fetch_windows_build_deps.py` run (which fills `bin\`) skips it and the
build asks for it with `--select msvc-runtime --root embed_build`.
`check_embed_tree.py` is the guard: when a new package imports another
runtime DLL (`msvcp140_2.dll`, `concrt140.dll`, `vcomp140.dll`, ...) the
build fails until that file is added to the pin's `files` list. A source
install (`run_from_source.bat`) uses your own Python and still needs the
Redistributable.

**cuDNN.** Nothing downloads cuDNN separately. The `ctranslate2` wheel
from PyPI carries its own `cudnn64_9.dll` (about 0.3 MB) inside
`Lib\site-packages\ctranslate2\`, and Method C bundles that wheel as
it is, locally and in CI. GPU users still need cuBLAS for CUDA 12,
which the app installs on demand (see the GPU note in
`requirements.txt`).

## Method C in CI (GitHub Actions)

`.github/workflows/windows-installer.yml` runs the steps above on a
clean `windows-latest` runner. It starts on a push to `master` that
touches a build file (`build_embed_installer.bat`, `installer_embed.iss`,
`requirements.txt`, `platform/windows/build-deps.json`, the helper
scripts below or the workflow itself) or what ships inside the build
(`gui.py`, `app/`, `core/`, `assets/`), and by hand from the Actions tab
("Run workflow"). A newer push waits for a running build instead of
cancelling it. It:

1. fetches every third-party download from
   `platform/windows/build-deps.json` — python-build-standalone,
   ffmpeg/ffprobe, yt-dlp, Deno, the Visual C++ runtime DLLs, the two
   diarization models and Inno Setup 6.7.3 — at a fixed URL, checked against the recorded size and
   a SHA-256 the upstream project publishes (release checksum file,
   GitHub release asset digest or Hugging Face LFS id);
2. runs `build_embed_installer.bat`, checks `embed_build\bin\` and the
   runtime DLLs in `embed_build\python\` against the pins again
   (`--check --root embed_build`, `--check --select msvc-runtime --root
   embed_build`), compiles
   `installer_embed.iss` and zips the Portable build;
3. writes a file manifest (`tools/build_manifest.py`: path, size and
   SHA-256 of every file in `embed_build\` and `dist_installer\`) and the
   exact PyPI package versions of the run (`site-packages.txt`);
4. runs `tools/smoke_windows_install.py` on the Portable tree
   (`embed_build\`), then installs the installer silently on the runner, checks the installed
   `bin\` and the runtime DLLs against the pins, runs
   `tools/check_embed_tree.py` on the installed tree (before the smoke
   test, which makes Python write `__pycache__` folders), runs
   `tools/smoke_windows_install.py` with
   the installed interpreter (version, runtime imports including the GUI
   dependencies, an import of every `app.*` / `core.*` module, assets and
   licence files, Tcl/Tk, bundled tools, diarization models,
   `gui.py --help`) and uninstalls it again;
5. uploads `windows-installer-<commit>` (installer + Portable ZIP) and
   `windows-build-manifest-<commit>` as workflow artifacts, kept 7 days.

It never creates a release or a tag and uses no secrets; the token has
read access only. Publishing stays the manual step in
`docs/RELEASE_PROCESS.md`, and the files are unsigned like the local
build.

Python packages are the one part that is not pinned:
`requirements.txt` uses version ranges, so two builds on different days
can bundle different package versions. `site-packages.txt` in the
manifest artifact records what a run bundled.

To compare a CI build with a local one, download the manifest artifact
and run:

```cmd
python tools\build_manifest.py write embed_build local-embed.json
python tools\build_manifest.py compare local-embed.json embed_build.json --strict bin/ --strict python/
```

`--strict` fails on any difference under those folders (they come from
the pinned downloads); other areas are listed with their file and size
changes, and the whole tree may change size by at most `--tolerance`
(default 10 %). A local `bin\` filled by hand or by the older
`tools\download_diarization_models.bat` also holds
`diarization\segmentation.int8.onnx` and `diarization\segmentation.tar.bz2`,
which the app never reads and the pins do not fetch, so `--strict bin/`
lists them until `bin\` is refilled with `fetch_windows_build_deps.py`.

**Moving a pin to a newer version:** change the entry's `url`, `size`
and `sha256` (and, for archives, each file's `member` and `sha256`) in
`platform/windows/build-deps.json`, taking the hash from the upstream
release (checksum file or the asset digest GitHub shows), then run
`python tools\fetch_windows_build_deps.py --root <empty folder>`: it
fails on any value that does not match the real download. Entries
without `files` (the Python tarball, Inno Setup) are not part of that
run; test them with `--only <name> --out <file>`. The entry marked
`"explicit": true` (`msvc-runtime`) is also left out of a plain run
because its files belong in the embed tree: test it with `--select
msvc-runtime --root <empty folder>`. When moving it, check that each DLL
still has a valid Microsoft signature (`Get-AuthenticodeSignature`) and
that the wheel's `vcruntime140.dll` and `vcruntime140_1.dll` equal the
ones in `embed_build\python\`.

## Rebuild without bumping the version — RETIRED, do not use (2026-08-23)

**This whole recipe is retired.** `--clobber` deletes the existing
asset and uploads a fresh one, which silently resets that asset's
GitHub download count to zero (confirmed via `cli/cli` issue #8822) —
discovered after this exact pattern had already been used at least
once (the v1.7.0 GC-lock-fix re-upload). See AGENTS.md "Guardrails"
for the replacement rule: cut a new patch version instead. Left below for
historical reference only.

<details>
<summary>Original recipe (do not follow)</summary>

Use this when the source changed (a bug fix, a UI tweak, a new writer,
…) but the release is meant to stay the SAME version number — i.e. you
are refreshing an already-published release's assets in place, not
cutting a new one. Confirm this is really what's wanted before
running Step 4 (it overwrites public, already-downloaded release
assets under the same tag).

**Step 1 — confirm the version is genuinely unchanged:**

```cmd
findstr /C:"__version__" core\__init__.py
findstr /C:"MyAppVersion" installer_embed.iss
findstr /C:"^version" pyproject.toml
```

All three must already show the version you intend to ship — this
recipe does NOT bump anything.

**Step 2 — validate the source first** (this is the same bar as any
commit — see AGENTS.md):

```cmd
python -m pyright app core
python -m pytest tests\ --ignore=tests\smoke
```

Both must be clean before building — the build below has no separate
CI gate to catch a regression.

**Step 3 — full rebuild + package:**

```cmd
build_embed_installer.bat
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer_embed.iss
python -c "import shutil; shutil.make_archive(r'dist_installer\WhisperTranscriberSuite-Portable-Windows-vX.Y.Z', 'zip', r'embed_build')"
```

`build_embed_installer.bat` always does a **full** rebuild (deletes
and redownloads `embed_build\` from scratch) so the result is not
sensitive to whatever was left over from a previous build — slower
than an incremental refresh, but nothing to get wrong. It ends with
its own sanity imports (full stack, core modules, `gui.py` parses)
and fails loudly (non-zero exit) if anything's missing. Google Cloud
STT's own client libraries (`google-cloud-speech`, `grpc`, protobuf)
are deliberately NOT part of this bundle — they install on demand via
`core/optional_deps.py` the first time a user picks their own
service-account JSON; only the app's lightweight wrapper module
(`core.backends.google_cloud_stt`, which needs none of those at
import time) is sanity-checked here.

**Step 4 — update the existing GitHub release's assets in place**
(same tag, no new tag, no version bump):

```cmd
gh release upload vX.Y.Z ^
    dist_installer\WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe ^
    dist_installer\WhisperTranscriberSuite-Portable-Windows-vX.Y.Z.zip ^
    --clobber
```

`--clobber` replaces the existing assets of the same name rather than
erroring that they already exist. This is the step users' next
download actually sees — anyone who already downloaded the old
asset is unaffected (their file doesn't change under them), but
`gh release view vX.Y.Z` afterwards should show fresh
`createdAt`/size for both assets. Optionally follow with `gh release
edit vX.Y.Z --notes-file <notes file>` if the release
notes body should also mention what changed in this refresh.

**Step 4b — macOS (can't build a `.dmg` on Windows):** read
[`docs/MACOS_BUILD_NOTES.md`](MACOS_BUILD_NOTES.md) first. Either build on a
real Mac with `bash platform/macos/build_mac.sh` (one command: venv, tools,
PyInstaller, checks, `.dmg`), or dispatch the CI workflow — it
builds AND tests (real transcription with the frozen app, GUI launch,
bundled ffmpeg/yt-dlp) on Apple-silicon and Intel runners and uploads
`WhisperTranscriberSuite-vX.Y.Z-macOS-{arm64,x64}.dmg`. Releases ship no `.sha256` files (GitHub shows each
asset's SHA-256 digest itself).

```cmd
gh workflow run macos-app.yml --ref master
gh run list --workflow=macos-app.yml -L 1
gh run watch <run-id> --exit-status
gh run download <run-id> --dir some_temp_dir
:: upload to a NEW release/version only - never --clobber (see AGENTS.md)
gh release upload vX.Y.Z some_temp_dir\macos-dmg-arm64\*.dmg* some_temp_dir\macos-dmg-x86_64\*.dmg*
```
Check each job's log for `[mac-spec] highest bundled minos` — that is the
real minimum macOS of that .dmg; put it in the release notes.

`macos-app.yml` is `workflow_dispatch`-only (see the file's own header
comment) so it never fires by accident on a normal push. The repo is
public, so this no longer burns paid private-repo macOS minutes.

</details>

## Sanity check after any build

```cmd
python -m pytest tests\ --ignore=tests\smoke
```

Expected: 162 passed.

For the compiled artefacts, run the smoke E2E against each:

```cmd
:: Method A
set WHISPER_SMOKE_EXE=dist\WhisperTranscriberSuite-vX.Y.Z-Portable.exe
python -m pytest tests\smoke\test_exe_real_e2e.py

:: Method B (after silent install to C:\Temp\test_B)
set WHISPER_SMOKE_EXE=C:\Temp\test_B\WhisperTranscriberSuite.exe
python -m pytest tests\smoke\test_exe_real_e2e.py

:: Method C (after silent install to C:\Temp\test_C)
set WHISPER_SMOKE_EXE=C:\Temp\test_C\python\pythonw.exe
set WHISPER_SMOKE_GUI=C:\Temp\test_C\gui.py
python -m pytest tests\smoke\test_exe_real_e2e.py
```

Each must report `test_exe_worker_transcribes_real_video PASSED`
(plus a skipped size check on Methods B and C — see the test for
why).

## Files involved

| File | Role |
|---|---|
| `whisper_project_onefile.spec` | Method A — embedded `EXE()` (no `COLLECT`) |
| `whisper_project_onedir.spec` | Method B — `EXE() + COLLECT()` for the onedir tree |
| `installer.iss` | Method B — wraps `dist_onedir\` into Setup-Compact |
| `build_embed_installer.bat` | Method C — builds `embed_build\` |
| `installer_embed.iss` | Method C — wraps `embed_build\` into Setup-Standard |
| `requirements.txt` | runtime deps installed into Method C's embed tree |
| `bin\` | bundled `ffmpeg.exe`, `ffprobe.exe`, `yt-dlp.exe`, `deno.exe`, diarization models (all methods) |
| `platform\windows\build-deps.json` | pinned URL, size and SHA-256 of every third-party download of Method C |
| `tools\fetch_windows_build_deps.py` | downloads and verifies those pins into `bin\` (or one file with `--only`) |
| `tools\check_embed_tree.py` | build check: every DLL import in `embed_build\` resolves on a clean Windows 10, no bytecode in `app\` and `core\` |
| `tools\build_manifest.py` | file manifest of a build tree, and a comparison of two manifests |
| `tools\smoke_windows_install.py` | smoke test of an installed build (used by CI) |
| `.github\workflows\windows-installer.yml` | Method C on a GitHub runner, outputs as workflow artifacts |

## Build outputs are gitignored

`dist/`, `dist_onedir/`, `dist_installer/`, `embed_build/`,
`build/`, and `build_logs/` are all in `.gitignore`. Commit only
specs, batch scripts, and `.iss` files.
