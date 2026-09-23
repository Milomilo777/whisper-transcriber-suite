# Session 8 — Packaging bug fix + smoke-test discipline

**Date:** 2026-05-14
**Branch:** `master`
**Driver:** a colleague reported that the packaged app did not work.

## TL;DR

The compiled exe was silently broken: the moment the user clicked
**Transcribe**, the worker subprocess died with

```
[ONNXRuntimeError] : 3 : NO_SUCHFILE : Load model from
  dist\WhisperProject\faster_whisper\assets\silero_vad_v6.onnx failed:
  Load model … failed. File doesn't exist
```

…because PyInstaller did not bundle the Silero VAD ONNX model that
`faster-whisper` opens by file path at VAD-filter time. VAD is on by
default, so every default transcription attempt failed.

The fix is one line in `whisper_project.spec`:

```python
from PyInstaller.utils.hooks import collect_data_files
faster_whisper_datas = collect_data_files('faster_whisper')
```

and then `*faster_whisper_datas` into `Analysis(datas=...)`.

The bug was invisible to every source-side test, including
`python gui.py` smoke runs and the headless `App` driver: source-side
code resolves `silero_vad_v6.onnx` from `site-packages/faster_whisper/assets/`,
which is always present in dev, so transcription succeeds. Only the
PyInstaller bundle is missing the asset.

## Why the previous tests didn't catch it

The repo had `tests/core/` and `tests/integrations/` covering unit and
in-process integration. Those test the **source code**, not the bundle.
The earlier compile-mode tests (e.g. `build.bat smoke`) only checked
that the exe stays alive for 5 seconds — but the bug doesn't surface
until you actually feed it a file to transcribe.

There was no test that **drives a real transcription through the
compiled exe**. Without one, this whole class of bug — anything
PyInstaller fails to package — was invisible.

## What changed

### `whisper_project.spec`

Added `collect_data_files('faster_whisper')` to the Analysis `datas`.
This pulls in `faster_whisper/assets/silero_vad_v6.onnx` (and any other
data files faster-whisper ships now or later). With this, the bundle
contains the asset at `dist/WhisperProject/faster_whisper/assets/`
and the transcriber can find it.

### `tests/smoke/`

New pytest suite that gets skipped on CI but runs locally:

- `test_exe_real_e2e.py` — spawns `WhisperProject.exe --worker`,
  sends a JSON `transcribe` command, asserts the SRT lands. Plus
  two regression guards: `test_exe_bundles_silero_vad_asset` and
  `test_exe_bundles_ffmpeg`.
- `test_app_headless.py` — the headless source-side suite for
  catching App/service regressions.
- `conftest.py` — `pytest.skip` guards for missing model / video / exe
  so the suite degrades gracefully on a clean machine.

Run locally with:

```
python -m pytest tests/smoke/ -v -s
```

## Verification

Before fix:

```
[exe_real] FAIL: [ONNXRuntimeError] … silero_vad_v6.onnx failed:
  File doesn't exist
```

After fix (same exe, same video):

```
[exe_real] worker ready after 8.7s
[exe_real] language: en (p=1.00)
[exe_real]   log> [19%] 00:00:00 --> 00:00:05 | President Trump urges …
[exe_real]   log> [100%] 00:00:30 --> 00:00:59 | Thank you for watching.
[exe_real]   log> Wrote 2 output file(s): 3029-NWN-Daily-Scroll-2m_0002.srt,
                  3029-NWN-Daily-Scroll-2m_0002.json
[exe_real] done in 84.2s

[exe_real] OK
  SRT  : E:\3029-NWN-Daily-Scroll-2m_0002.srt  (860 bytes)
  JSON : E:\3029-NWN-Daily-Scroll-2m_0002.json  (1117 bytes)
```

Unit suite: 136 passed, no regressions.

## Lessons for next session

1. **Source-side tests cannot catch packaging bugs.** If you ship an
   exe, you must have at least one test that drives the exe end-to-end
   on a real input.
2. `collect_data_files(<package>)` is the right tool for any third-party
   package that loads data by file path (not via `importlib.resources`).
   When adding a new heavy dependency, audit it for `open()` /
   `os.path.join` on files inside the package.
3. The `build.bat smoke` "exe stays up for 5s" check is necessary but
   nowhere near sufficient. Augment it (or replace it) with the smoke
   suite under `tests/smoke/`.
