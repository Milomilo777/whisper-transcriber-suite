"""Live end-to-end check of the slim v1.3.4 embed build against the
bugs that previously shipped broken. Drives the REAL worker over its
JSON stdin/stdout protocol (the exact process boundary where these
bugs lived) using the slim embed interpreter, then asserts every
requested output format actually lands on disk.

Run with the slim embed interpreter:
    embed_build\\python\\python.exe tools\\e2e_slim_pastbugs.py

Exercises in one transcription:
  * DOCX output is written (output_formats crosses the boundary)
  * non-srt/json formats (txt, docx) all land
  * a hyphenated language code ("en-US") normalises instead of crashing
  * a clip / time-range run (clip_start/clip_end) produces output
  * a filename with an apostrophe + space round-trips
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EMBED = REPO / "embed_build"
GUI = EMBED / "gui.py"
SRC_VIDEO = Path(os.environ.get("WHISPER_SMOKE_VIDEO", r"E:\3029-NWN-Daily-Scroll-2m_0002.mp4"))
WANT_FORMATS = ["srt", "json", "docx", "txt"]


def _readline_json(proc: subprocess.Popen, deadline: float):
    while time.time() < deadline:
        line = proc.stdout.readline() if proc.stdout else ""
        if not line:
            if proc.poll() is not None:
                raise RuntimeError(f"worker exited rc={proc.poll()}")
            continue
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue
    raise TimeoutError("deadline exceeded")


def main() -> int:
    if not SRC_VIDEO.exists():
        print(f"SKIP: test video not present: {SRC_VIDEO}")
        return 0
    if not GUI.exists():
        print(f"FAIL: embed gui.py not present: {GUI}")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="whisper_e2e_"))
    # Apostrophe + space: a name that previously mangled in subprocess IO.
    dst = tmp / "Bob's NWN clip 0002.mp4"
    shutil.copy(SRC_VIDEO, dst)
    print(f"[e2e] input: {dst}")

    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    proc = subprocess.Popen(
        [sys.executable, str(GUI), "--worker"],
        cwd=str(EMBED),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        creationflags=creationflags,
    )

    try:
        # Wait for ready (model load can take a while on first run).
        for ev in _readline_json(proc, time.time() + 300):
            e = ev.get("event")
            if e == "ready":
                print("[e2e] worker ready")
                break
            if e == "startup_error":
                print(f"FAIL: startup_error: {ev.get('message')}")
                return 1

        cmd = {
            "action": "transcribe",
            "file_path": str(dst),
            "language": "en-US",          # hyphenated → must normalise to "en"
            "resume": False,
            "clip_start": 0.0,
            "clip_end": 20.0,              # time-range / clip
            "output_formats": WANT_FORMATS,
        }
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(cmd) + "\n")
        proc.stdin.flush()
        print(f"[e2e] sent transcribe: lang=en-US clip=0..20 formats={WANT_FORMATS}")

        lang = None
        pmax = 0
        for ev in _readline_json(proc, time.time() + 600):
            e = ev.get("event")
            if e == "language_detected":
                lang = ev.get("language")
            elif e == "progress":
                pmax = max(pmax, ev.get("percent", 0))
            elif e == "error":
                print(f"FAIL: worker error: {ev.get('message')}")
                return 1
            elif e == "done":
                print(f"[e2e] done (detected lang={lang}, progress_max={pmax})")
                break

        # Assert every requested format landed, non-empty.
        ok = True
        for ext in WANT_FORMATS:
            out = dst.with_suffix("." + ext)
            size = out.stat().st_size if out.exists() else -1
            status = "OK" if size > 0 else "MISSING/EMPTY"
            if size <= 0:
                ok = False
            print(f"  [{status}] {out.name}  ({size} bytes)")

        if not ok:
            print("FAIL: one or more output formats missing/empty")
            return 1
        # docx must be a real Office Open XML zip (PK magic), not a stub.
        docx = dst.with_suffix(".docx")
        with open(docx, "rb") as fh:
            magic = fh.read(2)
        if magic != b"PK":
            print(f"FAIL: docx is not a valid .docx (magic={magic!r})")
            return 1
        print("  [OK] docx has valid PK/zip magic")
        print("PASS: slim build past-bug e2e")
        return 0
    finally:
        try:
            if proc.stdin is None:
                raise RuntimeError("worker has no stdin pipe")
            proc.stdin.write(json.dumps({"action": "shutdown"}) + "\n")
            proc.stdin.flush()
            proc.wait(timeout=10)
        except Exception:
            proc.terminate()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
