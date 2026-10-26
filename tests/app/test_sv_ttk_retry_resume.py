"""A retried sv_ttk load after a half-done load must not create the light theme twice.

CI flake (Windows 3.11): ``sv.tcl`` sources ``theme/light.tcl`` (creates ``sun-valley-light``), the
transient Tcl read fault then hits ``theme/dark.tcl``, and the test helper's retry sourced
``sv.tcl`` again -> ``TclError: Theme sun-valley-light already exists``. The fault is injected here
deterministically by making Tcl's ``source`` fail once on ``dark.tcl``.
"""
from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

import sv_ttk  # noqa: E402

_FAIL_ONCE_ON_DARK = r"""
set ::wts_dark_failed 0
rename source ::wts_real_source
proc source {args} {
    set file [lindex $args end]
    if {!$::wts_dark_failed && [string match */theme/dark.tcl $file]} {
        set ::wts_dark_failed 1
        error "couldn't read file \"$file\": No error"
    }
    uplevel 1 [linsert $args 0 ::wts_real_source]
}
"""


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError as e:  # pragma: no cover - no display
        pytest.skip(f"no Tk display: {e}")
    r.withdraw()
    yield r
    r.destroy()


def test_retry_after_a_read_fault_on_dark_tcl_loads_both_themes(root) -> None:
    root.tk.eval(_FAIL_ONCE_ON_DARK)
    assert not hasattr(root, "_sv_ttk_loaded")
    sv_ttk.set_theme("light")  # the conftest wraps _load_theme with the bounded retry
    assert root.tk.call("set", "::wts_dark_failed") == 1  # the fault really fired
    style = ttk.Style(root)
    assert {"sun-valley-light", "sun-valley-dark"} <= set(style.theme_names())
    assert style.theme_use() == "sun-valley-light"
    sv_ttk.set_theme("dark")  # the theme that was skipped by the fault is usable
    assert style.theme_use() == "sun-valley-dark"
    assert root.tk.call("font", "names")  # fonts were created exactly once
