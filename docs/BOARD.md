# Work board and RESUME

Updated: 2026-11-11. Release target: 2.4.0. This development snapshot includes
post-candidate reliability fixes; release validation remains separate.

## Owner questions / release boundary

- Keep this preparation local; branch publication has not been performed.
- Required research and translation signoff remain pending. Operational access
  details are in the ignored release record.
- No decision is needed for the selected implementation scope.
- Tagging, publication and release pushes wait for the owner's explicit approval.
- macOS verification is pending; access and resource blockers are recorded in
  ignored local release notes.
- Microphone hardware validation remains pending.

## RESUME

Read the [reliability step log](RELIABILITY_STATUS_2026-11-11.md);
its proposals and synthetic reproductions are not completed fixes.

The [worker-exit recovery record](FIX_WORKER_EXIT_OUTPUT_RECOVERY.md)
describes the recovery rules, limitations and regression commands.
New investigations must record their own baseline and verification.

Read [the dated scope proposal](RELEASE_2.4.0_PLAN.md), then this board.
Start by checking git status and live lane progress; preserve unrelated untracked
files. Mainline base was `c87fc7e8`; all existing Unreleased fixes are included.
No tag or public release has been created.

| Card | Status | Next action / acceptance |
|---|---|---|
| 240-01 Named presets | Integrated, reviewed twice | Real GUI, persistence and combined gate passed |
| 240-02 Editor subtitle quality | Integrated, reviewed twice | Real GUI, 91 focused tests and combined gate passed |
| 240-03 Download speed limit | Integrated, reviewed twice | Real download, 104 focused, 36 regression and combined gate passed |
| 240-04 Integration | Passed | Type gate 0/0/0; full desktop suite 13,914 passed, 75 skipped |
| 240-05 Release preparation | Installer built; Portable verified | Final installer and Portable ZIP ready locally; matching FFmpeg source retained |
| 240-07 Localization | Pending | Translate new labels and obtain independent language review |
| 240-08 Service compatibility | Offline checks passed | 142 service and 3 backup tests passed; verify live compatibility before publication |
| 240-09 Downloader refresh | Integrated, reviewed twice | yt-dlp 2026.10.26 pins, compatibility and real transfer verified; fresh regression gate passed: 13,914 tests, 75 skipped |
| 240-06 Final release checks | Pending | Installed real-file transcription, microphone, upgrade/uninstall; report limits |
| WATCH-01 Filename reuse | Backlog | Reproduce a concrete similarly named input failure before changing code |
| WATCH-02 Diarization memory | Backlog | Measure long recordings with existing memory fixes |
| WATCH-03 Weekly comparison | See REL-03 | Review November 4–11 changes; supplement with independent research |

## Reliability follow-up

| Card | Status | Next action / acceptance |
|---|---|---|
| REL-01 Preparation cause evidence | Audited | Existing reviewed implementation retained; no duplicate fix required |
| REL-02 Error prioritization | Assessed; implementation held | Source-stream consistency reproduced with real codecs; preprocessing, retry and checkpoint compatibility still require implementation and validation |
| REL-03 Weekly research | Partial; held | Selected primary-source corrections verified; remaining research and applicability checks are open |
| REL-04 Gate discrepancy | Partial; held | Terminal-decoder fixture isolation committed; remaining host-sensitive failures are unresolved |
| REL-05 Transcription endpoints | Implemented; verification pending | [Endpoint bounds](FIX_TRANSCRIPTION_ENDPOINT_BOUNDS.md); full gate and real long-file rerun pending |
| REL-06 Recovery and settings | Implemented; joint verification pending | History and search tolerate malformed metadata; settings retain valid output formats; explicit preset models replace Accuracy intent; Linux updates stop after a failed pull |

Output-cause and audio-slice-cause fixes are included in this development
snapshot. Worker-exit recovery has independent approval for its exact
implementation; its regression tests cover real writers and worker exits.
These checks do not complete release hardware validation or authorize publication.

## Release-candidate evidence before the reliability follow-up

Record final commands, counts and review findings here as work lands. Artifact
hashes, machine-specific paths, access details and raw logs belong in ignored
local notes. The initial environment needed runtime/test dependencies installed;
no model downloads are permitted. Use existing shared models read-only.

All feature reviews completed both rounds. Fixes cover oversized-timestamp
navigation, preserving concurrent privacy changes while applying presets, normal
model capture, main-control refresh, Tk compatibility, and visible protocol-limit
warnings. Planning review corrected changelog placement and removed private worker
details. Local raw evidence is kept under `_local/release240/`; feature documents
record portable test commands.

Pre-integration evidence: `python -m pyright app core` with the isolated test
interpreter reported 0 errors, 0 warnings and 0 informations. The eight real-model
smoke/end-to-end cases passed using existing archive weights. A real spoken sample
also completed through the CLI with nonempty transcript text and SRT/JSON/TXT
outputs. The release documentation/source-notice checks passed 37 tests.
The integrated type gate remains 0 errors, 0 warnings and 0 informations.
Another 112 documentation/packaging checks passed. Real spoken-file
transcription also passed on CUDA/float16 without CPU fallback. The final combined hermetic desktop gate passed: **13,914 passed, 75 skipped,
zero failures**. It runs the same selection as `python -m pytest tests/
--ignore=tests/smoke -q` in desktop chunks. Optional model downloads were disabled;
the eight real-model cases passed separately using existing weights.
The initial run exposed a missing generated module-list update; the corrected
registry passed its full 55-test module and the fresh combined gate.
The first Portable candidate passed its built-runtime check: all 212 app/core
modules imported, Tcl/Tk started, tools and diarization assets passed. A real
spoken file also produced SRT/JSON/TXT and a persisted finished history entry
with the packaged interpreter. That unpublished candidate remains preserved. The downloader was refreshed to the verified stable 2026.10.26. Its pin, command
and runtime checks passed 171 tests; the fresh combined gate passed with the
same 13,914 tests and 75 skips. The final Windows rebuild completed from committed
source. Its transferred Portable ZIP matched the build hash and passed a fresh
desktop runtime check, including the exact downloader version, all 212 modules,
Tcl/Tk, bundled tools and assets. Real spoken-file transcription passed with the
final packaged interpreter and persisted its finished history entry. Final
documentation/packaging checks passed 86 tests. Installer upgrade/uninstall and
installed-build hardware checks remain pending; no publication has occurred.
