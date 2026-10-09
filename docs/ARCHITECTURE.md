# Architecture

A snapshot of how the application is organized today, written for someone who needs to read or change the code. This is descriptive, not aspirational — see `ROADMAP.md` for where we want to go. File sizes are left out on purpose: they go stale with every change, so use `wc -l` when you need one.

## One-paragraph summary

A Tkinter desktop app that does two related jobs: download audio/video from any yt-dlp-supported site, and locally transcribe audio/video to subtitle and transcript files, by default with `faster-whisper`. The model downloads from the Hugging Face Hub on first use (resumable, each file checked against the Hub) and is cached on disk. Transcription work runs in long-lived subprocess "workers" so the model loads once and stays hot. Downloads run in worker threads inside the main process, driving the bundled yt-dlp binary over `subprocess.Popen`. The UI talks to background work through `queue.Queue` instances polled from the Tk main loop. The `App` object (`app/app.py`) owns the state and the queues; the heavy logic lives in four service classes under `app/services/`.

## Process model

```
                 ┌─────────────────────────────────────────┐
                 │              App (Tk main)              │
                 │  - widgets, event polling               │
                 │  - queue / download_queue (task lists)  │
                 │  - workers[]   (subprocess refs)        │
                 │  - services: Transcription, Download,   │
                 │    Format, Integrations                 │
                 └──┬──────────────────────┬───────────────┘
                    │ JSON over stdio      │ subprocess.Popen
                    ▼                      ▼
        ┌─────────────────────┐   ┌──────────────────────┐
        │  Transcription      │   │  yt-dlp              │
        │  worker subprocess  │   │  (one per download   │
        │  - loads the ASR    │   │   or format lookup)  │
        │    engine           │   │  - bundled in bin/   │
        │  - one job at a     │   │  - ffmpeg merges     │
        │    time             │   │    audio+video       │
        └─────────────────────┘   └──────────────────────┘
```

Two kinds of concurrent work, two different patterns:

- **Transcription workers** are full Python subprocesses launched as `python -u -m core.worker` (`gui.py --worker` in a frozen build). The model load is expensive (seconds) and the model holds gigabytes of weights, so workers stay alive across jobs. The protocol is line-delimited JSON: the parent writes `{"action":"transcribe","file_path":...}` to stdin, the worker writes `{"event":"progress","percent":42}` or `{"event":"done",...}` lines back. `parallel_workers` in `config.json` caps how many run at once. A worker reads `config.json` once, at start, so per-file options (speaker labels, VAD, word timestamps, chapters, ...) travel with each `transcribe` command as a `settings` snapshot taken at dispatch (`core/task_settings.py`); engine and model keys stay fixed for the worker's life.
- **yt-dlp downloads** are short-lived child processes spawned per task. The download thread reads yt-dlp's stdout line by line, parses the progress to drive a progress bar, and forwards the rest to the console log. Cancellation kills the process tree (`core/_proc.py`), so the ffmpeg merge child dies with yt-dlp.

Three smaller processes follow the same worker pattern and are not covered further here: the Live tab spawns its own `core.worker` and sends it `transcribe_live` chunks (`app/services/live_service.py`), Clone Your Voice has a separate worker (`core/voice_clone_worker.py`, `app/services/voice_clone_service.py`), and the optional web/LAN job server lives in `core/server/` (see `SERVER.md`).

The Tk main loop is the only thing that touches widgets. Background threads hand results over through queues that the main loop drains:

| Queue (on `App`)  | Producer                                             | Consumer (Tk side)                     | Period |
|-------------------|------------------------------------------------------|----------------------------------------|--------|
| `worker_events`   | one reader thread per worker subprocess              | `TranscriptionService.poll`            | 100 ms, only while a worker exists |
| `format_events`   | the `format-lookup` thread (`FormatService.lookup_formats`) | `FormatService.poll`            | 200 ms |
| `download_events` | the `download-task` thread (`DownloadService._run_task`)    | `DownloadService.poll`          | 300 ms |

A fourth queue, `_main_thread_calls`, takes any callable from any thread (`App.post_to_main`) and is drained every 50 ms by `_drain_main_calls`; the watched-folder thread has its own queue, `_watched_path_queue`. Python 3.14 raises when `after()` is called off the main thread, so these queues are the only safe way across.

## Layout

