# Smoke tests — local-machine integration suite

These tests exercise the **compiled exe** and the full **App** wiring against
a real model and a real media file. They cannot run on CI: they require
locally-downloaded model weights, a video file on disk, and a fresh
PyInstaller build under `dist/`.

The unit suite under `tests/core/` and `tests/integrations/` is what runs
on CI and stays hermetic. The smoke suite is what catches **packaging
bugs** the unit suite can't see — e.g. missing data files in the
PyInstaller bundle.

## Why they live here

The Session 8 history is instructive: a colleague reported the app was
broken, but a Python-source smoke test (`python gui.py` + service calls)
returned 11/11 pass. Only when we re-spawned `WhisperTranscriberSuite.exe --worker`
and sent a real `transcribe` command did we hit:

> `[ONNXRuntimeError] Load model … silero_vad_v6.onnx failed: File doesn't exist`

The Silero VAD model that `faster-whisper` loads by file path was not
collected into the PyInstaller bundle. Fix: add `collect_data_files('faster_whisper')`
to the spec. This category of bug **cannot** be caught from source — only
the compiled exe touches the bundled file layout. Hence: smoke tests
against the exe.

## What's covered

| File | What it proves |
|---|---|
| `test_app_headless.py` | The `App` Tk root + every service can be instantiated and driven without UI clicks. Catches Python-source regressions across services, writers, dialogs, oTranscribe round-trip, theme switching. |
| `test_exe_real_e2e.py` | `dist/WhisperTranscriberSuite/WhisperTranscriberSuite.exe --worker` actually transcribes a real video. Catches **PyInstaller packaging bugs** (missing data files, hidden imports, DLLs that don't resolve at runtime). |

## How to run

```
# Set the test video (defaults to E:\3029-NWN-Daily-Scroll-2m_0002.mp4)
set WHISPER_SMOKE_VIDEO=C:\path\to\some.mp4

# Make sure the exe is built and the model is in %LOCALAPPDATA%
build.bat clean

# Run just the smoke suite
python -m pytest tests/smoke/ -v -s
```

Each test calls `pytest.skip(...)` if its prerequisites (model folder,
test video, compiled exe) are missing, so running the whole `pytest`
invocation on a clean machine still succeeds.
