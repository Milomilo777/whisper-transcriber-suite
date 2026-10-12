"""tools/i18n_extract.py: what it collects, what it refuses, and its command-line modes."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "i18n_extract.py"
_spec = importlib.util.spec_from_file_location("i18n_extract", SCRIPT)
assert _spec and _spec.loader
ex = importlib.util.module_from_spec(_spec)
sys.modules["i18n_extract"] = ex
_spec.loader.exec_module(ex)


def _scan(source: str) -> "ex.Result":
    out = ex.Result()
    ex.scan_source(source, "app/x.py", out)
    return out


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=120)


def test_collects_every_marker_form() -> None:
    res = _scan(
        "from app.i18n import _, N_, lazy, ngettext, pgettext, translate\n"
        "from app import i18n\n"
        "A = N_('Module constant')\n"
        "def f(n, name):\n"
        "    _('Plain')\n"
        "    _('Implicit ' 'concatenation {name}', name=name)\n"
        "    ngettext('{n} file', '{n} files', n)\n"
        "    pgettext('menu', 'Open')\n"
        "    lazy('Tooltip')\n"
        "    i18n._('Through the module')\n"
        "    translate(A)\n"
        "    translate('Literal through translate')\n")
    assert res.errors == []
    assert res.messages == {
        "Module constant": "Module constant", "Plain": "Plain",
        "Implicit concatenation {name}": "Implicit concatenation {name}",
        "{n} file": ["{n} file", "{n} files"], "menu\x04Open": "Open", "Tooltip": "Tooltip",
        "Through the module": "Through the module",
        "Literal through translate": "Literal through translate"}


@pytest.mark.parametrize("call,needle", [
    ("_(f'Hi {x}')", "f-string"),
    ("_(msg)", "not a string literal"),
    ("_('Hi %s' % x)", "% or +"),
    ("_('Hi ' + x)", "% or +"),
    ("ngettext('{n} a', plural, n)", "not a string literal"),
    ("pgettext(ctx, 'Open')", "not a string literal"),
    ("lazy(x)", "not a string literal"),
    ("_()", "positional string literal"),
    ("_('Hi {}', x=1)", "positional placeholder"),
    ("_('Hi {0}', x=1)", "positional placeholder"),
    ("_('Hi {name}', other=1)", "name="),
    ("translate(f'Hi {x}')", "f-string"),
    ("translate('a {x}'.format(x=1))", "a call result"),
])
def test_refuses_non_literal_or_badly_formatted_messages(call: str, needle: str) -> None:
    res = _scan(f"def f(x, msg, plural, n, ctx):\n    {call}\n")
    assert res.errors, call
    assert "app/x.py:2" in res.errors[0]
    assert needle in res.errors[0]


def test_kwargs_splat_and_no_kwargs_are_accepted() -> None:
    res = _scan("def f(kw):\n    _('Use {title} literally')\n    _('Hi {name}', **kw)\n")
    assert res.errors == []


@pytest.mark.parametrize("body", [
    "for _ in range(3):\n        pass\n    _('Hi')",
    "a, _ = (1, 2)\n    _('Hi')",
    "with open('x') as _:\n        pass\n    _('Hi')",
    "_ = 3\n    return _('Hi')",
    "try:\n        pass\n    except Exception as _:\n        pass\n    _('Hi')",
    "for _ in range(3):\n        pass\n    return lambda: _('Hi')",
])
def test_refuses_a_function_that_assigns_underscore_and_calls_it(body: str) -> None:
    res = _scan(f"from app.i18n import _\ndef f():\n    {body}\n")
    assert any("assigns the name _" in e for e in res.errors), res.errors


def test_underscore_in_a_comprehension_or_other_function_is_fine() -> None:
    res = _scan("from app.i18n import _\n"
                "def f():\n    xs = [1 for _ in range(3)]\n    return _('Hi')\n"
                "def g():\n    for _ in range(2):\n        pass\n")
    assert res.errors == []


def test_refuses_module_level_rebinding_after_import() -> None:
    res = _scan("from app.i18n import _\nfor _ in range(2):\n    pass\nX = _('Hi')\n")
    assert any("rebinds _" in e for e in res.errors)


def test_conflicting_uses_of_one_message() -> None:
    res = _scan("def f(n):\n    _('{n} file')\n    ngettext('{n} file', '{n} files', n)\n")
    assert any("conflicts" in e for e in res.errors)


def test_the_real_app_has_no_errors_and_ignores_the_layer_itself() -> None:
    res = ex.extract(ROOT)
    assert res.errors == []
    assert ROOT / "app" / "i18n.py" not in ex.source_files(ROOT)
    assert ROOT / "gui.py" in ex.source_files(ROOT)


def _tree(tmp_path: Path, source: str) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text(source, encoding="utf-8")
    return tmp_path


def test_writes_deterministic_sorted_lf_catalog(tmp_path: Path) -> None:
    root = _tree(tmp_path, "from app.i18n import _, pgettext\n_('b')\n_('a')\n_('Sending…')\n"
                           "pgettext('menu', 'Open')\n")
    assert _run("--root", str(root)).returncode == 0
    data = (root / "app" / "locales" / "en.json").read_bytes()
    assert b"\r" not in data and data.endswith(b"}\n")
    assert "Sending…".encode() in data
    assert b"menu\\u0004Open" in data  # the context separator is written as an escape
    doc = json.loads(data)
    assert list(doc["messages"]) == sorted(doc["messages"])
    assert doc["_meta"] == {"code": "en", "direction": "ltr", "name": "English",
                            "plural": "one_other", "status": "source"}
    assert _run("--root", str(root)).returncode == 0
    assert (root / "app" / "locales" / "en.json").read_bytes() == data
    assert _run("--root", str(root), "--check").returncode == 0


def test_check_fails_on_stale_catalog_and_on_errors(tmp_path: Path) -> None:
    root = _tree(tmp_path, "from app.i18n import _\n_('a')\n")
    assert _run("--root", str(root), "--check").returncode == 1  # no en.json yet
    assert _run("--root", str(root)).returncode == 0
    (root / "app" / "m.py").write_text("from app.i18n import _\n_('a')\n_('new')\n", encoding="utf-8")
    res = _run("--root", str(root), "--check")
    assert res.returncode == 1 and "stale" in res.stderr
    (root / "app" / "m.py").write_text("from app.i18n import _\n_(f'{1}')\n", encoding="utf-8")
    res = _run("--root", str(root))
    assert res.returncode == 1 and "app/m.py:2" in res.stderr


def test_missing_lists_untranslated_messages(tmp_path: Path) -> None:
    root = _tree(tmp_path, "from app.i18n import _\n_('a')\n_('b')\n_('c')\n")
    (root / "app" / "locales").mkdir()
    (root / "app" / "locales" / "de.json").write_text(
        json.dumps({"_meta": {"code": "de"}, "messages": {"a": "A", "b": ""}}), encoding="utf-8")
    res = _run("--root", str(root), "--missing", "de")
    assert res.returncode == 0
    assert res.stdout.split() == ["b", "c"]


def test_find_unwrapped_reports_literal_interface_text(tmp_path: Path) -> None:
    f = tmp_path / "d.py"
    f.write_text(
        "from app.i18n import _\n"
        "ttk.Label(p, text='Hello')\n"
        "ttk.Label(p, text=_('Wrapped'))\n"
        "messagebox.showerror('Title', 'Body')\n"
        "dlg.title('Window')\n"
        "var.set('Busy')\n"
        "var.set('')\n"
        "show_error(f'Failed {x}')\n"
        "ttk.Label(p, text='0 / 5')\n", encoding="utf-8")
    res = _run("--find-unwrapped", str(f))
    assert res.returncode == 0
    found = sorted(ln.rsplit(": ", 1)[-1] for ln in res.stdout.splitlines() if ln)
    assert found == sorted(["'Hello'", "'Title'", "'Body'", "'Window'", "'Busy'", "f-string"])
