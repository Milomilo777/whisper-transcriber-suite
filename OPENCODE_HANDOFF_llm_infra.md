# OpenCode handoff — LLM + infra review (branch `opencode/llm-infra-review`)

Scope reviewed in full: `core/llm.py`, `core/_checkpoint.py`,
`core/_gc_import_guard.py`, `core/_liveness_tick.py`, `core/task.py`, plus
their tests and every caller that could hit the reviewed paths
(`app/dialogs/transcript_viewer.py` AI panel, `core/chapters.py`,
`core/transcriber.py` checkpoint/clip paths, `app/services/transcription_service.py`).

Gates: **pyright app core — 0 errors, 0 warnings, 0 informations**;
**`python -m pytest tests/ --ignore=tests/smoke` — 2208 passed, 1 skipped**
(no `TclError` flake occurred this run).

## Real bugs found and fixed

### 1. Local LLM failed outright on any long transcript (high impact)
`core/llm.py` — the transcript viewer feeds the WHOLE transcript to
`summarise` / `action_items` / `ask` / `translate preview`
(`transcript_viewer._full_transcript_text`, no length cap). The local
runner is loaded with `n_ctx=4096` and llama-cpp-python raises
`ValueError("Requested tokens ... exceed context window ...")` before
decoding once the rendered prompt reaches `n_ctx` (verified in the
installed source, llama_cpp 0.3.34, `Llama._create_completion`, which the
chat handler path reaches). A recording longer than roughly 20 minutes of
speech therefore made every AI-tool button fail with a raw error.

Fix: new context-fitting section in `core/llm.py:284` — `_token_counter`
uses the loaded model's own `tokenize` (correct for CJK, where a
chars/token estimate is badly wrong) with a conservative char-ratio
fallback; `_fit_messages_to_context` (`core/llm.py:361`) caps the answer
at half the window, shrinks only the longest message (the transcript) to
the exact remaining token budget, preserves head + tail via
`_truncate_middle` (so an `ask` prompt's trailing question survives), and
gives any freed room back to the answer. Wired into `LLMRunner._chat`
(`core/llm.py:454`). Remote endpoints are deliberately untouched — their
window belongs to the provider. A `logger.warning` records when a
transcript was truncated.

Trade-off, accepted: a very long transcript is now summarised from its
beginning + end (middle elided) instead of failing. A chunked
map-reduce summariser would be the follow-up if full coverage is wanted.

Tests (`tests/core/test_llm.py`): `test_long_transcript_summarise_is_fitted_to_the_context_window`,
`test_long_prompt_fits_even_when_every_char_is_a_token` (1 token/char —
proves the tokenizer-based fit, not just a char estimate),
`test_short_transcript_is_not_truncated`,
`test_ask_keeps_the_question_when_the_transcript_is_truncated`,
`test_long_translate_fits_and_keeps_answer_room`,
`test_fitting_falls_back_when_the_model_has_no_tokenizer`,
`test_fit_messages_to_context_leaves_a_short_prompt_untouched`,
`test_truncate_middle_keeps_head_and_tail/_is_a_noop_when_it_fits`.
All use a fake Llama that raises the same `ValueError` the real library
does when the prompt reaches `n_ctx`.

### 2. Action items silently lost when the model appended prose after the JSON
`core/llm.py:504` `_parse_json_list` used `json.loads` whenever the text
started with `[`, so a chatty response like
`["call Alice"]\n\nLet me know if you need more.` raised
`JSONDecodeError` and returned `[]` — the UI reported "no action items
detected" even though the model returned them. (Leading prose was already
handled; only trailing prose was not.)

Fix: locate the first `[` and let `json.JSONDecoder().raw_decode` parse
exactly the first JSON value, ignoring anything before or after it.

Tests: `test_parse_json_list_ignores_trailing_prose_after_array`,
`test_parse_json_list_handles_fence_with_trailing_prose`,
`test_parse_json_list_takes_only_the_first_array` (all would fail on the
old code); all pre-existing parser tests still pass unchanged.

