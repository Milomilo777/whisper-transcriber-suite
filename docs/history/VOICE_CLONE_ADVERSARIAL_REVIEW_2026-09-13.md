# Clone Your Voice / Text to Voice — Adversarial Code Review

**Date:** 2026-09-13

**Scope.** Line-by-line adversarial review of the "Clone Your Voice / Text to
Voice" feature (3 phases, merged to master): `core/voice_clone.py`,
`core/voice_clone_worker.py`, `app/services/voice_clone_service.py`,
`app/widgets/voice_clone_tab.py`, and `tests/core/test_voice_clone.py`, read
in full. Cross-checked against the integration points in `core/hub.py`,
`core/optional_deps.py`, `core/config.py`, `app/app.py`, and `gui.py`
(grepped for `voice_clone`/`VoiceClone`, matching regions read with
surrounding context), plus `core/_proc.py`, `core/recorder.py`,
`core/transcriber.py::get_duration`, `installer_embed.iss`, and
`docs/BUILD.md` where needed to verify a specific claim (subprocess
tree-kill behavior, mic-recording fallback behavior, ffprobe edge cases,
and how the opt-out marker actually gets created). The goal was to find
real, triggerable bugs — not style feedback. `embed_build/`'s copies of all
four source files were diffed against `core`/`app` and are byte-identical,
so all findings below apply equally to both.

No P0 (crash / security) issues were found. Every failure path traced in
this review — install failure, worker-spawn failure, stdin-write failure,
worker crash mid-generation, worker killed out from under an in-flight
call, `ffmpeg`/`ffprobe` failures — is caught by a broad `except Exception`
somewhere in the chain and correctly reaches `_generate_failed` /
`show_error`, and the Generate button is reliably re-enabled in every
traced case. Subprocess argument construction is list-based throughout
(no `shell=True`, no string interpolation into a shell command), and the
worker protocol uses plain `json.loads`/`json.dumps` (no `pickle`/`eval`),
so shell-injection and deserialization risk are both clean. 3 P1s and 8
P2s were found; see below.

---

## P1 findings

### P1-1: Reference samples that fail *hard* validation are added anyway, not just soft ones

**File:** `app/widgets/voice_clone_tab.py:167-184` (`_add_sample`), root cause
shared with `core/voice_clone.py:108-137` (`validate_reference_sample`).

```python
def _add_sample(app: Any, path: str) -> None:
    from core.voice_clone import MAX_REFERENCE_SAMPLES, validate_reference_sample

    if len(app.vc_samples) >= MAX_REFERENCE_SAMPLES:
        show_error(...)
        return
    issue = validate_reference_sample(path)
    if issue is not None:
        show_error(app, "This clip may not work well", issue.message)
        # Still added -- the user may know better than the heuristic
        # (e.g. a clip a hair under/over the recommended range).
    app.vc_samples.append(path)
```

`validate_reference_sample` returns the same `ReferenceIssue` type for two
very different classes of problem: (a) soft, "quality" issues where the
comment's rationale genuinely applies — clip a bit under/over the
3-10s recommended range — and (b) hard failures where there is no usable
audio at all: `"File not found."` (path doesn't exist), `f"Could not read
this audio file: {e}"` (ffprobe/format error), and `"Could not determine
the clip's length."` (duration `<= 0`, e.g. ffprobe returns non-numeric
`N/A` — see `core/transcriber.py:476-485`). `_add_sample` treats all of
these identically and appends the path regardless.