```
gui.py                      entry point: GUI, --worker, --voice-clone-worker, `transcribe`, `serve`
app/
├── app.py                  App: Tk root, state, queues, menus, the 500 ms loop
├── services/
│   ├── transcription_service.py   worker lifecycle, dispatch, event handling, finish_task
│   ├── download_service.py        yt-dlp command building and the download threads
│   ├── format_service.py          format lookup for the URL field
│   ├── integrations_service.py    oTranscribe import/export
│   ├── live_service.py, voice_clone_service.py, subbed_video.py
├── domain/                 task models for the queues (VideoDownloadTask, ...), languages
├── dialogs/, widgets/      windows and tab pages (widgets/tabs.py builds the main tabs)
└── theme/                  design tokens, colours, per-OS window chrome
core/
├── config.py               load_config / save_config, DEFAULT_CONFIG, platform folders
├── task.py                 TranscriptionTask (the transcription queue item)
├── task_settings.py        per-task options snapshot sent to the worker
├── worker.py               worker subprocess entry point, JSON stdio protocol
├── transcriber.py          transcription pipeline, model lifecycle, output writing
├── backends/               ASR engines (faster-whisper, whisper.cpp, NVIDIA, cloud)
├── writers/                one module per output format
├── model_manager.py, hub.py   model catalog, Hub download, model folders
├── history.py              SQLite history of downloads and transcriptions
├── yt_dlp_update.py        user-writable, self-updating yt-dlp copy
├── optional_deps.py        on-demand optional packages
├── server/                 optional HTTP job server
└── integrations/           oTranscribe, SMTV
bin/                        ffmpeg, ffprobe, yt-dlp, Deno (gitignored; see BUILD.md)
tests/                      hermetic suite; tests/smoke/ needs real resources
```

`bin/` is gitignored (not in the repo): `docs/BUILD.md` shows how a build fills it, and on Linux and macOS a yt-dlp or ffmpeg found on `PATH` is used when `bin/` has none. `AGENTS.md` carries the shorter top-level map.

## Key flows

### Startup

1. `gui.py` `main()` handles the worker modes and the `transcribe` / `serve` commands first; otherwise it calls `app.run()`, which builds `App`.
2. `App.__init__` loads `config.json` (`core.config.load_config`), creates the queues and the four services, builds the tabs and arms the loops: `App.loop` (500 ms), `FormatService.poll`, `DownloadService.poll` and `_on_start`.
3. `_on_start` shows the first-run windows when they apply (the quick start, then the model-folder picker). **No worker starts at launch**: loading the model costs about 1.5 GB of RAM and a CPU spike, which is wasted for a session that only downloads or browses history.
4. The first transcription goes through `App._ensure_transcribe_ready`. If the model files are missing it asks, then runs `ModelDownloadDialog`, which calls `ensure_model` (`core/model_manager.py`) to fetch the model from `config["model"]["hf_repo"]` on the Hugging Face Hub into the model folder (resuming a cut-off download).
5. `TranscriptionService.ensure_worker_ready` then spawns a worker (`start_worker`) and shows `ModelLoadingDialog` until the worker emits `ready`. Automation paths (watched folder, crash resume) wait for `ready` without a dialog.
6. If the worker emits `startup_error` with the default engine, the parent finishes any in-flight tasks as errors, stops all workers and opens the mandatory download dialog. For another engine (whisper.cpp, NVIDIA, cloud) it shows that engine's own error instead, since downloading the Whisper model cannot fix it.

### Exit

