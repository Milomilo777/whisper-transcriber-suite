# Transcription endpoint bounds

Whisper timestamp predictions can extend beyond the decoded audio. The transcription path uses the decoder's sample duration before VAD, shifted onto the source timeline for clips and resumes. A verified original PCM extent also limits resampling or preprocessing that adds samples. PCM verification checks that the final declared frame is readable; an unverified container estimate does not truncate speech. Completed checkpoints retain the audio extent with the source identity.

Segments and words are checked before periodic checkpoints and after post-processing. Output dispatch also constrains timestamp rounding to the format's last representable tick inside the recording. Partial subtitles and chapter sidecars use the same bound. Existing tiny-cue repair remains available inside the recording, and generic writer calls without a known audio extent keep their existing behavior.

Text and word labels are never discarded to fit an endpoint. A wholly out-of-range segment or word, or a cue too short for its format, is saved in a new durable recovery record before the timing error is reported. Existing checkpoints and completed output files are preserved. Reaching an endpoint never substitutes for exhausting the decoder iterator.

Rejected decoder cues and rescue replacements do not enter the resumable prefix. On a timing error, the checkpoint retains the latest accepted segments and their cursor, while the separate recovery record retains the rejected text and original clocks. A recovery-write failure still leaves the accepted prefix eligible for checkpointing. This preserves recovery; it does not repair model predictions whose start lies outside the recording or report the failed run as complete.

After the initial raw record is durable, a rejected first-pass or resumed cue can
capture further text from the same lazy decoder into an additional recovery
record. Those cues never enter a checkpoint or timed output. Capture stops on
cancel/pause, a decoder/conversion error, 64 iterator steps, two elapsed seconds
between steps, or 128 Ki characters of additional text. Loop-guard ticks count
as steps; a final yielded cue is kept whole even if it exceeds the text budget.
The additional record states whether the iterator exhausted or capture stopped
early. When no further cue is available, only the initial record is kept and
the reported error includes the stop reason. Records are retained for manual
recovery; repeating a failed attempt does not erase an earlier record.
The elapsed check cannot preempt a native decoder call; the worker watchdog
still handles a blocked call. Capture disables CUDA retry and loop-guard restart
for the failed run, and reads subsequent repeated cues without filtering them.
It cannot reconstruct cues the guard had already dropped before the rejection.
Pause ends this failed run's capture rather than waiting to resume it.
A capture/storage failure does not replace already written recovery data or the
valid prefix. Storage errors retain their operating-system classification and
include the path of the initial record that was successfully saved.

Validation uses all registered writers, fractional-sample endpoints, a long PCM input, clipped and resumed offsets, checkpoints, post-processing, container-duration discrepancies and recovery controls. Independent mutations must reject disabled checkpoint bounds and upward rounding at EOF. Actual long-file validation remains separate from hermetic tests.

```text
python -m pytest tests/core/test_transcription_endpoint_bounds.py tests/core/test_fixpack_timerange_slice.py tests/core/test_resume_from_cancellation.py tests/core/test_cuda_decode_recovery.py
python -m pyright app core
python -m pytest tests/ --ignore=tests/smoke -q
```
