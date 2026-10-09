# Architecture Decision Records

Short notes on the load-bearing choices in this codebase. Each entry follows the template:

```
## NNNN-title
Status:   [Accepted | Superseded by NNNN | Deprecated]
Date:     YYYY-MM-DD
Context:  the problem
Decision: what we chose
Consequences: what this commits us to
```

Write a new ADR every time a choice has a non-obvious justification that future-you will want to know. They are append-only — when a decision changes, write a new ADR superseding the old one rather than editing history.

---

## 0001 — Subprocess workers, not threads, for transcription

**Status:** Accepted
**Date:** 2026-05-10

**Context:** Transcription work is CPU-bound (or GPU-bound, but with Python GIL contention on the host side). `faster-whisper` / CTranslate2 / torch are not free-threaded. Running multiple transcriptions in threads inside the GUI process means:

- Python GIL serializes the calls anyway
- A crash inside the model (segfault from a corrupted input, OOM) takes the whole UI with it
- The first model load is expensive (5-15 seconds), so we want it amortized across jobs

**Decision:** Each transcription runs in a long-lived subprocess (`python -u -m core.worker`). The parent talks to it over stdin/stdout with newline-delimited JSON. Workers are spawned up to `parallel_workers` concurrent.

**Consequences:**
- We pay startup time (one model load) per worker, not per job
- A worker crash is isolated — `worker_exit` event fires, UI continues
- The IPC layer is observable (JSON event log is the diagnostic trail)
- We can't share Python objects between worker and UI; everything is serializable JSON
- Cancel is `terminate()` on the subprocess, simple and robust

**Alternatives considered:**
- Threads — rejected because of crash isolation and GIL
- `multiprocessing.Pool` — rejected because it doesn't fit the long-lived-worker model and adds pickling-of-large-objects friction
- ProcessPoolExecutor with `loky` — same issues as multiprocessing

---

## 0002 — Ship yt-dlp as a vendored binary, not a Python library import

**Status:** Accepted
**Date:** 2026-05-08

**Context:** yt-dlp is available as a pip package (`pip install yt-dlp`) and as a standalone executable. The project needs to:

- Run on machines without a yt-dlp pip install
- Update yt-dlp independently of the rest of the app
- Survive yt-dlp API changes between releases without breaking the GUI

**Decision:** Ship `yt-dlp.exe` in `bin/`. Drive it via `subprocess.Popen` with structured flags and parse stdout.