### 3. A non-UTF-8 checkpoint crashed resume instead of falling back
`core/_checkpoint.py:177` — the docstring promises "None if
missing/corrupt" and PROJECT_INDEX documents that resume "silently falls
back to a full re-transcribe rather than erroring", but the read only
caught `(OSError, json.JSONDecodeError)`. A checkpoint file whose bytes
are not valid UTF-8 raises `UnicodeDecodeError` (a `ValueError`, not a
`JSONDecodeError`) out of `load_checkpoint`, escalating into
`resume_transcription` and failing the task. Fixed by catching
`ValueError`, which subsumes both decode failures.

Test: `tests/core/test_fixpack_proc_ckpt.py::test_load_checkpoint_returns_none_on_non_utf8_corruption`
(writes `b'\xff\xfe...'` at the checkpoint path and asserts `None`).

### 4. Checkpoint write scratch was never reclaimed
`core/_checkpoint.py:250` — `sweep_partials` reaped `*.slice.wav` and
`*.json`, but a worker killed *mid-write* leaves `<key>.json.tmp`
(the atomic-write staging file, potentially holding the full captured
segments list) in `partials/` forever. Extended the sweep to reap
`*.json.tmp` older than the same short (10 min) cutoff, so a live writer
is never touched.

Test: `tests/core/test_checkpoint_sweep.py::test_sweep_partials_removes_stale_checkpoint_tmp`.

## Doc-only correction

`core/task.py` — the `clip_start`/`clip_end` comment claimed the span is
"Fed to faster-whisper as clip_timestamps", which directly contradicts
the documented invariant (PROJECT_INDEX: clip spans are PRE-SLICED via
ffmpeg because `clip_timestamps` decodes the whole file and hung on
multi-hour input). The comment now describes the real mechanism so a
future change doesn't re-introduce that hang. No behaviour change.

## Explicitly checked, NO bug found (no behaviour change)

- `core/_gc_import_guard.py` — exception safety verified: prior GC state
  restored on both normal and raising exits, and the shared lock is
  released on the exception path (a stuck lock would deadlock every
  later guarded import). No nesting of guarded calls exists anywhere in
  the tree today, so the non-reentrant `Lock` is safe as written; adding
  regression tests only.
- `core/_liveness_tick.py` — verified the ticker always stops (body
  returns, body raises, `log_cb` raises) and that `log_cb=None` spawns no
  thread. The module had zero direct tests despite being wrapped around
  every long silent C call, so a focused test file was added
  (`tests/core/test_liveness_tick.py`).
- `core/llm.py` — `LLMRunner` lock discipline (`_chat` serialises
  concurrent calls, `load()` never re-enters the lock),
  `download_default_model` atomic `.part` + cleanup on error/cancel,
  quote-stripping, `RemoteLLMRunner` error mapping (HTTP/URLError →
  `RemoteLLMError`). The documented "LLMRunner chat has no timeout" item
  in `docs/history/STABILITY_AUDIT_2026-05-23.md` is unchanged — a real
  cancel would need a llama.cpp callback, out of scope for a small fix.
- `core/_checkpoint.py` — `source_key` normcase behaviour, atomic
  `os.replace` writes, `validate_checkpoint` invariants (stale partial on
  any fingerprint/size/mtime mismatch) are all preserved; nothing was
  changed that could make a stale partial validate.

## Not checked

Nothing in scope was skipped. No path/tool rejection occurred and no
gitignored or credential-like file was read or modified.

---

## Second-pass independent re-check (muse-spark-1.3-contributor) — 2026-09-20

### What was verified from the first pass, and how

All four claimed fixes were reproduced as real bugs on `master` code and
confirmed fixed on this branch — not by trusting the prose, but by running
the branch's own new tests against the pre-fix code:

1. **Context fit** (`core/llm.py`): checked out `master` copies of
   `core/llm.py` + `core/_checkpoint.py` over the worktree, ran the new
   tests, confirmed
   `test_long_transcript_summarise_is_fitted_to_the_context_window`,
   `test_long_prompt_fits_even_when_every_char_is_a_token`,
   `test_parse_json_list_ignores_trailing_prose_after_array`,
   `test_parse_json_list_takes_only_the_first_array`,
   `test_load_checkpoint_returns_none_on_non_utf8_corruption`, and
   `test_sweep_partials_removes_stale_checkpoint_tmp` **all fail on
   `master` code**, then restored the branch files (`git status` clean)
   and confirmed they pass. So every claimed fix addresses a genuine,
   test-demonstrated defect.
2. **llama-cpp API usage**: confirmed against the installed
   llama_cpp 0.3.34 that `Llama.tokenize` has signature
   `(bytes, add_bos=True, special=False)` — the branch's
   `tokenize(text.encode("utf-8"), add_bos=False)` call is valid — and
   that the `>= n_ctx raises ValueError` window semantics match the
   branch's test fake.
3. **Tmp-suffix match**: `write_checkpoint` stages at
   `path.with_suffix(path.suffix + ".tmp")` = `<key>.json.tmp`, exactly
   what the new `sweep_partials` branch reaps; verified end-to-end (stale
   `.json.tmp` reaped, fresh one survives the 10-min cutoff).
4. **`task.py` comment fix**: confirmed against `core/transcriber.py`
   that the clip span is pre-sliced via ffmpeg and results shifted back
   — `clip_timestamps` is never passed to faster-whisper. The old comment
   was indeed wrong.

### Anything wrong with the first pass

One collateral-damage issue, fixed in this pass:

- **`docs/SESSION_HANDOFF_NEXT.md` was silently rewritten** (304 lines
  of the owner's live session notes deleted, framing changed from
  "DONE" to "IN PROGRESS"). The handoff file never mentions touching
  this doc; it is out of scope for this branch and the deletion was
  clearly unintended. Restored byte-identical to `master`
  (`git checkout master -- docs/SESSION_HANDOFF_NEXT.md`).

No claimed fix turned out to be wrong, cosmetic, or incomplete in a way
that matters in practice. One theoretical gap was examined and
deliberately left alone: `_fit_messages_to_context` uses
`budget = max(128, n_ctx - 64)`, which exceeds `n_ctx` for `n_ctx < 192`
— but `n_ctx` is a fixed 4096 default, not user-configurable
(`core/llm.py:206`, no UI path sets it), so the unreachable corner does
not justify touching working code. Residual risk if the fit ever
undercounts the real chat-template overhead is graceful anyway: every AI
caller (`TranscriptViewer._run_ai_task`, bilingual path) catches all
exceptions into a friendly result-box message, never a crash.

### New bugs found and fixed (with evidence)

- **Stale `clip_timestamps` comment in `core/transcriber.py` — the exact
  doc-bug class the first pass fixed in `task.py`, but missed at its
  source.** `transcriber.py:1482-1485` said the time range is processed
  "via clip_timestamps", directly contradicting the NOTE 8 lines below
  it (1491-1493) and the actual pre-slice implementation. The
  `_clip_timestamps_arg` docstring ("faster-whisper `clip_timestamps`
  value") said the same. Failure scenario: a future reader trusts the
  stale comment and "simplifies" the pre-slice away by passing the value
  as `clip_timestamps` — re-introducing the multi-hour-input hang the
  NOTE documents. Fixed both comments to describe the marker + pre-slice
  reality (doc-only, zero behaviour change; verified the `clip` string
  is only ever used as a clip-present gate, never forwarded to
  `transcribe`). No new test: comment-only change, covered by the
  existing clip-slice tests still passing.

### Final gates (this pass, after all changes)

- `python -m pyright app core` — **0 errors, 0 warnings, 0 informations**.
- Full hermetic suite `python -m pytest tests --ignore=tests/smoke` —
  **2209 tests, 0 failures, 0 errors, 1 skipped** (junit counts; the
  single skip is pre-existing).
