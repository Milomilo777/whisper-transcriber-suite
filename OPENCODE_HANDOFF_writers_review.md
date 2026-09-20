# Adversarial review handoff — writers / convert / oTranscribe

Branch: `opencode/writers-review`. Fixes live in commits `d33d267` (new tests)
and `94300bd` (the fixes themselves), both already on the branch. This file is
the review summary that was missing when those commits landed.

Scope: `core/writers/` (all writers plus `ass.py` / `bilingual_srt.py`),
`core/convert.py`, `core/integrations/otranscribe.py`, and their tests.

## Verification

- `pyright app core` → **0 errors, 0 warnings, 0 informations**.
- `python -m pytest tests/ --ignore=tests/smoke -q` → **green** (final run
  exit 0). Two earlier full runs hit an unrelated, intermittent environment
  flake — `_tkinter.TclError: Can't find a usable tk.tcl` at `tk.Tk()` in
  `tests/core/test_search_dialog.py` / `test_transcript_viewer.py`; each test
  passes in isolation and on re-run, no writers/convert code is involved.
- Pre-fix proof: with the source changes stashed, the new tests fail — 36
  failures in a full-suite pre-fix run (the target-format cases that ignore
  timestamps, e.g. `txt`, still pass) — and all pass after the fix.
- Regression evidence: every writer's output was byte-compared pre-fix vs
  post-fix on valid inputs (basic cues, unicode, speakers, karaoke words,
  empty lists, blank/whitespace segments). All text writers are byte-identical
  except the one intended `.otr` blank-segment change below. DOCX/PDF/SMTV
  raw bytes contain embedded timestamps so they differ between any two runs;
  comparing inner zip members, `word/document.xml` is identical for every
  valid input.

## Real bugs fixed

### 1. One malformed timestamp dropped an entire output file

A transcript JSON can be hand-edited or re-fed from an external tool. Every
writer except `tsv` / `json` / `ass` read `start` / `end` with a bare
`float(seg[...])`, so a single segment with a missing key, `None`, `"abc"`,
`NaN`/`Infinity`, or an integer too large for a float raised `KeyError` /
`TypeError` / `ValueError` / `OverflowError` and aborted that format's whole
write:

- `srt`, `vtt`, `lrc`, `md`, `inqscribe`, `express_scribe`, `docx`, `pdf`,
  `smtv_docx`, `bilingual_srt` (viewer's bilingual export), and
  `otranscribe.whisper_json_to_otr` / `segments_to_otr` (also `KeyError` on a
  missing `start`).
- `elan._ms`, `inqscribe.fmt_inqscribe_time`,
  `express_scribe.fmt_express_scribe_time` clamped NaN but not `Infinity`, so
  `Infinity` still reached `int(round(inf))` → `OverflowError`.
- `smtv_docx_writer._fmt_smtv_time` and the base `fmt_srt_time` /
  `fmt_lrc_time` had the same huge-integer `OverflowError` hole; `tsv._ms` /
  `json_writer._safe_float` / `ass._coerce` caught only `TypeError,
  ValueError`.
- `otr_to_srt` crashed on a corrupt `media-time` (`"abc"`) and on a
  `data-timestamp="nan"` in the `.otr` HTML.

Fix: one shared `core.writers.base.coerce_seconds(value, default=0.0)` that
accepts numeric strings, maps `None` / non-numeric / non-finite / too-large
values to `default`, and is now used at every segment-level time read; the
format-level helpers (`_ms`, `fmt_inqscribe_time`, `fmt_express_scribe_time`,
`_fmt_smtv_time`, `fmt_srt_time`, `fmt_lrc_time`, `_safe_float`, `_coerce`)
also reject non-finite / non-float-convertible values. A missing `end` falls
back to the segment start (matching `convert._parse_json`); a timestamp the
formatter cannot represent clamps instead of raising.

Tests: `tests/core/test_writers_malformed_input.py`
(`test_text_writer_survives_malformed_timestamps` over all 12 text formats,
`test_binary_writer_survives_malformed_timestamps` over docx/pdf/smtv_docx,
`test_bilingual_srt_writer_survives_malformed_timestamps`,
`test_time_formatters_clamp_non_finite_and_huge_int`), plus
`test_parse_json_tolerates_huge_integer_timestamps` and
`test_convert_file_survives_hand_edited_json` in `tests/core/test_convert.py`,
and `test_whisper_json_to_otr_tolerates_malformed_segments`,
`test_segments_to_otr_tolerates_missing_and_malformed_fields`,
`test_otr_to_srt_tolerates_corrupt_media_time_and_timestamp` in
`tests/integrations/test_otranscribe.py`.

### 2. Non-string `text` crashed writers and the converter

`normalize_text` called `text.split()` directly, so `{"text": 42}` raised
`AttributeError` in `srt`, `vtt`, `tsv`, `txt`, `md`, `lrc`, `elan`,
`inqscribe`, `express_scribe`, `ass`, `docx`, `pdf`; `json_writer` and
`convert._parse_json` did `(value or "").strip()` with the same result, and
`otranscribe` passed the raw value to `html.escape`. In `convert` this was an
uncaught `AttributeError` instead of the documented `ConvertError`, reached
by the "Convert transcript" picker on any such file.

Fix: `normalize_text` now takes `object` and coerces `None` → `""`, anything
else → `str()`; `json_writer`, `convert._parse_json`, and
`otranscribe.whisper_json_to_otr` / `_segments_to_otr_string` do the same
explicitly.

Tests: `test_text_writer_survives_non_string_text` (all text formats),
`test_docx_writer_survives_non_string_text`,
`test_pdf_writer_survives_non_string_text`,
`test_normalize_text_coerces_non_string`,
`test_parse_json_coerces_non_string_text`.

### 3. Unusable `words` crashed VTT/ASS/JSON — and VTT silently emptied cues

- `vtt._karaoke_payload` / `ass._karaoke_payload` iterated a non-list
  `words` value (`TypeError`) or, when every word was non-dict / blank,
  VTT returned an empty cue body and discarded the segment text (ASS already
  fell back to the text).
- `json_writer` did `w.get(...)` on non-dict word entries (`AttributeError`)
  and iterated a non-list `words`.

Fix: non-list `words` is treated as absent; non-dict entries are skipped;
VTT's no-usable-word case falls back to the segment text like ASS; the JSON
writer only emits `words` when at least one dict entry survives.

Tests: `test_vtt_karaoke_falls_back_to_text_when_words_unusable`,
`test_vtt_karaoke_ignores_non_list_words`,
`test_json_writer_skips_non_dict_words`,
`test_json_writer_ignores_non_list_words`.

## Improvements

- `_segments_to_otr_string` now skips blank segments (and non-dict entries in
  `segments_to_otr`) instead of emitting an empty timestamp paragraph —
  matching `whisper_json_to_otr` and every other writer that skips blanks.
- `convert._parse_tsv` / `_parse_eaf` also catch `OverflowError`, so a huge
  integer in a malformed table/slot is skipped like any other bad value
  rather than aborting the parse.
- `otranscribe`: `fmt_otr_time` (public API) and `_fmt_srt_time` now clamp
  NaN / Infinity / non-numeric input instead of raising.

## Deliberately not changed

- `write_bytes()`-is-real / `write()`-raises for docx / pdf / smtv_docx.
- The shared filename-collision index in `_write_outputs`.
- The `tsv` / `json` missing-`end` default (0.0): no crash, and changing the
  default would alter output for well-formed readers of malformed data.
- Writers that intentionally emit empty cues (`srt`, `vtt`, `tsv`, `txt`,
  `lrc`) — current output shape is stable and depended on.
- PDF CJK glyph coverage (reportlab base-14 fonts) — a real limitation but a
  font-embedding change, not a malformed-input bug.

## Adversarial self-critique

Re-read the full diff looking for changes that are not real bugs: the only
deliberate output change on *valid* input is the `.otr` blank-segment skip,
which is a consistency fix with a direct test (`test_segments_to_otr_skips_non_dict_and_blank_segments`).
`coerce_seconds` clamping a malformed `end` to `start` (rather than its old
independent 0.0) only fires on values that previously crashed the write, and
keeps `end >= start`. No documented invariant is contradicted: the binary
`write()`-raises contract, the collision-index semantics, and the
NaN/Inf-clamping design are all preserved — and the clamping helpers are now
actually reachable (the bare `float()` used to raise before they ran).

## Second-pass independent re-check (muse-spark-1.3-contributor)

Date: 2026-09-20. Branch commits at review time: `d33d267` (tests),
`94300bd` (fixes), `dea318b` (this handoff file).

### What was verified from the first pass, and how

- **Claim 1 (malformed timestamps abort whole file): proven by revert.**
  Overwrote `core/writers/srt.py` with its `master` version
  (`git show master:core/writers/srt.py`), leaving all new tests in
  place: `test_text_writer_survives_malformed_timestamps[srt]` fails
  with the exact claimed mechanism (`KeyError: 'start'` from the old
  `float(seg['start'])`). Restored via `git checkout HEAD --`, test
  green again, worktree clean (`git status --short` empty).
- **Claim 2 (non-string `text`): verified by code path + passing tests.**
  Old `normalize_text` called `text.split()` (`AttributeError` on `42`)
  and old `convert._parse_json` did `(value or "").strip()` — same
  crash. New `test_text_writer_survives_non_string_text` (all 12 text
  formats) plus docx/pdf/smtv variants pass on this branch.
- **Claim 3 (unusable `words`): verified with one correction (below).**
  Non-list `words` handling (VTT/ASS) and `json_writer` non-dict
  filtering pass. But the handoff prose over-claims slightly: it says
  "non-dict entries are skipped" as a blanket statement, while VTT's
  `_karaoke_payload` had no such guard — see finding F1.

### New bugs found and fixed (all reproduced before fixing)

- **F1. VTT crashed on non-dict word entries — first-pass fix was
  incomplete.** `vtt._karaoke_payload` did `w.get("start")` with no
  `isinstance(w, dict)` guard, so
  `{"words": ["bad", 5]}` raised `AttributeError` and aborted the whole
  `.vtt` (ASS already had the guard; `json_writer` and
  `convert._parse_json` filter too). Repro before fix:
  `vtt.write([{..., "words": ["bad", 5]}])` → `AttributeError: 'str'
  object has no attribute 'get'`. Fix: skip non-dict entries, mirroring
  ASS (`core/writers/vtt.py`).
- **F2. VTT word timestamps still had the `OverflowError` hole.**
  The word-level coercion caught only `(TypeError, ValueError)`, so a
  huge-integer word `start` (`10**400`) raised `OverflowError` and
  aborted the file — the exact bug class the first pass eliminated at
  segment level. Repro before fix confirmed `OverflowError: int too
  large to convert to float`. Fix: route through `coerce_seconds`
  (handles None/non-numeric/Overflow/non-finite with segment-start
  fallback), replacing the nested try/except.
- **F3. `fmt_ass_time` still raised on huge integers.** Its bare
  `seconds = float(seconds)` was missed while every sibling formatter
  (`fmt_srt_time`, `fmt_lrc_time`, elan/inqscribe/express_scribe,
  smtv, tsv, json `_safe_float`) was hardened. Repro:
  `fmt_ass_time(10**400)` → `OverflowError`. Public formatter, same
  hand-edited-JSON threat model. Fix: try/except
  `(TypeError, ValueError, OverflowError)` → `0.0`, mirroring siblings.
- New tests in `tests/core/test_writers_malformed_input.py`:
  `test_vtt_karaoke_skips_non_dict_word_entries`,
  `test_vtt_karaoke_falls_back_when_all_words_non_dict`,
  `test_vtt_karaoke_clamps_huge_int_word_start`,
  `test_ass_formatter_clamps_huge_int`. Each fails on the pre-fix code
  per the repros above and passes after.

### Reviewed and deliberately not changed

- **Non-dict *segments* (`srt.write([None])` etc. raise
  `AttributeError`).** Every in-repo producer filters these before they
  reach a writer: `convert._parse_json` skips non-dict entries, the
  transcript viewer filters at load (`transcript_viewer.py`, segments
  comprehension keeping only dicts), and the transcriber pipeline only
  emits dicts. The writer type contract is `list[dict]`; hardening all
  13 writers would be scope creep with no reachable crash path.
- `tsv`/`json` missing-`end` default, `write()`-raises binary contract,
  `.otr` blank-segment skip, PDF CJK coverage — agree with the first
  pass's "deliberately not changed" list, no new evidence against it.
- `smtv _fmt_smtv_time` resetting non-`int`/`float` input (e.g. numeric
  strings) to `0.0` instead of parsing: pre-existing behavior, callers
  now pass `coerce_seconds` output (finite floats), not reachable with
  strings in-repo. Left alone.

### Final verification (this pass)

- `pyright app core` → **0 errors, 0 warnings, 0 informations**.
- `python -m pytest tests/ --ignore=tests/smoke -q` → **green**
  (exit 0; targeted files
  `test_writers_malformed_input.py`/`test_otranscribe.py`/`test_convert.py`
  also green in isolation). No valid-input output changes: new fixes
  only fire on inputs that previously raised (non-dict words, huge-int
  word times, huge-int `fmt_ass_time` arg).

## Second-pass independent re-check (muse-spark-1.3-contributor) — follow-up pass

Date: 2026-09-20 (later run, same day). Branch commits at review time:
`d33d267` (tests), `94300bd` (fixes), `dea318b` (handoff),
`cdbe24f` (prior second-pass fixes + prior second-pass section above).
This section records an additional independent pass done on top, per the
re-check task template.

### What was verified from the earlier passes, and how

- **First-pass claim 1 (malformed timestamps abort whole file): holds.**
  `master:core/writers/srt.py` uses bare `float(seg['start'])` /
  `float(seg['end'])` (confirmed in diff); branch routes through
  `coerce_seconds`. Current
  `test_text_writer_survives_malformed_timestamps[srt]` passes on branch.
- **Prior second-pass F1–F3 (VTT non-dict words, VTT huge-int word
  times, `fmt_ass_time` huge-int): proven by revert.** Overwrote
  `core/writers/vtt.py` with its `master` version, leaving all tests in
  place: `test_vtt_karaoke_skips_non_dict_word_entries`,
  `test_vtt_karaoke_falls_back_when_all_words_non_dict`, and
  `test_vtt_karaoke_clamps_huge_int_word_start` all fail
  (`AttributeError` on `w.get`, `OverflowError: int too large to
  convert to float`). Restored, tests green again. For F3, `master`'s
  `fmt_ass_time` has the bare `seconds = float(seconds)` line
  (confirmed via `git show`), and bare `float(10**400)` raises
  `OverflowError` — the exact claimed mechanism; new
  `test_ass_formatter_clamps_huge_int` passes on branch. Worktree was
  clean after each restore.

### New bug found and fixed (reproduced before fixing)

- **F4. `otr_to_srt` crashed on a non-string `text` payload — same
  corrupt-input class the earlier passes hardened everywhere else.**
  A hand-edited / corrupt `.otr` with e.g. `{"text": 42,
  "media-time": 0}` reached `parser.feed(42)`, raising `TypeError:
  can only concatenate str (not "int") to str` (full traceback
  confirmed) and aborting the whole import. Reproduced for `42`,
  `["<p>hi</p>"]`, `{"html": "hi"}`, `True` — all raised `TypeError`.
  Fix: coerce a non-`str` payload to `""` in `otr_to_srt`
  (`core/integrations/otranscribe.py`) — no cues to extract, so the
  import yields empty output instead of a traceback.
- New test `test_otr_to_srt_tolerates_non_string_text` in
  `tests/integrations/test_otranscribe.py` (all four shapes, asserts
  `""` output). Proven: fails on the pre-fix hunk (`TypeError` at
  `html/parser.py feed`), passes after. Fix fires only on inputs that
  previously raised.

### Reviewed and deliberately not changed

- **`convert._parse_json` passes NaN/Infinity through to intermediate
  segments** (`float("nan")` doesn't raise, so no fallback fires).
  Not fixed on purpose: every emit path clamps via `coerce_seconds` /
  `_safe_float` (verified: NaN/Inf segments render as `00:00:00,000`
  in SRT), so there is no crash and no user-visible wrong output —
  fixing it would be theory, not a concrete failure.
- **`json_writer` keeps a non-string word value as-is** (`"word":
  w.get("word", "")` can emit a JSON number for malformed input). No
  crash (`json.dumps` handles it) and re-import coerces via `str()`;
  normalising it here would change output shape with no failure behind
  it. Left alone.
- Non-dict *segments*, `write()`-raises binary contract, `.otr`
  blank-segment skip, PDF CJK coverage, `tsv`/`json` missing-`end`
  default — agree with both earlier passes, no new evidence against.

### Final verification (this pass)

- `pyright app core` → **0 errors, 0 warnings, 0 informations**.
- `python -m pytest tests/ --ignore=tests/smoke` → **2237 passed,
  1 skipped, exit 0** (full hermetic suite, ~111s).
