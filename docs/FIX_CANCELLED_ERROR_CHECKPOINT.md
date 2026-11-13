# Preserve accepted text when cancellation races an error

A cancellation can arrive after the decoder yields a valid segment but before
the next periodic checkpoint. If the next decoder step fails, or invalid timing
is being preserved separately, the normal cancellation handler is bypassed.
The error handler previously skipped its checkpoint whenever cancellation was
set. A fresh job could have no checkpoint, and a resumed job could retain only
its older prefix.

Both error handlers now try to save the accepted prefix regardless of that
cancellation flag. Resumed work combines the previous prefix with the accepted
new segments. The checkpoint remains incomplete, and rejected timing or further
raw recovery text never becomes resumable text. Clipped transcription retains
its existing checkpoint policy.

The original error still reaches the caller, and existing exports remain
untouched. A checkpoint write failure keeps its existing warning and failure
counter behavior rather than claiming persistence. Ordinary cancellation and
errors without cancellation retain the same prefix-saving behavior.

Regression cases cover fresh and resumed jobs, cancellation just after a real raw
recovery write or during a failing decoder step, ordinary cancellation, and a refused
checkpoint write.
