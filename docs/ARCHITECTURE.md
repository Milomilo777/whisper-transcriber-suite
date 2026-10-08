# Architecture

A snapshot of how the application is organized today, written for someone who needs to read or change the code. This is descriptive, not aspirational — see `ROADMAP.md` for where we want to go.

## One-paragraph summary

A Tkinter desktop app that does two related jobs: download audio/video from any yt-dlp-supported site, and locally transcribe audio/video to SRT subtitles with `faster-whisper`. The model downloads from the Hugging Face Hub on first use (resumable, each file checked against the Hub) and is cached on disk. Transcription work runs in long-lived subprocess "workers" so the model loads once and stays hot. Downloads run in worker threads inside the main process, driving `yt-dlp.exe` (a bundled binary) over `subprocess.Popen`. The UI talks to background work through `queue.Queue` instances polled from the Tk main loop.

## Process model

```
                 ┌─────────────────────────────────────┐
                 │            App (Tk main)            │
                 │  - widgets, event polling           │
                 │  - download_queue (in-process)      │
                 │  - workers[]   (subprocess refs)    │
                 └──┬──────────────────────┬───────────┘
                    │ JSON over stdio      │ subprocess.Popen
                    ▼                      ▼
        ┌─────────────────────┐   ┌──────────────────────┐
        │  Transcription      │   │  yt-dlp.exe          │
        │  worker subprocess  │   │  (one per download)  │
        │  - loads faster-    │   │  - bundled in bin/   │
        │    whisper model    │   │  - ffmpeg merges     │
        │  - one job at a     │   │    audio+video       │
        │    time             │   └──────────────────────┘
        └─────────────────────┘
```

Two kinds of concurrent work, two different patterns:

- **Transcription workers** are full Python subprocesses launched as `python -u -m core.worker`. The model load is expensive (seconds) and the model holds ~3 GB of weights, so we keep workers alive across jobs. The protocol is line-delimited JSON: parent writes `{"action":"transcribe","file_path":...}` to stdin, worker writes `{"event":"progress","percent":42}` or `{"event":"done",...}` lines back. `parallel_workers` in `config.json` caps how many of these run at once.
- **yt-dlp downloads** are short-lived child processes spawned per task. The parent thread reads `yt-dlp`'s stdout line by line, parses `[download] N.N%` to drive a progress bar, and forwards the rest to the console log. Cancellation is `task.process.terminate()`.

The Tk main loop is the only thing that touches widgets. Workers and download threads communicate through three queues that the main loop drains every 100-300 ms:

| Queue                  | Producer                  | Consumer (Tk side)        |
|------------------------|---------------------------|---------------------------|
| `worker_events`        | reader threads on each worker subprocess | `poll_worker_events`     |
| `format_events`        | `lookup_formats` thread   | `poll_format_events`      |
| `download_events`      | `process_download_queue` thread | `poll_download_events` |

## Layout

```
whisper_project_direct_download_v2/
├── gui.py                          ← Tk app, 1156 lines, all UI + orchestration
├── config.json                     ← user-editable settings
├── bin/
│   ├── ffmpeg.exe                  ← bundled (~100 MB)
│   ├── ffprobe.exe                 ← bundled (~100 MB)
│   └── yt-dlp.exe                  ← bundled (~18 MB)
├── core/
│   ├── __init__.py                 ← empty
│   ├── config.py                   ← load_config / save_config — JSON next to executable
│   ├── task.py                     ← TranscriptionTask (9 lines)
│   ├── model_manager.py            ← ensure_model: download zip, verify MD5, extract
│   ├── transcriber.py              ← faster-whisper wrapper, model lifecycle
│   └── worker.py                   ← subprocess entry point, JSON stdio protocol
└── docs/
    └── auto-subtitles-feature.md
```

`bin/` is gitignored (not in the repo) — users need ffmpeg, ffprobe, and yt-dlp executables in this folder before launching.

## Key flows

### Startup

1. `App.__init__` reads `config.json` and renders the three tabs.
2. `after(100, start_standby_worker)` spawns the first worker subprocess.
3. The worker calls `load_existing_model` — opens the WhisperModel pointed to by `config["model_path"]`. If the folder exists, it tries to load; if it doesn't exist, the worker emits `startup_error`.
4. On `startup_error`, the parent shuts the worker down, opens `ModelDownloadDialog`, and runs `ensure_model` (`model_manager.py`) which downloads the model from `config["model"]["hf_repo"]` on the Hugging Face Hub into `model_path` (resuming a cut-off download), and only then starts a fresh worker.
5. Once a worker emits `ready`, `worker_ready=True` and the UI unlocks job submission.

### Exit

1. `App.on_exit` (window close, File > Exit, Ctrl+Q, tray Exit, macOS Cmd+Q) asks about queued jobs, then marks this app's running history rows `interrupted` ("app closed").
2. `stop_all(cancel_running=True)` sends each busy worker `cancel` (it writes the resume checkpoint) and then `shutdown`; stragglers are terminated after the 5 s grace.
3. `settle_done_on_exit` finishes the rows of jobs whose `done` event (with non-empty output files) arrived during step 2; everything else stays `interrupted` and is offered for resume at the next start.
4. The history database is closed, the window destroyed, `mainloop` returns, and `gui.py` ends the process with `core.process_exit.end_process` (logs flushed, then `os._exit`), because a model download in this process runs on a library thread pool that Python would otherwise wait for.

### Transcription

