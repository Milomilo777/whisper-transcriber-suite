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