1. `App.on_exit` (window close, File > Exit, Ctrl+Q, tray Exit, macOS Cmd+Q) asks about queued jobs, then about unsaved edits (each transcript viewer: Save / Discard / Cancel, then the Live tab's transcript; Cancel or a failed save keeps the app open untouched), then marks this app's running history rows `interrupted` ("app closed").
2. Running package installs are stopped and their merge step is awaited (`core.optional_deps.wait_until_idle`, up to 30 s). Then `stop_all(cancel_running=True)` sends each busy worker `cancel` (it writes the resume checkpoint) and then `shutdown`; stragglers are terminated after a 15 s grace (5 s for a worker with no job). The stop covers installs started by the app process only; installs run by a worker process (Google Cloud, NVIDIA engines) are not stopped by it. At the next start `core.optional_deps.sweep_install_leftovers` restores or removes what a cut install left (`.bak-<pid>`, `.merge-<pid>`, `pylibs-stage-*`) for processes that no longer exist.
3. `settle_done_on_exit` finishes the rows of jobs whose `done` event (with non-empty output files) arrived during step 2; everything else stays `interrupted` and is offered for resume at the next start.
4. The history database is closed, the window destroyed, `mainloop` returns, and `gui.py` ends the process with `core.process_exit.end_process` (Sentry and logs flushed with a 3 s cap, then `os._exit`), because a model download in this process runs on a library thread pool that Python would otherwise wait for.

### Transcription

1. `App.add()` (or the batch, watched-folder, crash-resume and download-hand-off paths) creates a `TranscriptionTask` and appends it to `App.queue` (a per-instance list) after the gates in `_ensure_transcribe_ready`.
2. `App.loop` runs every 500 ms and calls `TranscriptionService.dispatch_waiting`. It spawns temporary workers while `parallel_workers` allows, inserts the history row, stamps the current output formats and settings onto the task, and writes `transcribe_command(task)` to an idle worker's stdin from a daemon thread.
3. The worker (`core/worker.py`) calls `core.transcriber.transcribe`, which emits `progress` events and `log` lines, keeps a resume checkpoint, and writes the selected formats through `core/writers/`.
4. The worker emits `done` with the files it wrote. `TranscriptionService.poll` routes the event to `finish_task`, which writes the history row **before** it reports success to the UI, updates the linked download row, and retires the worker if it was a temporary one and no task is waiting (`retire_worker`). The worker started by `ensure_worker_ready` stays alive for the next job.
5. A worker that stops sending events (heartbeats included) for `LIVENESS_TIMEOUT_S` is declared wedged and restarted (`restart_worker`); a worker process that died without its `worker_exit` is detected by `_expire_dead_workers`.

### Download

1. `App.add_download()` calls `DownloadService.enqueue_from_form()`, which validates the form and appends one or more `VideoDownloadTask` items to `App.download_queue`.
2. `App.loop` also calls `DownloadService.process_queue`. Only one download runs at a time (`App.download_current`); the next waiting task starts a `download-task` daemon thread running `_run_task`.
3. `_run_task` first checks Work offline and, in the automatic update mode, updates the user-writable yt-dlp copy at most once a day (`core.yt_dlp_update`; the bundled binary is never written, and `App.yt_dlp_path()` returns the newer of the two). Then it runs the optional subtitle phase (`--skip-download --write-auto-subs --write-subs`), then the media phase (`-f <selector> --merge-output-format <ext>`). SMTV links and the caption-only shortcut take their own branches (`_run_smtv_task`, `_run_caption_only_task`).
4. The thread reads each yt-dlp stdout line, passes it through `parse_progress_line` and `parse_destination_line`, and pushes `(kind, task, payload)` tuples onto `download_events`. The kinds are `progress`, `log`, `subtitle_status`, `done`, `done_full` and `error`.
5. Cancellation: `App.cancel_download(task)` sets `task.cancelled`, tree-kills `task.process` and, for a task that has no running thread (paused or waiting), cleans up directly. A running download's thread sees the flag after yt-dlp exits and posts `("done", task, "cancelled")`. Pause (`App.pause_download`) is stop-and-continue: the process is killed, the partial files stay, and resume starts a fresh run on the same task.
6. When a download finishes (`DownloadService._finish`) and auto-transcribe or "Make subtitled video" is on, the file is queued for transcription (`App.enqueue_transcription_from_download`) and the download row shows `transcribing` while it runs.

### Subtitle phase (see `docs/auto-subtitles-feature.md`)

Inside the same download thread, before the media phase, when `task.subtitles_enabled`. Reuses `task.process` so cancel works without phase-awareness. Records the files from the `Writing video subtitles to:` lines and surfaces a summary in `subtitle_status_var` next to the combo. A subtitle problem never aborts the media download.

### Format lookup

Typing in the URL field debounces 800 ms (`FormatService.schedule_lookup`), then a `format-lookup` daemon thread runs `yt-dlp --dump-single-json --no-playlist` and posts `("formats", url, info)` or `("error", url, message)` to `format_events`. `FormatService.poll` fills the audio and video combos from `info["formats"]` and captures `current_video_language` from `info["language"]` (falling back to the first key of `info["automatic_captions"]`) for "Automatic" subtitle resolution. A result for a URL that is no longer in the field is dropped.

## Threading rules

- Tkinter is single-threaded. Only code running on the Tk main loop (the service `poll()` methods, `loop`, `_drain_main_calls` and Tk callbacks) touches widgets.
- Workers and download threads only put events on queues, or hand a callable to `App.post_to_main`. They never call `self.something_var.set(...)` directly.
- Subprocess `stdout` is read on a dedicated daemon thread per process (`core._threads.safe_thread` logs an uncaught exception). The reader pushes JSON events (worker) or raw lines plus parsed progress (yt-dlp) onto the appropriate queue.
- `App.download_current` and the task lists are plain instance attributes with no lock. They are safe because every state transition happens on the Tk main thread: `process_queue` is called only from `loop` and from queue events handled by `DownloadService.poll`. Download threads mostly read the task flags (`cancelled`, `paused`) and post events; the few fields they write, such as `task.process`, are guarded by a per-run generation counter so a stale run cannot touch a resumed one.

## Cancellation contract

| Layer | Mechanism |
|-------|-----------|
| Tk → transcription worker, one job | cooperative `{"action":"cancel","task_id":...}` through `TranscriptionService.send_control`; the transcriber checks `task.cancelled` between segments and writes a resume checkpoint |
| Tk → transcription worker, stopping it | `{"action":"shutdown"}` on stdin, then `kill_process_tree` after a grace period if it ignores it (`stop_worker`, `stop_all`) |
| Tk → yt-dlp | `kill_process_tree(task.process)` (`cancel_download`, `pause_download`) |
| Inside the model download | `cancel_event` (`threading.Event`) checked at chunk boundaries and per file in `ensure_model` |

Cancel must always be safe to call multiple times and from the Tk main thread.

## Configuration

`config.json` lives in the per-user folder from `platformdirs.user_config_dir("WhisperTranscriberSuite")` (on Windows `%LOCALAPPDATA%\WhisperTranscriberSuite`), not next to the executable; `core.config.migrate_config_location` moves a legacy copy there. `DEFAULT_CONFIG` in `core/config.py` is the authoritative list of keys and their defaults, and `docs/CONFIG.md` explains how the file is merged, read and saved (atomic writes, a lock file shared by every process, a `.bak` copy). The few keys that shape the architecture:

```json
{
  "model": { "name": "...", "hf_repo": "..." },  // model chosen from the catalog; hf_repo is what ensure_model downloads
  "model_path": "...",       // folder holding the model files
  "device": "auto",          // "auto" | "cpu" | "cuda"
  "compute_type": "int8",    // faster-whisper compute_type
  "parallel_workers": 2,     // cap on concurrent transcription workers
  "output_formats": ["srt", "json"]  // written per task, sent with each transcribe command
}
```

`save_config` writes only the keys this process changed, so the app, its workers, the server and the CLI can share one file without overwriting each other.

## Worker stdio protocol

Newline-delimited JSON. Lines that fail to parse (or parse to something other than an object) become `{"event":"log","message":<raw line>}` (e.g. uncaught Python prints, traceback fragments). The parent's reader injects `_pid` and `_worker_id` into every event; the worker adds `_token`, the per-spawn id the parent passed in `WHISPER_WORKER_TOKEN`, so a late event from a restarted worker is never credited to its replacement (`TranscriptionService.worker_for_event`). The module docstring of `core/worker.py` is the authoritative field list; this is the shape of it.

Parent → worker actions:
- `{"action": "transcribe", "file_path": "...", "task_id": "...", "language": ..., "settings": {...}, ...}`: the command is built by `transcribe_command` in `transcription_service.py`
- `{"action": "cancel" | "pause" | "resume", "task_id": "..."}`: applied at once by a dedicated reader thread, because the main thread is busy inside `transcribe()`
- `{"action": "transcribe_live", "file_path": "...", "id": ...}`: Live tab chunks; replies with `live_result` or `live_error`
- `{"action": "shutdown"}`

Worker → parent events:
- `{"event": "ready"}`: model loaded, accepting jobs (additive fields report the device the model landed on)
- `{"event": "startup_error", "message": "..."}`: model load failed before becoming ready
- `{"event": "started", "file_path": "..."}`: beginning a job
- `{"event": "progress", "percent": N}`: emitted per segment; additive `speed_x` / `eta_s` once the speed meter has enough data ([SPEED_METER.md](SPEED_METER.md))
- `{"event": "language_detected", ...}`, `{"event": "log", "message": "..."}`: informational
- `{"event": "done", "file_path": "...", ...}`: job finished; carries the written output paths and stats
- `{"event": "error", "message": "...", "file_path": "..."}`: job failed
- `{"event": "control_applied" | "control_unmatched", ...}`: acknowledgement of a cancel/pause/resume
- `{"event": "heartbeat", "ts": ...}`: every 5 s, feeds the liveness watchdog
- `{"event": "worker_exit", "return_code": N}`: synthesized by the parent when the worker's stdout closes (or by `_expire_dead_workers`)

## Why this shape

- **Subprocess workers, not threads, for transcription**: faster-whisper / CTranslate2 / torch are not free-threaded. A crash inside the model takes the worker down without killing the UI. Reloading the model after a crash is just `restart_worker`.
- **yt-dlp via subprocess, not as a library**: the project ships a vendored yt-dlp binary so users don't need a Python yt-dlp install, and a second user-writable copy can update itself (`core/yt_dlp_update.py`) without admin rights. Trade-off: we parse stdout instead of subscribing to a progress hook.
- **JSON event protocol, not direct return values**: keeps the worker decoupled from Tk and means we can swap the parent UI without touching the worker. It also gives us free observability — the JSON event log is the diagnostic trail.
- **Queues over callbacks**: Tk has no built-in async, and `after(N, cb)` polling of a `queue.Queue` is the canonical way to bridge threads/subprocesses into the Tk main loop without locking.
- **Services over one big class**: `App` keeps the state and the widgets; the download, transcription and lookup logic sits in `app/services/` so it can be tested with a fake `App`.
