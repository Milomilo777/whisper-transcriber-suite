# OpenCode handoff — misc features review (watcher / recorder / monitors / tiling / burn_subs)

Scope reviewed in full: `core/watcher.py`, `core/recorder.py`, `core/monitors.py`,
`core/tiling.py`, `core/burn_subs.py`, plus their tests
(`tests/core/test_watcher.py`, `test_recorder.py`, `test_fixpack_recorder.py`,
`test_monitors.py`, `test_tiling.py`, `test_tiling_ffplay.py`,
`test_fixpack_tiling_divisions.py`, `test_fixpack_sw3_tilingthreads.py`,
`test_fixpack_bl_tilingmon.py`, `test_burn_subs.py`).
`app/app.py`, `core/live.py` and `core/_proc.py` were read for caller context only and
deliberately not modified (out of scope).

Verification (final tree): `pyright app core` = 0 errors / 0 warnings / 0 informations;
`python -m pytest tests/ --ignore=tests/smoke -q` = exit 0, no failures
(2199 tests collected). One mid-session full run showed a single failure in
`tests/core/test_search_dialog.py::test_open_selected_with_no_selection_is_a_noop`
(Tk construction, unrelated to any changed file); it passed immediately when re-run
alone, and the following two full-suite runs were fully green — treated as the known
intermittent Tk flake, not a regression.

## Real bugs fixed

### 1. Watched folder silently ignored files MOVED into it

`core/watcher.py`'s handler implemented only `on_created`. watchdog reports a file
that is moved/renamed into the watched directory as a **moved** event, not a created
one — confirmed in watchdog 6.0.0's `read_directory_changes.WindowsApiEmitter`
(`FILE_ACTION_RENAMED_NEW_NAME` → `FileMovedEvent(src, dest)`; a move-in from outside
the folder has no paired old-name, so it only ever arrives as `on_moved`), and
identically on Linux via `IN_MOVED_TO`.

Effect (real, user-visible): Explorer's default drag on the same volume is a *move*, so
"drop a media file into the watched folder" — the feature's headline flow — did
nothing. The same applies to downloaders that write `name.mp4.part` and rename it to
`name.mp4` on completion (the only event seen is the rename).

Fix: the handler now shares one `_dispatch(path)` (bytes-decode + media-extension
gate + callback + Audit-A8 `on_error` hook) between `on_created` and a new `on_moved`
that dispatches `event.dest_path`. `on_moved` also ignores directories and filters out
moves OUT of the folder via a new `_is_inside(folder, path)` helper (some backends
report those; enqueueing a file that just left the folder would be wrong).

Tests (`tests/core/test_watcher.py`, all hermetic — fake `watchdog.*` modules capture
the handler handed to `Observer.schedule`): moved-in media dispatches the dest path
(including a bytes dest), moved-out is ignored, non-media/directories are ignored,
`on_created` still dispatches, and the `on_error` hook fires for a moved event.

### 2. `burn()` wrote straight to the user's chosen path (non-atomic)

`core/burn_subs.py` invoked ffmpeg with the final `out_path` as its output. ffmpeg
`-y` truncates that file the moment it starts, so any mid-way failure (bad source,
disk full, the 1 h timeout) left a corrupt partial `.mp4` under the user's chosen name
— and if the user had picked a path that already held a file, that file was destroyed
before ffmpeg even knew whether it could proceed.

Fix: encode into `mkstemp(prefix=".burn-", suffix=<same ext>, dir=<out dir>)` (same
directory ⇒ same filesystem) and only `os.replace()` it onto `out_path` after ffmpeg
succeeds; the temp is unlinked in `finally` on every failure path. Same-directory use
of `mkstemp` guarantees the replace is atomic and keeps ffmpeg's extension-based format
inference working.

Tests: `test_burn_failure_does_not_clobber_existing_output` (existing bytes survive; no
`.burn-*` leftover; exactly one ffmpeg attempt), plus the updated
`test_burn_video_path_passed_unescaped_as_input` (the argument is now a temp sibling)
and the two existing cleanup tests still pass.

### 3. `burn()` failed outright when the output container rejects the source audio codec

