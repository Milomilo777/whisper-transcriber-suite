# Reliability investigation checkpoint — 2026-11-11

This step log supplements [BOARD](BOARD.md).
No publication, deployment or new release is authorized by this document.

## Completed changes and retained validation

- Preparation diagnostics retain their original process cause; the existing
  reviewed fix was audited rather than implemented again.
- Output-error diagnostics and worker-exit recovery remain pinned to their
  reviewed implementations. The [recovery record](FIX_WORKER_EXIT_OUTPUT_RECOVERY.md)
  describes filename ownership checks and their limitations.
- The terminal-decoder fixture selects CPU explicitly so host GPU detection
  cannot construct real replacement weights. All partial-checkpoint assertions
  remain intact; separate tests cover CUDA recovery. This is test isolation,
  not a transcription behavior change.
- The combined development snapshot passed the full hermetic gate:
  13,980 passed, 75 skipped, no failures; Pyright reported zero errors,
  warnings and informations. These results are retained evidence for that
  snapshot, not a new application gate for this documentation checkpoint.

## Held investigations

- Real two-track codec fixtures show inconsistent stream selection between
  full faster-whisper decoding, slicing and the window reader used by rescue.
  A complete policy must cover MLX, other backends' automatic selection,
  denoise and separation fallbacks, derived caches, partial checkpoints and
  bounded time-range costs. No production fix or spoken-ASR validation is
  claimed.
- A direct decoder-adapter call with explicit timestamps can suppress a lazy
  failure after a successful recovery callback. The reviewed regression is
  intentionally failing. No current GUI producer of those explicit arguments
  was found; do not attribute unrelated user errors to this internal seam.
  A yielded timestamp or media duration does not prove iterator exhaustion.
- Installed VAD collection performs repeated growing copies. A per-group
  metadata discrepancy was also reproduced, but tested downstream consumers
  used offsets, durations and the original speech chunks; no resulting ASR
  corruption was established. No dependency upgrade or compatibility patch
  has been selected.
- Windows listener metadata, per-cue speaker editing, durable completion
  records and transfer identity have reviewed assessments or proposals;
  they are not completed capabilities. Some earlier environment-sensitive
  failures remain unresolved.

## Restart acceptance

Re-read current instructions and inspect the exact branch and dirty files.
Preserve held tests and raw evidence. Verify research against primary sources,
write regressions before production changes, and retain compatibility and
save-before-report ordering. Each implementation still needs mutation evidence,
focused checks, the full gate, independent review and relevant real-data
validation. Release hardware, localization and publication gates remain open.
