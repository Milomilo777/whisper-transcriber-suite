# Resume completed text after changing decoding settings

A checkpoint marked `transcription_completed: true` already contains the entire
decoded transcript. It is written before post-processing so a diarization or
formatting failure can be resumed. Validation previously rejected a changed
device, precision, batch size, model or backend before reaching that completed
branch. Resume deleted the checkpoint and requested a fresh transcription.

Completed checkpoints now pass decoder compatibility checks after verifying
schema, source identity and a segment list. This does not accept partial
checkpoints with changed decoding settings, bypass timing checks, or turn a
non-boolean completion marker into permission to skip validation. Post-processing,
cancellation, output persistence and successful checkpoint removal retain their
existing order. Failed writes retain the checkpoint.

The Fable crash-recovery review's settings-mismatch finding was reproduced with
seven failures and seven controls before the fix. Integration regressions write
real checkpoints and SRT/JSON/TXT outputs from a synthetic PCM file while both
audio slicing and decoder creation are forbidden. This is checkpoint recovery
proof, not a GPU transcription or native diarization test.

A review also reproduced two completed-translation failures when the newly
selected decoder could not translate. Decoder capability is now checked only
when more ASR is needed; saved English text keeps its translated filename marker.
