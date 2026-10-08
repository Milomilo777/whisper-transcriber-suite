"""The transcription worker's log output: UTF-8 on the pipe, no per-chunk repeats."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from core import worker

REPO = Path(__file__).resolve().parents[2]

_CHILD = (
    "import sys\n"
    "from core.worker import _utf8_stdio\n"
    "if sys.argv[1] == 'fix':\n"
    "    _utf8_stdio()\n"
    "sys.stderr.write('faster_whisper \\u2014 caf\\u00e9\\n')\n"
    "sys.stderr.flush()\n"
    "sys.stderr.write('\\u0633\\u0644\\u0627\\u0645\\n')\n"
    "sys.stderr.flush()\n"
)


def _child_stderr(mode: str) -> str:
    """Run a child the way both parents do: stderr piped, decoded as UTF-8."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    env["PYTHONUTF8"] = "0"  # the default on Windows; never inherited here
    out = subprocess.run(
        [sys.executable, "-c", _CHILD, mode], cwd=str(REPO), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace", timeout=60,
    )
    return out.stdout


def test_worker_log_lines_reach_the_parent_as_utf8():
    text = _child_stderr("fix")
    # Em dash, accented Latin and Persian letters all survive the pipe.
    assert "faster_whisper \u2014 caf\u00e9" in text
    assert "\u0633\u0644\u0627\u0645" in text
    assert "\ufffd" not in text


def test_without_the_fix_a_windows_child_garbles_the_dash():
    """Negative control: proves the test above can fail on this platform."""
    if sys.platform != "win32":
        return  # POSIX locales are UTF-8 already; nothing to garble
    text = _child_stderr("raw")
    # The cp1252 dash byte 0x97 is not UTF-8: the parent sees U+FFFD.
    assert "faster_whisper \ufffd" in text


def _record(message: str, name: str = "faster_whisper") -> logging.LogRecord:
    return logging.LogRecord(name, logging.WARNING, __file__, 1, message, None, None)


def test_english_only_warning_passes_once():
    flt = worker._OnceFilter(worker._ENGLISH_ONLY_WARNING)
    warning = ("The current model is English-only but the language parameter "
               "is set to 'fa'; using 'en' instead.")
    assert flt.filter(_record(warning)) is True
    assert flt.filter(_record(warning)) is False
    assert flt.filter(_record(warning.replace("'fa'", "'de'"))) is False
    # Every other message keeps flowing, repeats included.
    assert flt.filter(_record("Processing audio")) is True
    assert flt.filter(_record("Processing audio")) is True


def test_filter_is_installed_once_on_the_faster_whisper_logger():
    target = logging.getLogger("faster_whisper")
    before = list(target.filters)
    try:
        worker._install_log_filters()
        worker._install_log_filters()
        added = [f for f in target.filters if isinstance(f, worker._OnceFilter)]
        assert len(added) == 1
    finally:
        target.filters[:] = before