**Consequences:**
- The user / packager doesn't need a Python yt-dlp install
- Updates are a single binary replacement (`yt-dlp --update`, or the planned auto-update in ROADMAP 3.2)
- We parse stdout (`[download] N%`, `Writing video subtitles to:`) rather than subscribing to a progress callback. Phase 3.1 replaces regex with `--progress-template "%(progress)j"` which gives us JSON progress events
- Cancellation is `terminate()`, which is always correct (no in-process state to clean up)
- The cost: we cannot directly inspect `info_dict` without a separate `--dump-single-json` invocation (we accept this — it's how `lookup_formats` works today)
- For users who want bleeding-edge yt-dlp features, an `extra_ytdlp_args` setting (ROADMAP 3.4) gives them an escape hatch without us needing UI for every flag

**Alternatives considered:**
- `import yt_dlp` library — rejected because of the dependency-on-pip-install problem and the inability to ship a self-contained binary
- Both library and binary — rejected as needless complexity for one-developer scope

---

## 0003 — Resumable MD5-verified ZIP for model distribution, not Hugging Face Hub

**Status:** Superseded by 0010
**Date:** 2026-05-06

**Context:** The model is ~3 GB. Users in Iran (the developer's geography) have unreliable, throttled, sometimes-blocked access to huggingface.co. `huggingface_hub.snapshot_download` requires reaching HF and authenticating gracefully with their CDN; in practice this fails for many users.

**Decision:** The model lives as a single ZIP on a CDN mirror (`smch.ir`), accompanied by an `.md5` manifest listing the MD5 of every file inside the archive. The app downloads the ZIP with HTTP `Range` resume support, extracts it, then verifies every file against the manifest. Mismatches trigger a full redownload.

**Consequences:**
- Robust against partial downloads (resume via `Range: bytes=N-`)
- Robust against corrupted extracts (file-by-file MD5 check)
- We pay the cost of hosting and updating the mirror when the model changes
- Users without smch.ir access can still hand-place the model at `config.model_path` and skip the download dialog
- One model URL per `config.json`. Multi-model support (ROADMAP 2.7) will keep the same shape, just a list of these objects.

**Alternatives considered:**
- HuggingFace Hub — rejected for the access reason
- BitTorrent / IPFS — overkill for the scale; no real reliability gain over a CDN + integrity check
- No verification — rejected because corrupt model files give silently-bad transcriptions

---

## 0004 — Single mutable `download_current` global, no lock

**Status:** Accepted (but flagged in AUDIT B3)
**Date:** 2026-05-09

**Context:** Only one download can be active at a time today. We need to remember which task is "the current one" so the worker thread can notify completion and the next task can pick up.

**Decision:** Use a module-global `download_current` variable. The convention is that all reads and writes of it happen on the Tk main thread (either directly, or via `download_events` queue events that the main thread drains).

**Consequences:**
- No locking complexity
- Works as long as the convention holds — and today it does
- Future parallel-downloads support (ROADMAP 3.7) requires replacing this with a list and using a `Semaphore` or similar
- The global is a smell that the AUDIT calls out; it should become `self.download_current` on the App when we refactor `gui.py` (ROADMAP 1.4)

**Alternatives considered:**
- `threading.Lock` — unnecessary given the single-thread-write convention
- Make it a method on a `DownloadService` class — what the refactor will do

---

## 0005 — `tkinter` over PyQt / web frameworks

**Status:** Accepted
**Date:** 2026-05-04

**Context:** Need a desktop GUI on Windows that ships easily, looks acceptable, doesn't bloat the install, and a solo developer can maintain.

**Decision:** Tkinter as the toolkit, with the planned upgrade to `sv-ttk` (ROADMAP 1.1) for modern Windows 11 styling.

**Consequences:**
- Zero install dependency on Windows (`tkinter` is in the stdlib's Python distribution)
- PyInstaller bundle stays small (~50-80 MB without the model)
- We're locked into the Tk widget model. Custom widgets need to be drawn on a Canvas or imported via niche libraries (`ttkwidgets`, `tkinterdnd2`)
- The default look is mediocre; mitigated by `sv-ttk`
- Switch cost to PyQt6 / Flet / NiceGUI is L (~1 week per ROADMAP estimate), so this is reversible if we ever need richer widgets

**Alternatives considered:**
- PyQt6 / PySide6 — better widget library and tooling, but adds 40-80 MB to the bundle and a steeper learning curve
- Flet / NiceGUI — fast iteration, but they're web-based under the hood and don't fit the "drives subprocesses on the user's filesystem" model as cleanly
- Electron — rejected, ~100 MB minimum bundle plus runtime, single-developer maintenance cost

---

## 0006 — Each transcription writes SRT + JSON next to the input file

**Status:** Accepted (under review for ROADMAP 2.4 multi-format output)
**Date:** 2026-05-05

**Context:** Where should output files go? Same folder as input? A configured output folder? A user prompt per file?

**Decision:** Same folder as input, same base name, `.srt` and `.json` extensions.

**Consequences:**
- Predictable for the user — output is right next to input
- Plays well with batch workflows where the user already has folders organized by topic
- Existing files of the same name are silently overwritten — documented but not yet a "confirm overwrite" prompt
- ROADMAP 2.4 adds VTT/TSV/TXT/LRC; this decision applies to all of them. The output formats are user-selectable, not auto-generated all-at-once.

**Alternatives considered:**
- Configured output folder — rejected as it forces the user to flatten their organization into one bucket
- Subfolder `<input>_transcripts/` — minor friction for the common case; possible future setting
- User prompt per file — overkill for a batch workflow

---

## 0007 — Reject `.eaf` DOCTYPE by substring check, not `defusedxml` or an expat handler

**Status:** Accepted
**Date:** 2026-08-15

**Context:** `core.convert._parse_eaf` (the "Convert transcript" ELAN
import) parsed untrusted `.eaf` files with plain
`xml.etree.ElementTree.fromstring`. Stdlib `ElementTree`/expat has no
built-in limit on entity expansion, so a crafted `.eaf` with a `DOCTYPE`
entity block can hang the app or exhaust memory ("billion laughs"); the
same `DOCTYPE` opening is also the XXE (external-entity) vector. Found
during an attacker's-eye pass over the whole codebase — every other
input-parsing path checked in that pass was already hardened, this one
was not.

**Decision:** Reject any input containing the literal `<!DOCTYPE`
substring before parsing, instead of installing `defusedxml` or reaching
into `ET.XMLParser`'s underlying expat parser to set
`StartDoctypeDeclHandler`. The XML grammar's `doctypedecl` production
requires that exact, case-sensitive token, so the check is complete, not
a heuristic.

**Consequences:**
- No new dependency, no change to `requirements.txt` or either
  PyInstaller `.spec`'s hidden-import list.
- Survives Python-version churn: while implementing this, `ET.XMLParser()`
  on this machine's Python 3.14 exposed no `.parser`/`._parser` attribute
  at all (only `_parse_whole`/`_setevents`/`close`/`entity`/`feed`/`flush`/
  `target`/`version`), so the commonly-cited `parser.parser.StartDoctypeDeclHandler
  = ...` recipe (which assumes the pure-Python fallback implementation)
  raised `AttributeError` against the C-accelerated implementation. A
  plain string check has no such dependency on ElementTree's internals.
- Any legitimate `.eaf` producer that ever needs a DOCTYPE (none of this
  app's own writers do) would be rejected too — acceptable, since ELAN's
  own format does not require one.

**Alternatives considered:**
- `defusedxml.ElementTree.fromstring` — the standard fix, but adds a
  dependency for one call site; also project convention favors a small
  stdlib-only fix when one is straightforward (see `core/server/jobs.py`'s
  hand-rolled `_safe_filename`/`is_safe_url` instead of a library).
- `parser.parser.StartDoctypeDeclHandler = ...` on `ET.XMLParser` — tried
  first; abandoned because the attribute does not exist on this Python's
  C-accelerated `XMLParser` (see Consequences above).

---

## 0008 — Disable GC around whole heavy-import/allocation-heavy background operations

**Status:** Accepted as defense-in-depth — NOT a proven-complete fix on its
own; see the round 4 update below and ADR 0009 for what actually resolved
the full-suite crash.
**Date:** 2026-08-15

**Context:** Several backends and probes report readiness via an
`is_available()`/`runtime_available()`-style function that lazily imports
a heavy optional C-extension package the first time it's called:
`google_cloud_stt` (`google.cloud.speech_v2`), `whisper_cpp`
(`pywhispercpp`), `nvidia_asr` (`transformers`/`torch`, via
`availability._import_transformers`), `separator` (`demucs`),
`voiceprint` (`pyannote.audio`), `llm` (`llama_cpp`), `diarization`
(`sherpa_onnx`), `alignment` (`stable_whisper`), and `search`
(`sentence_transformers`, both the availability check and the actual
model load in `Embedder._load`). `core.hardware.probe_tiers()` does the
same for `ctranslate2`/`onnxruntime`/`openvino`/`torch` hardware-tier
probing. `app.app._refresh_engine_status()` fires an engine-status probe
on a fresh daemon thread every time the user changes the engine
selection, and `app.widgets.hardware_wizard` does the same for a
hardware re-probe — so a real app session can easily end up with more
than one such probe thread alive at once.

A real crash was root-caused this session through THREE separate rounds
of instrumented full-test-suite reproduction, each disproving the
previous theory before the real fix held:

1. **Lock-only.** First observed: `Windows fatal exception: code
   0x80000003` (STATUS_BREAKPOINT) inside proto-plus's message-class
   creation (`proto/message.py` `__new__` -> `_file_info.py` `ready()`),
   while `google.cloud.speech_v2`'s module-level class registration ran
   on a probe thread AND a GC pass fired concurrently. Theory: two probe
   threads racing the same first import. Added a `threading.Lock()`
   around `runtime_available()`'s import. **Disproved**: a full-suite
   rerun crashed in the exact same place — the crash dump showed the
   lock correctly serializing the threads, and a SINGLE thread alone
   inside the import still faulted when GC fired.
2. **Import-scoped `gc.disable()`.** Wrapped the import itself (not the
   whole function) in `gc.disable()`/`gc.enable()`. A full-suite rerun
   then completed clean — looked fixed. Same two-part pattern (lock +
   import-scoped `gc.disable()`) was applied pre-emptively to the other
   8 modules above, since none of them had been observed to crash yet
   but all do the identical lazy-heavy-import-from-a-probe-thread
   pattern.
3. **Still incomplete — the crash recurred** on a LATER full-suite rerun
   (verifying the batch of 8 pre-emptive fixes), in the same
   `app.app._probe` thread, but this time NOT inside the import: the
   fault landed in `<string> line 2 in __init__` (a `@dataclass`'s
   auto-generated constructor) at `availability.py`'s
   `EngineStatus(...)` construction — one line AFTER
   `runtime_available()` had already returned successfully, GC
   correctly re-enabled by its own guard. So the real failure mode is
   broader than "GC firing mid-import": it is "GC firing ANYWHERE in
   this thread while the process is under this kind of allocation
   pressure" (in the observed case, a concurrent real faster-whisper
   transcription — `encode()`/`detect_language()` — running on another
   thread at the same moment, plus several other live background
   threads: worker heartbeats, tqdm monitors).

**Decision:** Disable GC for the ENTIRE risky operation, not just the
import statement inside it — `app.app._refresh_engine_status`'s
`_probe()` inner function now wraps its whole body (the
`engine_status(...)` call and the `EngineStatus(...)` fallback
construction) in `gc.disable()`/`gc.enable()`, and
`core.hardware.probe_tiers()` wraps its whole body (all five tier
sub-probes) the same way. The per-module `is_available()`/
`runtime_available()` functions keep their narrower import-scoped guard
(cheap, still correct, and covers direct callers that bypass the
thread-level wrapper, e.g. `app/dialogs/advanced.py` calling
`_llm.runtime_available()`/`_g.runtime_available()` directly) — belt AND
suspenders, not either/or. Every `gc.disable()` site restores the
caller's PRIOR GC state via `try/finally` (`if was_enabled: gc.enable()`),
not an unconditional re-enable, so a caller that had already disabled GC
for its own reason is not silently overridden. Keep the
`threading.Lock()` at each site too — it does not fix the crash by
itself (round 1 proved that) but still avoids redundant concurrent
imports.

**Consequences:**
- A GC-disabled window per background probe/hardware-reprobe — normally
  well under a second (an import), occasionally the length of a
  benchmark-free tier probe. Negligible: these are user-driven (engine
  selection, Advanced dialog open, Hardware Wizard re-probe), not a hot
  loop, and each site restores GC afterward regardless of outcome.
- Any FUTURE probe/status-check function that does a lazy heavy import
  or heavy allocation from a background thread must wrap its own body
  (not just an inner import line) in this same lock +
  `gc.disable()`/`gc.enable()` pattern — see
  `core/backends/google_cloud_stt.py`'s `runtime_available()` for the
  per-function reference, and `app.app._refresh_engine_status`'s
  `_probe()` / `core.hardware.probe_tiers()` for the whole-thread-body
  reference. Import-only scoping is NOT sufficient by itself (round 2
  above) — wrap the whole background operation when one exists.
- Does not cache any availability result — an on-demand
  `core.optional_deps` install mid-session must still be picked up by
  the next probe call.
- Proven with instrumented full-suite reruns at every step, not
  asserted — including catching round 2's own incompleteness. Regression
  tests across `tests/core/test_google_cloud_stt.py`,
  `tests/core/test_backends.py`, `tests/core/test_separator.py`,
  `tests/core/test_llm.py`, `tests/core/test_diarization.py`,
  `tests/core/test_voiceprint.py`, `tests/core/test_alignment.py`,
  `tests/core/test_search.py`, and `tests/core/test_hardware_cuda_gate.py`
  cover the mechanism (GC state always restored, concurrent callers
  serialize) at every hardened site, since the native fault itself is
  inherently timing-dependent and not something a unit test can pin
  down directly.

**Alternatives considered:**
- Lock only (no `gc.disable()` at all) — round 1; disproved by a
  full-suite rerun crashing in the same place.
- `gc.disable()` scoped to just the import statement — round 2; looked
  sufficient after one clean full-suite run, but a LATER run proved it
  incomplete (the fault can land just outside that narrow window too).
  Kept anyway at the per-function level as a cheap first layer, but no
  longer trusted alone.
- Eagerly import all optional heavy backends at app startup on the main
  thread (before any other thread exists) — would sidestep the
  concurrency angle, but not the "GC fires during unrelated concurrent
  allocation pressure" angle (round 3 showed the fault isn't tied to
  import timing at all), and contradicts this module's own stated design
  goal (`core/backends/availability.py`'s docstring: "GUI callers should
  compute cloud-engine statuses lazily... rather than eagerly at every
  startup") — startup cost for a feature most users never touch is
  exactly what the lazy design avoids.
- Report the crash upstream (protobuf/proto-plus, or CPython 3.14's GC)
  and wait for a fix — worth doing separately (round 3's evidence, a
  plain dataclass constructor faulting under GC, points more at a
  CPython/GC-and-threading interaction than at protobuf specifically),
  but doesn't help users on the currently-shipped dependency/interpreter
  versions in the meantime.

**Round 4 — the whole-function guard STILL wasn't enough; this is the
update that keeps this ADR honest.** After widening `_probe()`'s
`gc.disable()` to cover its entire body (including the `post_to_main()`
call, since round 3's fault landed one line after the first `gc.enable()`
returned — see the code comment in `app/app.py`), TWO more full-suite
reruns were run to confirm. The first was clean. The second crashed
again, same `Thread-59 (_probe)`, but this time the fault frame was
`_weakrefset.py` line 15 — a **CPython-internal weakref cleanup
callback**, with NO `app.py` frame above it in the visible stack. The
concurrently-running thread at that exact moment was loading the REAL
faster-whisper model (`WhisperModel.__init__`) for
`test_v08_real_file_e2e.py` — a thread this ADR's fix never touched.

This is the evidence that finally settled it: `gc.disable()`/
`gc.enable()` are **process-global, not thread-local**. Whichever thread
happens to cross GC's generation-0 allocation threshold triggers a
collection that walks objects across the WHOLE process — so a thread this
ADR never touched (the real model load) can trigger the exact same class
of fault on its own, with `_probe()`'s own guard doing nothing to prevent
it. Continuing to widen `_probe()`'s guard, or adding guards to more and
more individual functions, cannot converge on a complete fix by this
approach — the trigger is not really "which function is running," it is
"is ANY thread anywhere in the process crossing the GC threshold while
conditions are fragile." The GC-disable hardening in this ADR is kept
(it is real, cheap, evidence-based risk reduction for the specific
probe/import call sites it covers, in ordinary single-transcription
usage) but is explicitly NOT claimed to make the pytest full-suite
scenario crash-proof. See ADR 0009 for what actually resolved the
full-suite crash: removing the trigger condition (a real model load
running concurrently with ~700 other tests' leftover threads) rather
than continuing to chase where, process-wide, GC might fire next.

---

## 0009 — Move the one real-model test out of the hermetic full-suite run

**Status:** Accepted
**Date:** 2026-08-15

**Context:** ADR 0008 root-caused (over 4 rounds of instrumented
full-suite reproduction) a real native crash to Python's garbage
collector firing, process-wide, while SOME thread in the process was
under heavy allocation pressure — and proved that no amount of
per-function `gc.disable()` hardening can guarantee this can't happen,
because `gc.disable()` is process-global and cannot protect the process
from a thread it was never applied to. `tests/core/test_v08_real_file_e2e.py`
self-gates on the real SMTV clip fixture + the real ~3 GB Whisper model
both being present (`pytest.mark.skipif(not SMTV_CLIP.exists(), ...)`) —
on THIS dev machine both are present, so it always ran for real as part
of `run_tests.bat`'s ~700-test "hermetic" suite
(`pytest tests/ --ignore=tests/smoke`), loading and transcribing with the
real model concurrently with whatever threads ~700 other tests had left
running. The file's own docstring already said it conceptually belonged
with the smoke tests ("they live alongside the existing smoke tests
because they share the same model-load cost and the same gating
pattern") — it just physically lived in `tests/core/` for a shared-fixture
reason (see Alternatives).

Owner was asked directly (given how much of this session's budget the
GC-crash chase had already consumed) whether to keep patching narrower
GC windows, accept the residual risk and move on, or isolate the
real-model test — and chose isolation.

**Decision:** `git mv tests/core/test_v08_real_file_e2e.py
tests/smoke/test_v08_real_file_e2e.py`. This test now only ever runs via
the separate smoke-test path (`pytest tests/smoke/...`), never mixed into
the hermetic gate `run_tests.bat` runs before every commit — removing the
"real model load running concurrently with ~700 other tests' leftover
threads" trigger condition entirely, regardless of whether the underlying
GC/threading interaction is ever fully understood or fixed upstream.

The move broke one dependency: `tests/core/conftest.py`'s
`_isolate_transcriber_globals` autouse fixture existed specifically to
let this file's module-scoped `transcribed_clip` fixture (which mutates
`core.transcriber` module globals via `load_existing_model()`) coexist
with the rest of `tests/core/` without leaking state into later test
files. Moved that one fixture up to a new `tests/conftest.py` (the shared
root, applying to every subdirectory including `tests/smoke/`) so the
moved test keeps the exact protection it relied on. Left
`_default_offline_backend` (the other autouse fixture in
`tests/core/conftest.py`) where it was — it forces the offline backend
for hermetic-suite determinism, which is specifically NOT what a
real-model smoke test should have forced on it, and this test's own
fixture already forces a fresh real load regardless
(`t.MODEL = None; t.load_existing_model()`), so it never depended on that
fixture in the first place.

**Consequences:**
- `run_tests.bat` / `pytest tests/ --ignore=tests/smoke -q` is now
  provably not exposed to this specific crash trigger — two full-suite
  reruns after the move were clean; this is the actual resolution,
  not another "looks fixed" claim (see ADR 0008's own history of those).
- The real-model coverage this test provides is unchanged — it still
  runs, just only via the smoke-test path
  (`python -m pytest tests/smoke/test_v08_real_file_e2e.py`), same as
  every other resource-heavy test in that directory.
- `tests/conftest.py` is now the place any FUTURE cross-cutting
  isolation fixture that needs to apply to both `tests/core/` and
  `tests/smoke/` (or any new test subdirectory) belongs — not
  `tests/core/conftest.py`, which is core-suite-specific now.
- `PROJECT_INDEX.md`'s Gotchas entry describing this as a
  "test-order-dependent flake... needs a real hot worker+model" is
  updated; it is no longer order-dependent because it no longer shares
  a process with the tests whose order it depended on.

**Alternatives considered:**
- Keep chasing narrower `gc.disable()` windows — rejected; ADR 0008
  round 4 proved this specific approach cannot converge (the trigger is
  process-wide GC behavior, not any one function's code).
- Accept the residual crash risk in the hermetic suite and move on
  without isolating the test — rejected by the owner when asked; a
  full-suite run that can spuriously crash 1-in-N times undermines
  trusting a clean `run_tests.bat` result before every commit.
- Skip/delete the real-model test entirely — rejected; it is real,
  valuable end-to-end coverage (hallucination + auto-chapters + the full
  transcribe pipeline against real audio), not a test worth losing. It
  only needed a different execution context, not removal.

---

## 0010 — Models download only from the Hugging Face Hub

**Status:** Accepted

**Date:** 2026-10-08

**Context:** ADR 0003 put four models on a zip mirror with an `.md5` manifest; every other
model already came from the Hugging Face Hub, which also served as the mirror's fallback. The
mirror path had its own failure modes: an entry with a `url` but no `md5` wiped a freshly
unpacked model, and an MD5 mismatch deleted a working model before its replacement existed. A
non-official server is also one more thing a user has to trust.

**Decision:** Every model downloads from its `hf_repo` through `faster_whisper.download_model`
(huggingface_hub). The `url`/`md5` keys are removed from the built-in catalog and the default
config, and dropped from any catalog entry or old `config.json` that still holds them, so no
source but the Hub is ever contacted. A model counts as installed when it has a non-empty
`model.bin` and no unfinished `.incomplete` blob; an installed model is never deleted by
`ensure_model`.

**Consequences:**
- One download path: resumable (huggingface_hub keeps `.incomplete` blobs) and checked file by
  file against the Hub.
- Networks that block huggingface.co cannot download a model from the app; a model can still be
  placed by hand in the model folder.
- Older app versions keep using the mirror files, so those files stay where they are.

## 0011 — Windows frame theming through ctypes DWM calls; "System" theme by a slow registry check

**Status:** Accepted

**Date:** 2026-10-09

**Context:** The Light/Dark theme restyled the Tk widgets, but the title bar and border are drawn
by Windows and stayed light. "System" asked the optional `darkdetect` package, which no Windows
bundle contains, so it always meant Dark there. Prior art read first: pywinstyles (DWM attribute
numbers and colour order; no Windows build checks) and darkdetect (the `AppsUseLightTheme`
registry value; its change listener blocks a thread in `RegNotifyChangeKeyValue`).

**Options considered (live "System" follow):**
1. Check the registry value every 2 s on the Tk thread (`root.after`). Chosen: no thread, no
   hook, one cheap read, only while the mode is "System".
2. Hook `WM_SETTINGCHANGE` ("ImmersiveColorSet"). Instant, but it means replacing Tk's window
   procedure, which Tk and tkdnd already own.
3. A listener thread blocked in `RegNotifyChangeKeyValue` (darkdetect's way). Instant, but Tk is
   not safe to touch from another thread, so it needs a hand-off queue and a stop event.

**Decision:** `app/theme/win_chrome.py` calls `DwmSetWindowAttribute` through `ctypes` (no new
dependency, no COM): the dark flag (20, then 19 if refused) on every window, the caption, border
and text colours on Windows 11 (build 22000+, read from `RtlGetVersion`, not the exe manifest)
only, a frame redraw on Windows 10. Every call is wrapped; `native_window_theme` /
`WTS_NO_NATIVE_CHROME` switch it all off. `app/theme/system_appearance.py` holds one back-end per
OS behind `is_dark()` / `subscribe()`; the Windows back-end is option 1.

**Consequences:**
- A theme flip in Windows Settings reaches the app within 2 s.
- A dialog shown for the first time may paint its title bar light for one frame before the
  `<Map>` handler runs.
- Windows' own message boxes and file dialogs keep the system title bar.
- Known cosmetic gap: plain `tk.Text` / `tk.Listbox` widgets with colours of their own inside a
  dialog that is open during a flip keep their old colours until the dialog is reopened; ttk
  widgets and the colour tokens follow at once.
- macOS and Linux behave as before (`darkdetect` once, no watching; no answer counts as light, a
  missing package as dark, now logged); the macOS back-end plugs into `get_backend`.

## 0012 — Taskbar progress, badge and flash through ctypes ITaskbarList3; guarded set-up

**Status:** Accepted

**Date:** 2026-10-09

**Context:** A long transcription gave no sign on the Windows taskbar: no progress, no count of
queued jobs, nothing when a job finished behind another window. The Windows way is
`ITaskbarList3` (progress state and value, overlay icon) plus `FlashWindowEx`. It is a COM
interface called through a vtable, so one wrong slot number or argument type is an access
violation that no `try` can catch. Prior art read first: Microsoft's `ITaskbarList3` and "Taskbar
Extensions" documentation and the SDK header `ShObjIdl_core.h`; the `TaskbarButtonCreated`
message is how a program learns that the button exists again after Explorer restarts. The app
already uses `ctypes` for DWM (ADR 0011) and has no `comtypes` or `pywin32` dependency.

**Options considered:**
1. `comtypes` or `pywin32`. Typed wrappers, but a new dependency in every bundle for three calls.
2. `ctypes` with a hand-written vtable. Chosen: no dependency; the slot numbers are written once,
   checked against the SDK header (a test re-derives them from the header when the SDK is
   installed) and pinned, and a test calls a fake COM object built from ctypes callbacks so each
   wrapper method is shown to land on its slot with 64-bit arguments.
3. Progress through the window title only (already done). Nothing on the button itself.

**Decision:** `app/theme/win_taskbar.py`. `App.refresh` (every 500 ms) calls `sync`, which turns
both queues into one snapshot (state, percent, badge count) and sends only what changed, at most
one round per 500 ms, on the main thread only. The flash is decided from the same snapshots (a job
going from queued/running to finished while the window is not the foreground window) and is tied
to the existing "Chime on completion" setting; no second option. A download row that the auto-transcribe
hand-off sets to "finished" is not a finish by itself (the hand-off does that for a failed or cancelled
transcription too); the linked transcription task reports a success on its own. Guards:
- Kill switch: `native_taskbar` (config) and `WTS_NO_TASKBAR` (environment).
- Start marker `taskbar_integration.marker` in the app data folder, written before the first COM
  call and removed after the first real update (state, value and the badge icon) went through. A
  crash in between leaves it; the next start of the same app version logs a warning and keeps the
  integration off. Another version ignores it. It does not repair itself: delete the file or update.
- No COM until a job exists, and not for a withdrawn window; `CoInitializeEx` in a single-threaded
  apartment on the Tk thread (a thread already in a multi-threaded apartment is refused);
  `HrInit` is called; everything is released (`Release`, `CoUninitialize` if this code initialised,
  icons destroyed) in `App.destroy` before the window goes.
- `TaskbarButtonCreated`: `SetWindowSubclass` (chains to the existing procedure; Tk's own is not
  replaced, unlike the option rejected in ADR 0011) only sets a flag; the next round creates a new
  COM object and re-applies the state. If the hook cannot be installed only this recovery is lost.
- Five rounds in a row of refused calls switch the integration off for the session; every failure
  is logged once and never reaches the user.

**Consequences:**
- Windows 7 and later get the taskbar features; macOS and Linux import the module and do nothing.
- A failed job turns the bar red for at least 5 seconds, and then until the window is in front.
- A user job flashes the button (three blinks) once, when its last stage ended well: not for a failed
  or cancelled job, and not for the transcription step of a subtitled-video row (its burn is last).
- A user whose start crashed in the set-up sees no taskbar features until the next app version.
- Another instance that starts at the very moment the first one holds the marker also stays off.
- The AppUserModelID is unchanged (a pinned or grouped taskbar button is not touched).