1. `App.add()` appends a `TranscriptionTask` to the module-global `queue` list.
2. The 500 ms periodic `loop()` calls `process()` which finds waiting tasks, ensures an idle ready worker exists (spawning a temporary one if `parallel_workers > active`), then sends `{"action":"transcribe",...}` to its stdin.
3. The worker reads the file, calls `model.transcribe(file)`, and emits `progress` events per segment plus `log` lines with the segment text.
4. On completion the worker writes `<base>.srt` and `<base>.json` and emits `done`.
5. `finish_worker_task` either keeps the worker alive (if it's a standby) or `retire_worker`s it (temporary workers exit when the queue drains).

### Download

1. `App.add_download()` validates the form, appends a `VideoDownloadTask` to the module-global `download_queue`.
2. `process_download_queue` starts a daemon thread for the first waiting task. In the automatic update mode it first updates the user-writable yt-dlp copy at most once a day (`core.yt_dlp_update`; the bundled binary is never written, and `App.yt_dlp_path()` returns the newer of the two), then optionally a subtitle phase (`--skip-download --write-auto-subs --write-subs`), then the media phase (`-f <selector> --merge-output-format <ext>`).
3. The thread reads each `yt-dlp` stdout line, regex-matches `[download] N%` to update progress, and pushes events onto `download_events`.
4. Cancellation: `cancel_download(task)` sets `task.cancelled=True` and calls `task.process.terminate()`. The reader loop exits when stdout closes; the worker checks `task.cancelled` after `wait()` and emits `done` with status `cancelled`.

### Subtitle phase (newest feature, see `docs/auto-subtitles-feature.md`)

Inside the same download thread, before the media phase, when `task.subtitles_enabled`. Reuses `task.process` so cancel works without phase-awareness. Records `wrote_files` from `Writing video subtitles to:` lines and surfaces a summary in `subtitle_status_var` next to the combo.

### Format lookup

Typing in the URL field debounces 800 ms, then a daemon thread runs `yt-dlp --dump-single-json --no-playlist`. The audio and video combo are populated from `info["formats"]`, and `current_video_language` is captured from `info["language"]` (falling back to the first key of `info["automatic_captions"]`) for "Automatic" subtitle resolution.

## Threading rules

- Tkinter is single-threaded. Only `poll_*` methods (running on the Tk main loop) touch widgets.
- Workers and download threads only put events on queues. They never call `self.something_var.set(...)` directly.
- Subprocess `stdout` is read on a dedicated daemon thread per process. The reader pushes JSON events (worker) or raw lines + parsed progress (yt-dlp) onto the appropriate queue.
- `download_current` is a module global protected only by the convention that `process_download_queue` is only called from the Tk main loop and from itself via queue events on the Tk main loop. There's no lock — it works because all state transitions happen on the main thread.

## Cancellation contract

| Layer | Mechanism |
|-------|-----------|
| Tk → worker | `worker["process"].terminate()` (+ optional `{"action":"shutdown"}` on stdin first) |
| Tk → yt-dlp | `task.process.terminate()` |
| Inside transcribe loop | per-segment `if task.cancelled: return` check |
| Inside model download | `cancel_event` (threading.Event) checked at chunk boundaries and per MD5 file |

Cancel must always be safe to call multiple times and from the Tk main thread.

## Configuration

`config.json` lives next to the executable / source. Schema (current):

```json
{
  "model": {
    "name": "...",          // model folder name, display name
    "hf_repo": "..."        // Hugging Face repo ensure_model downloads from
  },
  "model_path": "...",       // absolute path where the model is extracted
  "device": "auto",          // "auto" | "cpu" | "cuda"
  "compute_type": "int8",    // faster-whisper compute_type
  "parallel_workers": 2,
  "download_folder": "...",
  "download_subtitles_enabled": false,
  "download_subtitle_lang": "Automatic"
}
```

`save_config` is called whenever the user changes the download folder, toggles the subtitle checkbox, or picks a subtitle language. The model section is not edited by the UI today.

## Worker stdio protocol

Newline-delimited JSON. Lines that fail to parse become `{"event":"log","message":<raw line>}` (e.g. uncaught Python prints, traceback fragments). Every event gets `_pid` and `_worker_id` injected by the reader before going on the queue so the parent can route it to the right worker entry.

Parent → worker actions:
- `{"action": "transcribe", "file_path": "..."}`
- `{"action": "shutdown"}`

Worker → parent events:
- `{"event": "ready"}` — model loaded, accepting jobs
- `{"event": "startup_error", "message": "..."}` — model load failed before becoming ready
- `{"event": "started", "file_path": "..."}` — beginning a job
- `{"event": "progress", "percent": N}` — emitted per segment
- `{"event": "log", "message": "..."}` — non-structured log line
- `{"event": "done", "file_path": "..."}` — job finished successfully
- `{"event": "error", "message": "...", "file_path": "..."}` — job failed
- `{"event": "worker_exit", "return_code": N}` — synthesized by the parent's reader thread when stdout closes

## Why this shape

- **Subprocess workers, not threads, for transcription**: faster-whisper / CTranslate2 / torch are not free-threaded. A crash inside the model takes the worker down without killing the UI. Reloading the model after a crash is just `restart_worker`.
- **yt-dlp via subprocess, not as a library**: the project ships `yt-dlp.exe` as a vendored binary so users don't need a Python yt-dlp install, and updates are `yt-dlp --update` rather than `pip install -U`. Trade-off: we parse stdout instead of subscribing to a progress hook.
- **JSON event protocol, not direct return values**: keeps the worker decoupled from Tk and means we can swap the parent UI without touching the worker. It also gives us free observability — the JSON event log is the diagnostic trail.
- **Queues over callbacks**: Tk has no built-in async, and `after(N, cb)` polling of a `queue.Queue` is the canonical way to bridge threads/subprocesses into the Tk main loop without locking.