**Concrete failure scenario:** the user clicks "Record sample," the mic
disconnects or the backend produces zero frames mid-capture. Per
`core/recorder.py:190-223`, `Recorder.stop()` is documented to always
return a path to an *existing* file — if the capture loop never wrote a
real WAV, `stop()` synthesizes a valid empty placeholder WAV specifically
"so the caller's 'open this file' path doesn't crash." `validate_reference_sample`
correctly detects this (ffprobe reports `0.0`/`N/A` duration → "Could not
determine the clip's length"), shows the warning dialog — and then adds
the unusable clip to `app.vc_samples` anyway. If this is the user's only
sample, `core/voice_clone.py:208` passes it straight through as
`ref_audio` to `model.generate(...)` with no further check. Depending on
how OmniVoice's own audio loader handles a zero-length reference, this
either raises deep inside the model after the multi-minute first-run
model load has already completed (a confusing, delayed failure instead of
an immediate one the app already had the answer to), or — because
`sf.write` will happily write whatever `audio[0]` comes back as — succeeds
and produces a silent/degenerate output with no error message at all.

**Suggested fix direction:** give `ReferenceIssue` (or `validate_reference_sample`'s
return contract) a way to distinguish blocking failures from advisory
ones, and have `_add_sample` refuse to add the sample for the blocking
kind (file missing / unreadable / zero duration) while keeping the
existing "still added" behavior only for the range-advisory kind.

---

### P1-2: No way to cancel the on-demand install or a running generation short of killing the whole app

**File:** `app/widgets/voice_clone_tab.py:296-352` (`_generate`/`worker`);
contrast `app/app.py:2288-2320` (`_offer_optional_install`'s established
pattern) and `app/widgets/live_tab.py:148-151` (`live_stop_btn`).

`voice_clone_tab.py`'s own docstring says threading "follows the same
shape as the Live tab," but the Live tab ships a dedicated `Stop` button
(`app.live_stop_btn`) while the Clone-Your-Voice tab has no Stop/Cancel
control anywhere — only `Generate`, `Play result`, and `Save As...`. Worse,
the call into the on-demand installer drops the cancellation hook that
already exists for this exact purpose:

```python
ok = voice_clone.ensure_installed(log_cb=app.log_threadsafe)
```

`voice_clone.ensure_installed` (`core/voice_clone.py:87-99`) accepts a
`cancel_event` and forwards it straight to `optional_deps.install`, which
is explicitly designed around cooperative cancellation (`core/optional_deps.py:133-156,214-250`).
Every other on-demand install in this codebase wires this up with a
visible Cancel button — see `app/app.py:2286-2320`, which creates a
`threading.Event`, a "Cancel" button that sets it, a `WM_DELETE_WINDOW`
handler that also sets it, and passes it through to `optional_deps.install`.
The voice-clone tab does none of this.

**Concrete failure scenario:** first-time user clicks Generate. The ~2GB
package install starts (bounded internally at 1800s / 30 minutes with no
UI-visible way to cancel it), and even after that, OmniVoice's own
first-load weight download and the generation itself run under a combined
3600s (1 hour) ceiling. If the user's connection is slow, or they simply
change their mind, or the consent dialog scared them but they already
clicked through — their only recourse for the next up-to-90 minutes is to
force-close the entire application (losing the transcription queue, any
open Live session, etc.), not just this one tab's operation.

**Suggested fix direction:** add a Cancel/Stop button to the tab (mirroring
`live_stop_btn`), have it set a `cancel_event` threaded through to
`ensure_installed`, and have it call `app.vc_worker.stop()` to abort an
in-flight generation the same way app-exit already does.

---

### P1-3: The Portable ZIP build has no way to ever opt out — the "off by default" guarantee only exists for the installer

**File:** `core/hub.py:130-149` (`voice_clone_tab_enabled`, correct in
isolation); `installer_embed.iss:249-280` (the *only* place
`no_voice_clone.flag` is ever written); `docs/BUILD.md:26-28` (Portable
build recipe).

`voice_clone_tab_enabled()` is correctly implemented and well-tested
(`tests/core/test_hub.py:66-97` covers marker-present, marker-absent,
filesystem-error-defaults-safe, and independence from the tiling marker).
The gap isn't in this function or in how `app/app.py` consumes it
(`app/app.py:1611,1623-1634` — single source of truth, no divergent
second check, `gui.py` doesn't duplicate it either). The gap is that the
marker file this function looks for is *only ever created by the Inno
Setup installer's Pascal script* (`installer_embed.iss:277-280`):

```pascal
MarkerPath := ExpandConstant(NoVoiceCloneMarker);
if not WizardIsTaskSelected('voiceclone') then begin
    if not SaveStringToFile(MarkerPath, '', False) then
      Log('Could not create no_voice_clone.flag marker at ' + MarkerPath);
end else begin
    if FileExists(MarkerPath) then
      DeleteFile(MarkerPath);
end;
```

Per this repo's own `docs/BUILD.md:26-28,165,222`, the Portable ZIP is
built as `shutil.make_archive(..., 'zip', r'embed_build')` — a raw zip of
the embed tree, with no Inno Setup step and no other code path that ever
writes `no_voice_clone.flag` into it (confirmed: no such file exists
anywhere in the repo or any build script). The code comments for this
feature specifically call out "OFF by default (public-installer opt-in;
legal/ethical sensitivity...)" as the rationale — but every user who
downloads the Portable build (one of the two officially shipped
deliverables per this repo's `CLAUDE.md`) gets the tab enabled by default
with no supported way to turn it off.

**Suggested fix direction:** either bake a `no_voice_clone.flag` into the
Portable zip's `embed_build/` tree at build time (removed only if a future
"opt in" packaging step exists), or change the default posture so the
Portable channel is opt-in via a config value instead of an installer-only
marker file. This is inherited from the pre-existing Tiling-feature
mechanism (same gap applies there), but it matters more here given the
feature's own stated legal/ethical rationale for defaulting off.

---

## P2 findings

### P2-1: `_concat_references` leaks a temp WAV file on every multi-sample generation

**File:** `core/voice_clone.py:236-259`.

```python
fd, out_path = tempfile.mkstemp(suffix=".wav", prefix="voice_clone_ref_")
os.close(fd)
...
result = subprocess.run(cmd, **kwargs)
if result.returncode != 0 or not os.path.isfile(out_path):
    raise RuntimeError(f"Could not combine reference clips: {result.stderr}")
return out_path
```

`out_path` is created directly in the OS temp directory (not under this
app's own `user_cache_dir()`) and is never deleted by any caller —
`generate()` (line 210) uses it as `ref_path` and then simply drops the
reference on both the success and failure path; nothing ever calls
`os.remove` on it. Every "Generate" click with 2 or 3 reference samples
(the UI explicitly encourages more than one: "More than one clip
generally improves similarity") leaves one more orphaned WAV in `%TEMP%`
forever. Low per-file cost, but unbounded over repeated use, and it
lands in shared OS scratch space rather than the app's own cache.

**Suggested fix direction:** wrap the `model.generate(...)` call in a
`try`/`finally` that removes the concatenated temp file when
`len(reference_paths) > 1`.

### P2-2: `MODEL_READY_TIMEOUT_S` is dead code — the model-load phase has no timeout of its own

**File:** `app/services/voice_clone_service.py:25-28`; contrast
`app/services/live_service.py:35,105`.

```python
MODEL_READY_TIMEOUT_S = 900.0
...
GENERATE_TIMEOUT_S = 3600.0
```

`live_service.py` defines the identically-named `MODEL_READY_TIMEOUT_S`
and actually uses it (`def wait_ready(self, timeout: float =
MODEL_READY_TIMEOUT_S)`). The voice-clone service defines the same
constant, with a comment explaining exactly what it's for ("generous so a
slow machine's first load is never mistaken for a hang"), but nothing in
`VoiceCloneWorker.generate()` or anywhere else in the file ever reads it
— confirmed via a repo-wide grep, the only two hits are its own
definitions in `live_service.py` (used) and `voice_clone_service.py`
(unused). The model-load phase (which can include OmniVoice's own ~2GB
weight download, separate from the earlier pip install) shares the same
undifferentiated 3600s budget as the actual generation call. Not a hang
— the 1-hour ceiling still eventually fires — but a stalled model load is
indistinguishable from a stalled generation, and takes up to 4x longer
than apparently intended to time out.

**Suggested fix direction:** either wire a `wait_ready()`-style dedicated
wait keyed off the `model_loading`/`model_ready` events with this
timeout, mirroring `live_service.py`, or remove the unused constant if
the unified-timeout design is intentional now.

### P2-3: The two riskiest files in the feature have zero test coverage

**File:** `tests/core/test_voice_clone.py` (scope); confirmed via
repo-wide search that no other test file references `voice_clone` /
`VoiceClone` besides `tests/core/test_hub.py` (which only covers
`voice_clone_tab_enabled()`).

`tests/core/test_voice_clone.py` exercises `validate_reference_sample`,
`generate()`'s three input-validation `ValueError`s, `default_device`,
`is_available`/`ensure_installed` delegation, and `session_work_dir` —
all pure/cheap paths in `core/voice_clone.py`. There is no test file at
all for `app/services/voice_clone_service.py` (the subprocess
lifecycle/concurrency class — `start`/`stop`/`generate`/`_read_loop`/
`_handle`/`_fail_all_pending`) or `app/widgets/voice_clone_tab.py` (consent
gating, and the sample-admission logic where P1-1 lives). Nor is there
any test for `generate()`'s actual success path (mocking a fake model) or
for `_concat_references` — the exact function with the leak in P2-1.

**Suggested fix direction:** add a fake-subprocess-based test for
`VoiceCloneWorker` (send/receive JSON lines over real pipes to a stub
script) and widget-level tests for `_add_sample`/`_consent_accepted`
using a headless Tk root, matching how other tabs in this codebase are
tested.

### P2-4: Consent is enforced only in the UI layer, nowhere else

**File:** `core/voice_clone.py:177-233` (`generate`), `core/voice_clone_worker.py`
(whole file), `app/services/voice_clone_service.py:119-171`
(`VoiceCloneWorker.generate`) — none reference consent at all; the only
gate is `app/widgets/voice_clone_tab.py:264-279` (`_consent_accepted`),
called from `_generate` (line 293) before any thread is spawned.

The gate itself is correctly placed and race-free (it's a synchronous
check on the main thread, before the background worker thread or
subprocess ever starts, so there's no window where a click can slip
through before consent is recorded). But it is the *only* place consent
is checked. Nothing in the engine function, the worker's stdin/stdout
protocol, or the service class knows the concept exists. Any future
caller that talks to `core.voice_clone.generate()` or the worker protocol
directly — a script, a test, a CLI flag, a different tab — gets full
generation capability with zero consent enforcement.

**Suggested fix direction:** for defense in depth, thread a
`consent_accepted: bool` (or the config dict) into `core.voice_clone.generate()`
itself and raise if it's not set, so the engine doesn't rely solely on
its one current caller doing the right thing.

### P2-5: `VoiceCloneWorker._dead` is written but never read

**File:** `app/services/voice_clone_service.py:54,91,194`.

`self._dead = threading.Event()` is set in `.stop()` (line 91) and in
`_read_loop`'s `finally` (line 194), but no code anywhere in the class
ever calls `.is_set()` or `.wait()` on it. `is_running()` (lines 113-115)
relies solely on `proc.poll()`, which does correctly detect death, so this
is functionally harmless — but it's either leftover/incomplete code or a
signal that was meant to gate something (e.g., `generate()` short-circuiting
immediately instead of attempting a write that will fail) and never got
wired in.

**Suggested fix direction:** either use `self._dead` as an early-exit
check at the top of `generate()`, or remove it if `proc.poll()` is judged
sufficient.

### P2-6: The recording countdown's `after()` chain isn't cancelled on app close

**File:** `app/widgets/voice_clone_tab.py:218-224` (`_tick_recording`) vs.
`416-433` (`stop_voice_clone_worker`).

`_tick_recording` reschedules itself every second via `app.after(1000,
lambda: _tick_recording(app, seconds_left - 1))` for the duration of a
6-second sample recording. `stop_voice_clone_worker`, called from
`app.py`'s exit handler, stops the `Recorder` object itself but never
cancels this pending `after()` chain. If the user closes the app in the
middle of recording a sample, a previously-scheduled tick can still fire
after `self.destroy()` has run, touching `app.vc_status_var` on a
destroyed Tk interpreter. Tkinter's default callback-exception handling
means this would surface as, at worst, a stray traceback logged at
shutdown rather than a hang or a visible crash — low severity, but a
real, reachable gap.

**Suggested fix direction:** capture the `after()` id and cancel it (or
check a `self._closing`-style flag) in `stop_voice_clone_worker`, the same
way `_drain_main_calls` already guards its own rescheduling elsewhere in
`app.py`.

### P2-7: Worker shutdown blocks the Tk main thread for up to ~7 seconds if a generation is in flight

**File:** `app/services/voice_clone_service.py:86-111` (`stop`).

`on_exit()` in `app/app.py` calls `stop_voice_clone_worker` synchronously
on the main thread. If a generation is currently running in the
subprocess (no cooperative cancel exists, by design — see the
`voice_clone_worker.py` module docstring), `.stop()` writes a shutdown
command the worker won't read until its current blocking call returns,
waits up to 5s, then falls through to `kill_process_tree` (which can
itself take a few seconds via `taskkill /T` and its graceful→forced
escalation), then waits up to another 2s. All of this runs on the GUI
thread, so the whole application appears frozen for up to ~7+ seconds
when closing mid-generation. This mirrors the pre-existing Live-tab
shutdown shape (not a new pattern introduced here), so it's low priority,
but it is a real, reproducible UI freeze specific to whenever this
feature is mid-run at exit time.

**Suggested fix direction:** if this is ever revisited, move the
kill-tree wait off the main thread (e.g., a short-lived non-daemon
cleanup thread joined with a hard cap) so window close feels instant even
mid-generation — same opportunity exists for the Live tab.

### P2-8: No protection against an orphaned worker on an abrupt parent crash/kill

**File:** `core/_proc.py` (whole file — confirmed no Job-Object or
equivalent parent-death-linked kill mechanism anywhere in the codebase via
repo-wide search); `app/services/voice_clone_service.py:86-111`.

All of this feature's subprocess cleanup (`kill_process_tree`,
graceful-then-forced escalation) runs from the normal `on_exit()` path.
If the main GUI process is killed abnormally (Task Manager "End Task,"
a hard crash in unrelated native code, power loss), none of that cleanup
code runs, and the voice-clone worker — potentially holding a ~2GB loaded
model and mid an up-to-one-hour CPU-pegged generation — is left running
as a true orphan with no parent to report results to. This is a
pre-existing, shared characteristic of every subprocess this app spawns
(yt-dlp, ffmpeg, the transcription worker, the Live worker) — not a new
defect introduced by this feature — but voice-clone's combination of a
large resident model and long runtime makes it the most expensive
instance of this gap to actually hit.

**Suggested fix direction:** out of scope for a targeted fix to this
feature alone; if ever addressed, a Windows Job Object with
`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` assigned to each spawned subprocess
would give real parent-death semantics across the whole app, not just
this feature.

---

## Overall assessment

The feature is defensively written where it counts most: every subprocess
boundary (install, spawn, write, read, generate) is wrapped in a broad
exception handler that correctly routes failures back to the user through
`_generate_failed`/`show_error`, the Generate button cannot get stuck
disabled in any traced scenario, the consent gate is race-free at the one
point it's checked, the opt-in/opt-out marker logic in `core.hub` is
correct and independently well-tested, and there is no shell-injection or
unsafe-deserialization surface anywhere in the worker protocol. The real
issues are less dramatic than a crash: a validation function whose
answers get ignored for the cases that matter most (P1-1), a long-running
operation with no way to back out of short of killing the whole app
(P1-2) despite the codebase having a mature, reusable pattern for exactly
this that simply wasn't applied here, and a distribution-channel gap that
quietly defeats the feature's own stated legal/ethical rationale for
defaulting off (P1-3). The P2 list is mostly small leaks, dead code, and
minor shutdown-timing rough edges that are worth cleaning up but pose no
real risk to data or stability. None of the eight specific hunt areas in
the review brief turned up a crash or a security hole; the P1s are where
real user-facing pain would actually show up.
