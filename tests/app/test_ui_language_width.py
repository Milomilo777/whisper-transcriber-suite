"""The language chooser list is wide enough for its longest name (Tk; skips without a display)."""
from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter")

from app.dialogs import ui_language  # noqa: E402


@pytest.fixture
def box():
    try:
        root = tk.Tk()
    except tk.TclError:  # pragma: no cover - headless
        pytest.skip("no Tk display available")
    root.withdraw()
    widget = tk.Listbox(root, width=36)
    widget.pack()
    root.update()
    yield widget
    root.destroy()


def test_short_names_keep_the_old_width(box) -> None:
    assert ui_language.fitted_width(box, ["     English", "     Deutsch"]) == 36


def test_a_long_name_widens_the_list(box) -> None:
    long_name = "     " + "Ꭰ" * 60
    width = ui_language.fitted_width(box, ["     English", long_name])
    assert width > 36


def test_the_width_is_capped(box) -> None:
    assert ui_language.fitted_width(box, ["x" * 500]) == 64
