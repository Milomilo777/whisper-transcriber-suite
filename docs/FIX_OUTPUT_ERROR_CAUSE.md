# Output error causes

Output creation and writing keep the underlying exception when they fail. Failure diagnostics therefore distinguish permission denied and a full disk from an unexplained runtime error, without sending exception text.

Exclusive filename claims still protect earlier and concurrent transcripts. Existing names are skipped; a denial on an absent name gets one retry at the next index before failing with its original OS cause. Other storage errors stop immediately. A failed claim releases any earlier placeholders from that output set. Each format also creates its destination directory inside its own failure boundary, preserving directory errors before a later file-open failure can replace them. Writers still run independently: one failing format does not discard a format already saved. If every writer fails, the aggregate RuntimeError chains the last writer exception and output diagnostics follow that explicit chain until the first concrete OS error. Previously handled implicit exception contexts cannot replace the active write failure; model and preparation diagnostics retain their existing traversal.

Validation commands:

```text
python -m pytest tests/core/test_output_error_cause.py tests/core/test_output_error_context.py tests/core/test_write_outputs_race.py tests/core/test_failure_clue.py tests/core/test_failure_clue_review.py tests/core/test_failure_clue_context_chain.py
python -m pyright app core
python -m pytest tests/ --ignore=tests/smoke -q
```

The focused cases cover real Windows read-only-file denial, simulated disk-full/permission failures at claim, flush and replacement, cleanup, collision races and partial success. Failed claims enforce exactly two attempts for access denial and one for full-disk, read-only filesystem and other I/O errors. Mutations removing output-chain classification or allowing an extra permission retry must fail the corresponding assertions. No input or model is needed.
