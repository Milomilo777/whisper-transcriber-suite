# Output recovery after a worker exit

The writer reuses the lowest available shared filename index. A higher numbered file can therefore belong to an older run. If a worker exits after saving outputs but before reporting their paths, recovery searches recognised indices, including gaps, instead of assuming the highest contiguous index is current.

Reported output paths remain authoritative. For missing-path recovery with a run timestamp, exactly one plausible set must fall inside the run's freshness window and every expected path must be a regular file. Multiple recent sets, a new partial set, inaccessible metadata, future timestamps and conflicting input filenames remain failures; their files are preserved. NFC/NFD ownership checks and native case aliases are retained. Known custom filename templates and duplicate-extension plans require reported paths rather than a guessed default plan. Older tasks without a start timestamp keep the legacy fallback.

The existing two-second timestamp tolerance remains because filesystem precision varies; [CPython documents this limitation](https://docs.python.org/3.13/library/os.html#os.stat_result). Filename and timestamp inference is best effort, not a durable per-job result identifier. It cannot establish the provenance of arbitrary copied or edited files. Normal worker-reported results avoid this inference.

Ownership checks also invert one supported writer step for each candidate: an optional translation suffix followed by an optional shared index. For example, a source named `clip (7).wav` cannot claim fresh `clip (7).srt` while a distinct `clip.wav` exists; the latter can produce that file at index 7. The same applies to literal translated names. Inversion is not recursive, so an unambiguous `clip (7) (1).srt` can still be recovered. Translation suffix case aliases use native file identity, preserving distinct names on case-sensitive filesystems.

Validation uses real SRT/JSON writers, Unicode and native case paths, removed index slots, unrelated numbered sources and ambiguous/partial controls. A real child saves its files and exits with code 1 without a completion event; the parent must persist the recovered history paths before showing the result. Disabling timestamp-aware recovery must fail these regressions.
Reverse-ownership regressions also exercise the parent failure/history path and preserve every foreign output byte. Removing inverse ownership detection must fail them while the unambiguous higher-index controls remain green.

```text
python -m pytest tests/core/test_worker_exit_output_recovery.py tests/core/test_salvage_unicode_names.py tests/core/test_worker_lifecycle_c251b.py
python -m pyright app core
python -m pytest tests/ --ignore=tests/smoke -q
```