`burn()` always passed `-c:a copy`, but the Save dialog suggests `.mp4`, which cannot
carry Opus/Vorbis audio. A source downloaded as `.webm`/`.mkv` (yt-dlp keeps Opus for
those) makes ffmpeg fail with
`Could not find tag for codec opus in stream #1, codec not currently supported in
container` — the whole subtitle burn failed for perfectly valid media. (The module
docstring claimed "H.264 + AAC" while the code copied the audio, so the two never
agreed.)

Fix: keep the lossless, fast `-c:a copy` as the first attempt; if ffmpeg fails with
one of the two known container/codec-rejection phrases in stderr, retry ONCE with
`-c:a aac`. Unrelated ffmpeg failures are never retried, and when the caller supplied
its own audio codec via `extra_args` the retry is skipped so their choice is not
overridden (`-c:a` is emitted before `extra_args`, preserving the original
later-wins precedence). The docstring now describes the real behaviour.

Tests: `test_burn_retries_with_aac_when_container_rejects_audio` (two calls,
`["copy", "aac"]`, output produced, no temp leftovers),
`test_burn_container_failure_with_caller_codec_is_not_retried`,
`test_burn_aac_retry_failure_is_reported`, and the generic-failure test asserts no
retry pass.

### 4. Recorder availability probes let native-load `OSError` escape into UI callbacks

`core/recorder.py`'s `mic_available()` / `loopback_available()` caught only
`ImportError`. A present-but-broken native backend raises `OSError` at import time —
sounddevice's documented `PortAudio library not found` (common on Linux without
`libportaudio2`) or a DLL-load failure for pyaudiowpatch on Windows. That exception
propagated out of `voice_clone_tab._record_sample` (calls `mic_available()` directly)
and `live_tab._start` → `core.live.is_available()` → `mic_available()` as an unhandled
Tk callback error, instead of the intended graceful "cannot record" state. This is the
same bug class the repo already fixed for diarization/parakeet/whisper_cpp probes.

Fix: new `_import_failure(module_name)` helper (returns the exception or None) backs
both probes; non-ImportError failures now return False and
`mic/loopback_availability_reason()` reports `"<module> could not be loaded: …"` so the
user sees the real cause. Missing-package behaviour and its message are unchanged.

Tests: `test_mic_available_false_when_portaudio_fails_to_load`,
`test_loopback_available_false_when_pyaudio_fails_to_load` (monkeypatch
`builtins.__import__` to raise the realistic `OSError`).

### 5. Tiling launch-failure / superseded-launch teardown did not reap killed children

The earlier zombie fix reaped killed yt-dlp/ffplay children only inside
`_terminate()`. Two other teardown paths kill processes without waiting on them:
the `_start` launch-failure `except` handler, and the `not published` path (a Stop or
new `start()` that raced the launch). The engine loops on launch failures with
backoff, so a wall that keeps failing to spawn (e.g. a persistently broken launch)
accumulated un-reaped `<defunct>` children for the whole outage on macOS/Linux.

Fix: both paths now collect `[ytdlp, *ffplay]` and call the existing `self._reap(...)`
helper (best-effort `wait(timeout=2)`, never raises), matching `_terminate`.

Tests (`tests/core/test_fixpack_sw3_tilingthreads.py`): the launch-failure test's fake
Popen now records `wait()` and asserts both spawned children were reaped; a new
`test_start_superseded_launch_reaps_killed_children` drives the `not published` path
and asserts the same for its two children.

## Read fully, no new real bugs found

- `core/monitors.py` — `_from_screeninfo` / `_from_win32` (thread-scoped per-monitor
  DPI awareness) / single-monitor fallback, the `(x, y, name)` total sort, the
  already-empty-list guards in `primary_index`/`select_monitors`, and the geometry
  helpers all hold up against the documented invariants (stable spatial indexing,
  graceful degradation, and graceful empty-list handling). Deliberately not changed:
  the DPI work scopes awareness to the thread only and I found no evidence of a real
  defect in that design from this environment.

## Deliberately not changed (considered and dropped in the adversarial re-read)

- Reordering `TilingController.start()`'s generation bump ahead of `self.stop()` — the
  code comment says "bump FIRST" but the observable impact is only a possible stray
  "Stopped." status flash; the join already prevents any real overlap, so touching
  race-sensitive mature code for a cosmetic race was not justified.
