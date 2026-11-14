"""Atomic JSON checkpoints for disposable native acceptance evidence."""
import json
import os
from pathlib import Path
import tempfile


def write_json_checkpoint(path, data):
    """Publish complete JSON, retaining the last checkpoint on interruption."""
    path = Path(path)
    payload = json.dumps(data, indent=2)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    stream = None
    try:
        stream = os.fdopen(fd, "w", encoding="utf-8")
        with stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if stream is None:
            os.close(fd)
        Path(temporary).unlink(missing_ok=True)
