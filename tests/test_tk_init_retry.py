"""The test-suite helper that retries the transient Tcl ``init.tcl`` start-up fault."""
from __future__ import annotations

import tkinter

import pytest

from tests import tk_init_retry as r

_INIT_TCL_MSG = (
    "Can't find a usable init.tcl in the following directories: \n"
    "    C:/Python314/tcl/tcl8.6\n\n"
    'C:/Python314/tcl/tcl8.6/init.tcl: couldn\'t read file "x": No error'
)


@pytest.fixture(autouse=True)
def _clean_retries():
    # A real retry earlier in the run may already be recorded; count from empty here, then put the
    # suite-wide list back so these tests neither see nor add to it.
    before = list(r.retries)
    r.retries.clear()
    yield
    r.retries[:] = before


def _flaky(failures: int, message: str = _INIT_TCL_MSG):
    calls = {"n": 0}

    def original(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] <= failures:
            raise tkinter.TclError(message)
        return "ok"

    return r.wrap_init(original), calls


def test_retries_init_tcl_error_then_succeeds(capsys):
    wrapped, calls = _flaky(failures=2)
    assert wrapped(object()) == "ok"
    assert calls["n"] == 3
    assert len(r.retries) == 2
    assert capsys.readouterr().err.count("[tk-init-retry]") == 2


@pytest.mark.parametrize(
    "message",
    [
        "Can't find a usable tk.tcl in the following directories: \n    C:/Python314/tcl/tk8.6",
        'invalid command name "tcl_findLibrary"',
    ],
)
def test_retries_the_other_spellings_of_the_same_fault(message):
    wrapped, calls = _flaky(failures=1, message=message)
    assert wrapped(object()) == "ok"
    assert calls["n"] == 2
    assert len(r.retries) == 1


def test_unrelated_invalid_command_name_is_not_retried():
    wrapped, calls = _flaky(failures=99, message='invalid command name ".!frame.!button"')
    with pytest.raises(tkinter.TclError, match="invalid command"):
        wrapped(object())
    assert calls["n"] == 1
    assert r.retries == []


def test_gives_up_after_max_tries_with_the_original_error():
    wrapped, calls = _flaky(failures=99)
    with pytest.raises(tkinter.TclError, match="init.tcl"):
        wrapped(object())
    assert calls["n"] == r.MAX_TRIES


def test_other_tcl_errors_are_not_retried():
    wrapped, calls = _flaky(failures=99, message="no display name and no $DISPLAY")
    with pytest.raises(tkinter.TclError, match="no display"):
        wrapped(object())
    assert calls["n"] == 1
    assert r.retries == []


def test_non_tcl_errors_are_not_retried():
    calls = {"n": 0}

    def original(self):
        calls["n"] += 1
        raise ValueError("init.tcl")

    with pytest.raises(ValueError):
        r.wrap_init(original)(object())
    assert calls["n"] == 1


def test_conftest_wraps_the_real_tk_class():
    assert hasattr(tkinter.Tk.__init__, "__wrapped__")
