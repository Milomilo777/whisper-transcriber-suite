"""Speaker diarization worker subprocess (started by ``core.diarization.diarize``).

sherpa-onnx loads onnxruntime.dll. When the calling process already holds an
older copy (issue #7: a foreign ONNX Runtime 1.17.1 on Windows), Windows reuses
that copy and the native code crashes the whole process. Running the work in
this fresh process keeps the transcription worker, and the finished transcript
it holds, alive whatever happens here.

Protocol (newline-delimited JSON):
  stdin, one line:  ``{"audio_path", "num_speakers", "cluster_threshold"}``
  stdout events:    ``{"event": "progress", "fraction"}`` (0.0-1.0, repeated),
                    then ``{"event": "done", "segments": [{"start", "end",
                    "speaker"}]}`` or ``{"event": "error", "error"}``.
Exit code 0 after ``done``, 1 after ``error``; a native crash shows up only as
the exit code and stderr, which the parent turns into a readable reason.
"""
from __future__ import annotations

import json
import sys


def _emit(event: dict) -> None:
    # json.dumps escapes non-ASCII, so the pipe encoding never matters.
    sys.stdout.write(json.dumps(event) + "\n")
    sys.stdout.flush()


def main() -> int:
    try:
        # First, before any other import could load a different
        # onnxruntime.dll into this process.
        import sherpa_onnx  # type: ignore[import-untyped] # noqa: F401
    except Exception as e:  # noqa: BLE001 - wrong-arch/missing DLLs raise OSError too
        _emit({"event": "error", "error": f"could not load sherpa-onnx: {e}"})
        return 1

    try:
        request = json.loads(sys.stdin.readline() or "{}")
        audio_path = request["audio_path"]
        from core import diarization

        segments = diarization._diarize_impl(
            audio_path,
            num_speakers=int(request.get("num_speakers", -1)),
            cluster_threshold=float(request.get("cluster_threshold", 0.5)),
            progress_cb=lambda fraction: _emit({"event": "progress", "fraction": float(fraction)}),
        )
        _emit({"event": "done", "segments": [
            {"start": s.start, "end": s.end, "speaker": s.speaker} for s in segments
        ]})
        return 0
    except Exception as e:  # noqa: BLE001 - reported to the parent, which decides
        _emit({"event": "error", "error": str(e) or type(e).__name__})
        return 1


if __name__ == "__main__":
    sys.exit(main())
