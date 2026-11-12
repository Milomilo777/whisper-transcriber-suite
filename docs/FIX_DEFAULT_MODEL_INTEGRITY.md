# Integrity checks for new default model downloads

The default single-file whisper.cpp and AI Layer downloaders previously treated
a nonempty HTTP response without Content-Length as a complete model. A server
closing a partial response could therefore publish an unusable model. A declared
length alone also cannot identify wrong content of the same size.

New default downloads use immutable upstream revisions and must match both the
pinned byte count and SHA-256 before publication. Hashing runs during transfer;
an oversized stream stops immediately. Rejection removes only the attempt's own
stage and preserves an existing destination. Existing cancellation, strict
publication locking and rechecking another completed download remain in effect.

Pins come from the upstream LFS metadata for
[whisper.cpp large-v3 q5_0](https://huggingface.co/ggerganov/whisper.cpp/tree/5359861c739e955e79d9a303bcbc70fb988958b1)
and [Qwen2.5 1.5B Q4_K_M](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/tree/91cad51170dc346986eccefdc2dd33a9da36ead9).
Update the URL revision, size and digest together when changing a default model.

Explicit custom URLs retain the existing transfer checks, since the application
has no trusted digest for arbitrary models. Existing model files also retain the
previous compatibility checks; this change does not certify or replace earlier
installations. Synthetic fixtures for generic transfer and filesystem behavior
use explicit custom URLs. Separate tests exercise default pin enforcement,
missing/zero/known response lengths, wrong digests, early oversize termination,
valid pinned content and preservation of an earlier file.
