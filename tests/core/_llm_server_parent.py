"""Stand-in app process for the orphan tests: starts a managed fake server and waits.

argv: <run dir> <log file> <fake server script> <model file>
Prints "child <pid>" once the server is ready, then sleeps until killed.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core import local_llm_server as lls  # noqa: E402


def main() -> None:
    run, log, script, model = (Path(a) for a in sys.argv[1:5])
    lls.run_dir = lambda: run  # keep records out of the real user cache
    lls._is_managed_exe = lambda exe: True  # the fake server runs on python
    server = lls.LocalLLMServer(
        lls.ServerOptions(model=model, peak_ram_mb=0, load_timeout_s=30),
        command=[sys.executable, str(script)],
        log_path=log,
    )
    server.start()
    print(f"child {server.pid}", flush=True)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
