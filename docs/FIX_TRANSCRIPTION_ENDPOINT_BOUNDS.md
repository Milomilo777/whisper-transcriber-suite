# Transcription endpoint bounds

Whisper timestamp predictions can extend beyond the decoded audio. The transcription path uses the decoder's sample duration before VAD, shifted onto the source timeline for clips and resumes. A verified original PCM extent also limits resampling or preprocessing that adds samples. PCM verification checks that the final declared frame is readable; an unverified container estimate does not truncate speech. Completed checkpoints retain the audio extent with the source identity.

Segments and words are checked before periodic checkpoints and after post-processing. Output dispatch also constrains timestamp rounding to the format's last representable tick inside the recording. Partial subtitles and chapter sidecars use the same bound. Existing tiny-cue repair remains available inside the recording, and generic writer calls without a known audio extent keep their existing behavior.

Text and word labels are never discarded to fit an endpoint. A wholly out-of-range segment or word, or a cue too short for its format, is saved in a new durable recovery record before the timing error is reported. Existing checkpoints and completed output files are preserved. Reaching an endpoint never substitutes for exhausting the decoder iterator.

Validation uses all registered writers, fractional-sample endpoints, a long PCM input, clipped and resumed offsets, checkpoints, post-processing, container-duration discrepancies and recovery controls. Independent mutations must reject disabled checkpoint bounds and upward rounding at EOF. Actual long-file validation remains separate from hermetic tests.

```text
python -m pytest tests/core/test_transcription_endpoint_bounds.py tests/core/test_fixpack_timerange_slice.py tests/core/test_resume_from_cancellation.py tests/core/test_cuda_decode_recovery.py
python -m pyright app core
python -m pytest tests/ --ignore=tests/smoke -q
```
