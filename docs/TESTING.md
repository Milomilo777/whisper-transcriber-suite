# Testing & running — quick guide

A short guide for working on this repo: how to run the tests, what the
test files are, and how to run the app.

## Run all checks (the everyday gate)

From the repo root, run:

```
run_tests.bat
```

(or double-click it in Explorer). It runs two things and prints a
PASS / FAIL summary, exiting non-zero if anything failed:

1. **pyright** — type check on `app\` and `core\`. Must stay at
   **0 errors** (the project's standing rule).
2. **pytest** — the hermetic unit suite (`tests\` minus `tests\smoke\`).

So after any change — yours or a teammate's — `run_tests.bat` tells you
at a glance whether the project is still green.

## One-time setup

- Python 3.11+ on PATH.
- `pip install -r requirements.txt`
- `pip install pyright pytest pytest-timeout responses hypothesis` (the dev tools `run_tests.bat`
  uses; the `dev` extra in `pyproject.toml` lists the same set plus `pytest-cov` for coverage runs).
  `pytest-timeout` is required: `pyproject.toml` passes `--timeout` to every run, so pytest stops
  with an unrecognised-argument error without it. `responses` is imported by the model download
  tests. `hypothesis` is the only optional one: the property-based tests skip themselves without
  it. `platformdirs`, which `tests/conftest.py` imports, comes with `requirements.txt`.

## What the test files are

- **`tests\` (everything except `tests\smoke\`)** — *hermetic* unit
  tests. No Whisper model, no network, no GUI window. Fast (seconds).
  These are the ones `run_tests.bat` runs. An autouse fixture in
  `tests\conftest.py` points every platformdirs per-user folder (config,
  data, cache, log) at a temp tree, so a run never touches your real app
  data; `tests\test_user_dir_isolation.py` fails if that redirect breaks.
  Each file targets one area, e.g.:
  - `tests\core\test_config.py` — config load/save, the model_path and
    download_folder persistence rules.
  - `tests\core\test_download_command.py` — the yt-dlp command builder
    (format selector, time-range, cookies).
  - `tests\core\test_history_db.py` — the SQLite history + crash-resume
    dismissal.
  - `tests\core\test_enqueue_after_download_async.py` — the non-blocking
    "transcribe after download" worker scheduling.
  - `tests\core\test_smtv_stream.py` — truncated-download handling of the
    site-specific download integration.

- **`tests\smoke\`** — *real-resource* tests. They need the Whisper
  model, a test video, and (for some) a live network, so they are
  **skipped automatically** when those aren't present. Run them only
  when validating a built installer, e.g.:

  ```
  set WHISPER_SMOKE_EXE=...\embed_build\python\pythonw.exe
  set WHISPER_SMOKE_GUI=...\embed_build\gui.py
  python -m pytest tests\smoke\test_exe_real_e2e.py
  ```

  See `docs\BUILD.md` for the full build + smoke instructions.

  The offline question-answering engine has its own smoke test against
  the real `llama-server` (installed runtime + a GGUF model; it loads the
  model once, ~3 GB of memory):

  ```
  set WHISPER_SMOKE_LLAMA_RUNTIME=%LOCALAPPDATA%\WhisperTranscriberSuite\Cache\tools\llama.cpp\b11514
  set WHISPER_SMOKE_LLAMA_MODEL=C:\models\gemma-4-E2B-it-Q4_K_M.gguf
  python -m pytest tests\smoke\test_local_llm_server_smoke.py
  ```

## Run the app from source

```
python gui.py
```

(Needs the dependencies above. The first transcription downloads the
~3 GB Whisper model once.)

## When a test fails

Scroll up in the `run_tests.bat` output:

- pyright prints `file:line` for each type error.
- pytest prints the failing test name and the assertion that failed.

Fix the cause, then re-run `run_tests.bat`. Keep pyright at 0 errors on
`app\` and `core\` before committing.

On Windows, `tk.Tk()` can rarely fail inside a full run with `Can't find a usable init.tcl` (a transient
Tcl read error; the file is fine and the test passes alone). The same fault can also read
`Can't find a usable tk.tcl` or `invalid command name "tcl_findLibrary"`. `tests/conftest.py` retries exactly
those errors at most 3 times in total; each retry is printed and the pytest summary shows `tk.Tk() init.tcl retries: N`.
Any other `TclError` fails the test as usual.

On Linux CI, Python 3.12 runs used to hang in Tk's `destroy` while the pystray icon thread waited on X (Xvfb
has no system tray). `.github/workflows/tray-hang-diag.yml` (manual trigger) runs the suite with and without
the tray icon and, when a test stops making progress, records whether the X server still answers and native
stacks of the stuck process (`gh workflow run tray-hang-diag.yml`). Its first run hung once in 4 runs with the
tray, never without, and at the hang the X server did not answer; the tray icon now stays off when X has no
system tray (`TrayController._no_x11_system_tray`).

The suite never adds a real icon to the system tray: `tests/conftest.py` replaces `pystray.Icon` with a
stand-in, and behind it the real icon class refuses to be built for the whole run; a test that still reaches it
fails with a message that names it (`tests/core/test_no_real_tray_icons.py`). A real icon whose test process
ends stays in the Windows notification area as a dead icon until the mouse passes over it, so full GUI runs
once left dozens there. The sv_ttk retry above covers the same Tcl read fault for any sv_ttk script
(`sv.tcl`, `theme/dark.tcl`, ...).

A key binding on a modal dialog (for example `<Escape>`) cannot be tested with `event_generate` in a background
test process on Windows: the dialog never gets the keyboard focus, so the key never arrives and `wait_window`
waits until the test timeout. Check that the binding exists (`dialog.bind("<Escape>")`) and close the dialog
the same way instead (`tests/app/test_share_page_dialog.py`).