- `_terminate(join=False)` still runs `_reap` on the UI thread; `wait()` on an
  already-killed child returns in practice, and changing it risks re-introducing the
  zombie leak the fixpack closed.
- Watcher `stop()`'s 2 s observer-join timeout and the app-level finished-file
  re-enqueue dedup question are pre-existing documented trade-offs / owner calls.

## Second-pass independent re-check (muse-spark-1.3-contributor) — 2026-09-20

Re-read the handoff above, then the real diff (`git diff master..HEAD`),
then re-verified each claimed fix by reverting the single `core/` file to
its `master` version and re-running that subsystem's new tests.

### What was verified and how (all revert-proven)

- Watcher `on_moved`: `master` has 0 `on_moved` refs. With `core/watcher.py`
  reverted, 4 tests fail (`dispatches_moved_in_media`, `moved_out_is_ignored`,
  `moved_non_media_and_dirs_ignored`, `moved_callback_error_hits_on_error`
  — `AttributeError: on_moved`); restored, all pass. Claim holds.
- Burn AAC retry: reverted, `test_burn_retries_with_aac...` fails with the
  exact real-world error (`Could not find tag for codec opus ... not
  currently supported in container`) and `test_burn_video_path...` fails on
  the `cmd[-1] != out` temp-sibling assertion; restored, all pass.
- Recorder OSError probe: reverted, both new tests fail with the raw
  `OSError: DLL load failed` escaping; restored, both pass. Claim holds.
- Tiling reap on both teardown paths: reverted, `test_start_launch_failure...`
  and `test_start_superseded_launch_reaps_killed_children` fail; restored,
  pass. Claim holds.

One honesty note on test strength (not a code defect): with `subprocess.run`
mocked, `test_burn_failure_does_not_clobber_existing_output` passes even on
the OLD code, because the mock never truncates `out_path` the way real
`ffmpeg -y` does. The atomicity is still proven — structurally, by
`test_burn_video_path...`'s `cmd[-1] != out` + same-dir + ext assertions
(which fail on old) plus correct `mkstemp(same dir)` → `os.replace` →
`finally unlink` code — but the clobber test alone is not a discriminating
regression test. Left as-is (it still guards the finally-cleanup); just
noted so nobody over-claims for it.

### Fresh adversarial pass — no further real bugs

Re-examined the same files plus immediate surroundings; checked and cleared:

- `burn()`: retry loop terminal logic (`codec == codecs[-1]` raise, no retry
  on generic errors/timeout, caller-codec skip), `os.replace` after success,
  `finally` unlink swallowing only `OSError`, `_extra_args_set_audio_codec`
  prefix matching (worst case it conservatively skips a retry), empty-suffix
  edge (same inference behaviour as before — not a regression).
- `watcher._is_inside`: `bytes` decode, empty-path, cross-drive
  `(OSError, ValueError)` guards all present; `on_created` needs no inside
  check (non-recursive schedule); no-attr `dest_path` defaults to ignored.
- `recorder._import_failure`: `except Exception` (not `BaseException`, so no
  `KeyboardInterrupt` swallow); double-import cost is `sys.modules`-cached.
- `tiling`: `_retire` (kill without wait) is transient-only — the retired proc
  stays in `_consumers` and is reaped at the next `_terminate`/relaunch, so no
  pileup. The `not published` path's missing sentinel/join vs the
  launch-failure path is correct, not an omission: the running fan-out
  thread's `finally` delivers the `None` sentinels and all threads involved
  are daemons that exit on their own (the `except` path needs the manual
  sentinel precisely because its fan-out may never have started).
- `monitors.py` (full read): `_from_screeninfo`/`_from_win32`/fallback chain,
  thread-scoped DPI context with restore, `(x, y, name)` total sort, empty
  guards, geometry helpers — all hold. One theoretical `KeyError`
  (`select_monitors` single-mode with gapped non-sequential indices) is
  unreachable via `list_monitors()` output; not changed.

No code changes from this pass — the first pass was sound.

### Final verification (this pass, final tree)

- `python -m pyright app core` → 0 errors / 0 warnings / 0 informations.
- `python -m pytest tests/ --ignore=tests/smoke -q` → exit 0, 2199 collected,
  fully green (no flakes this run).
