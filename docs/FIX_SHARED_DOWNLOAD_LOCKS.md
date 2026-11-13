# Ownership of shared resumable downloads

The pinned single-file downloader and manifest model downloader share stable
partial-file paths so interrupted transfers can resume. Previously, an unsupported
filesystem lock was logged and the transfer continued without ownership. A later
attempt could then overwrite or delete another producer's saved prefix while
restarting or rejecting its checksum.

Both producers now require the existing lock helper's strict mode before starting
network requests or touching resume files. A denied or unavailable lock stops the
attempt and preserves the existing prefix. Retry after the other producer finishes,
or use a destination whose filesystem supports locking. The helper's explicit
best-effort mode remains available to callers that do not share resume files.

Already verified single files and already accepted manifest installations still
return before requiring a write lock. Existing installation acceptance rules are
unchanged. Successful ownership retains the existing resume, hash verification and
atomic publication behavior.

Tests use real local HTTP transfers and injected native locking errors to verify
prefix preservation and zero requests without ownership. Positive cases cover
normal resumption and reuse without a write lock. The earlier no-lock transfer
test now requires refusal and preservation of saved bytes, following the reproduced
cross-producer prefix loss.

The Windows primitive raises on a failed nonblocking acquisition; see the
[Python locking documentation](https://docs.python.org/3/library/msvcrt.html#msvcrt.locking).
