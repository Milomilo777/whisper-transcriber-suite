# Audio slice failure causes

A nonzero ffmpeg exit during audio slicing now chains a standard `subprocess.CalledProcessError` behind the existing `RuntimeError`. The cause retains the actual command, return code and captured streams for local diagnosis. Closed preparation diagnostics can identify the process exception without including private input names or captured text. Partial-slice cleanup remains best effort before reporting failure; file locks can prevent removal. Timeout and launch errors, successful slices and resume fallback keep their existing behavior.

This follows the standard exception data used by CPython's [`subprocess.run(check=True)`](https://github.com/python/cpython/blob/3.13/Lib/subprocess.py) and the existing media-probe path. It identifies a verified source of generic preparation errors; historical generic error counts cannot establish which inputs encountered it. This change does not recover undecodable input or infer a media-specific cause from arbitrary stderr.

Validation covers nonzero positive and negative return codes, missing stderr, partial cleanup, captured cause details, closed diagnostic fields, timeout/launch controls and successful bounded slices. An external real-ffmpeg probe uses a valid synthetic WAV as a positive control and invalid synthetic media as the failure case. Removing the explicit cause must fail all three nonzero-exit regression cases.

```text
python -m pytest tests/core/test_prepare_slice_error_cause.py tests/core/test_prepare_failure_details.py tests/core/test_fixpack_timerange_slice.py tests/core/test_resume_from_cancellation.py
python -m pyright app core
python -m pytest tests/ --ignore=tests/smoke -q
```
