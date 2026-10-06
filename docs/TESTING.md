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
- `pip install pyright pytest` (dev tools used by `run_tests.bat`).

## What the test files are

- **`tests\` (everything except `tests\smoke\`)** — *hermetic* unit
  tests. No Whisper model, no network, no GUI window. Fast (seconds).
  These are the ones `run_tests.bat` runs. Each file targets one area,
  e.g.:
  - `tests\core\test_config.py` — config load/save, the model_path and
    download_folder persistence rules.
  - `tests\core\test_download_command.py` — the yt-dlp command builder
    (format selector, time-range, cookies).
  - `tests\core\test_history_db.py` — the SQLite history + crash-resume
    dismissal.
  - `tests\core\test_enqueue_after_download_async.py` — the non-blocking
    "transcribe after download" worker scheduling.
  - `tests\core\test_smtv_stream.py` — SMTV truncated-download handling.

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
