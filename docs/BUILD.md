# Build

How to produce Windows binaries from source.

**Currently shipped (both from the same `embed_build\` tree):**
Setup-Standard (installer) + Portable (zip of that same tree — NOT
a PyInstaller onefile exe; that changed at v1.3.2, see CLAUDE.md
"Style & scope"). The PyInstaller onefile (Method A below) and
Compact/onedir (Method B) pipelines still exist and still build —
their specs are kept in lock-step so they don't bit-rot — but
neither is published.

## TL;DR — the two shipped deliverables

(replace `X.Y.Z` with the current `core.__version__` / `MyAppVersion`)

```cmd
:: 1. Build the embed tree (downloads Python, installs requirements.txt, copies app/core/bin)
build_embed_installer.bat
:: Output: embed_build\

:: 2. Setup-Standard installer, from embed_build\
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer_embed.iss
:: Output: dist_installer\WhisperTranscriberSuite-vX.Y.Z-Setup-Standard.exe

:: 3. Portable zip — literally the same embed_build\ tree, zipped whole
python -c "import shutil; shutil.make_archive(r'dist_installer\WhisperTranscriberSuite-vX.Y.Z-Portable', 'zip', r'embed_build')"
:: Output: dist_installer\WhisperTranscriberSuite-vX.Y.Z-Portable.zip
```

See "Rebuild without bumping the version" below for the full,
copy-pasteable recipe (including uploading to the existing GitHub
release) used when re-shipping the SAME version with source-only
changes.

## Unshipped / optional pipelines

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
* `bin\ffmpeg.exe`, `bin\ffprobe.exe`, `bin\yt-dlp.exe` checked into
  the repo's `bin\` folder — Method A and B bundle them via the
  spec's `('bin', 'bin')` data entry; Method C copies them with
  `xcopy`.
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
   [python-build-standalone](https://github.com/astral-sh/python-build-standalone).
   This is a full CPython install with `tkinter` and the Tcl/Tk
   runtime — python.org's "embeddable" zip is stripped of tkinter,
   so we cannot use it directly.
2. Extracts it with the Windows-native `tar.exe`.
3. Verifies tkinter is importable.
4. `pip install --target` reads `requirements.txt` into the
   embed-build's `Lib\site-packages\`.
5. Copies `app\`, `core\`, `bin\`, and `gui.py` into the embed tree.
6. Writes a `sitecustomize.py` that prepends the bundle's
   `Lib\site-packages\` to `sys.path` whenever the embedded
   interpreter starts.
7. Runs a sanity import (`faster_whisper`, `ctranslate2`, `sv_ttk`,
   `platformdirs`, `tkinter`) to confirm the bundle is complete.

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

Output: `dist_installer\WhisperTranscriberSuite-vX.Y.Z-Setup-Standard.exe`
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
python -c "import shutil; shutil.make_archive(r'dist_installer\WhisperTranscriberSuite-vX.Y.Z-Portable', 'zip', r'embed_build')"
```

`WhisperTranscriberSuite-vX.Y.Z-Portable.zip` and
`WhisperTranscriberSuite-vX.Y.Z-Setup-Standard.exe` are the two files that get
uploaded to the GitHub release (see "Rebuild without bumping the
version" below, and `docs/RELEASE_PROCESS.md` for a full version-bump
release).

## Rebuild without bumping the version — RETIRED, do not use (2026-08-23)

**This whole recipe is retired.** `--clobber` deletes the existing
asset and uploads a fresh one, which silently resets that asset's
GitHub download count to zero (confirmed via `cli/cli` issue #8822) —
discovered after this exact pattern had already been used at least
once (the v1.7.0 GC-lock-fix re-upload). See CLAUDE.md "Never
`--clobber` an existing release asset" for the full story and the
replacement rule: cut a new patch version instead. Left below for
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
commit — see CLAUDE.md):

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
python -c "import shutil; shutil.make_archive(r'dist_installer\WhisperTranscriberSuite-vX.Y.Z-Portable', 'zip', r'embed_build')"
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
    dist_installer\WhisperTranscriberSuite-vX.Y.Z-Setup-Standard.exe ^
    dist_installer\WhisperTranscriberSuite-vX.Y.Z-Portable.zip ^
    --clobber
```

`--clobber` replaces the existing assets of the same name rather than
erroring that they already exist. This is the step users' next
download actually sees — anyone who already downloaded the old
asset is unaffected (their file doesn't change under them), but
`gh release view vX.Y.Z` afterwards should show fresh
`createdAt`/size for both assets. Optionally follow with `gh release
edit vX.Y.Z --notes-file docs/RELEASE_NOTES_vX.Y.Z.md` if the release
notes body should also mention what changed in this refresh.

**Step 4b — macOS (can't build a `.dmg` on Windows):** read
[`docs/MACOS_BUILD_NOTES.md`](MACOS_BUILD_NOTES.md) first. Either build on a
real Mac with the scripts listed there, or dispatch the CI workflow — it
builds AND tests (real transcription with the frozen app, GUI launch,
bundled ffmpeg/yt-dlp) on Apple-silicon and Intel runners and uploads
`WhisperTranscriberSuite-vX.Y.Z-macOS-{arm64,x64}.dmg` + `.sha256`.

```cmd
gh workflow run macos-app.yml --ref master
gh run list --workflow=macos-app.yml -L 1
gh run watch <run-id> --exit-status
gh run download <run-id> --dir some_temp_dir
:: upload to a NEW release/version only - never --clobber (see CLAUDE.md)
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
| `bin\` | bundled `ffmpeg.exe`, `ffprobe.exe`, `yt-dlp.exe` (all methods) |

## Build outputs are gitignored

`dist/`, `dist_onedir/`, `dist_installer/`, `embed_build/`,
`build/`, and `build_logs/` are all in `.gitignore`. Commit only
specs, batch scripts, and `.iss` files.
