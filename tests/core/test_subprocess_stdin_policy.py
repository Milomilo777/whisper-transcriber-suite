"""Every child process started by ``core/`` and ``app/`` says what its stdin is.

Why: the transcription worker (and the live and voice-clone workers) read their
commands from stdin, and a reader thread sits blocked on that pipe. A child
started WITHOUT a ``stdin`` argument inherits the pipe. On Windows an ffmpeg
that inherits it polls it for key presses and spun at the end of a slice until
its 600 s timeout, so every resume of a cancelled job stalled for ten minutes.
Other children (yt-dlp, deno, pip, demucs, ffprobe) can fail the same way, or
swallow commands meant for the worker. In a windowed Windows build or a Finder
launch the app's own stdin may not even be a valid handle.

The rule, checked with the AST: each ``subprocess.run`` / ``Popen`` /
``check_output`` / ``check_call`` / ``call`` (any import spelling) passes a
``stdin=`` or ``input=`` that really replaces the inherited pipe. These do not
count: ``stdin=None``, ``input=None``, ``stdin=0`` and ``stdin=sys.stdin`` all
inherit it. ``subprocess.getoutput`` / ``getstatusoutput``, ``os.system`` /
``popen`` / ``spawn*`` / ``exec*`` and ``asyncio.create_subprocess_*`` take no
usable stdin, so they are rejected outright.

``**kwargs`` is followed only when that is certain: a dict literal bound once, at
the top level of the same function, before the call; or a ``kwargs`` parameter
given ``kwargs.setdefault("stdin", ...)`` at the top level before the call. A
conditional, rebound or later-overwritten dict (``pop``, ``del``, a later
``**other``, ``stdin=None``) does not count.

Hidden calls are rejected too: a bare reference to ``subprocess.Popen`` (an alias,
a ``popen=subprocess.Popen`` default), ``getattr(subprocess, ...)``,
``import_module("subprocess")``, ``from subprocess import *`` and a bare ``subprocess``
name that is not a plain ``subprocess.<name>`` attribute. Type annotations are fine.
"""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCAN_DIRS = ("core", "app")

# (file relative to the repo root, enclosing function) -> why it is exempt.
# Keep this list short; every entry is re-checked below so it cannot go stale.
ALLOWED: dict[tuple[str, str], str] = {
    ("core/subtitle_edit.py", "open_in_subtitle_edit"): (
        "popen=subprocess.Popen is an injectable default (tests pass a fake); the "
        "function itself calls popen(..., stdin=subprocess.DEVNULL, ...)"
    ),
}

_SUBPROCESS_FUNCS = {"run", "Popen", "check_output", "check_call", "call"}
_SHELL_FUNCS = {"getoutput", "getstatusoutput"}  # no stdin parameter at all
_OS_PREFIXES = ("spawn", "exec", "posix_spawn")
_OS_NAMES = {"system", "popen"}
_STDIN_KEYS = {"stdin", "input"}
_ALL_FUNCS = _SUBPROCESS_FUNCS | _SHELL_FUNCS


def _is_os_func(attr: str) -> bool:
    return attr in _OS_NAMES or attr.startswith(_OS_PREFIXES)


def _parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}


def _enclosing_scope(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> ast.AST:
    cur = node
    while cur in parents:
        cur = parents[cur]
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.Module)):
            return cur
    return cur


def _scope_nodes(scope: ast.AST) -> list[ast.AST]:
    """Nodes of ``scope`` itself, not of the functions nested inside it."""
    out: list[ast.AST] = []
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        n = stack.pop()
        out.append(n)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        stack.extend(ast.iter_child_nodes(n))
    return out


def _param_names(scope: ast.AST) -> set[str]:
    if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        return set()
    a = scope.args
    names = {x.arg for x in [*a.posonlyargs, *a.args, *a.kwonlyargs]}
    for extra in (a.vararg, a.kwarg):
        if extra is not None:
            names.add(extra.arg)
    return names


def _real_stdin(value: ast.expr) -> bool:
    """True when ``value`` replaces the inherited stdin (not None, 0 or sys.stdin)."""
    if isinstance(value, ast.Constant):
        return not (value.value is None or (type(value.value) is int and value.value == 0))
    if isinstance(value, ast.Attribute) and value.attr in {"stdin", "__stdin__"}:
        return False
    return True


def _key_is_stdin(key: ast.expr | None) -> bool:
    return isinstance(key, ast.Constant) and key.value in _STDIN_KEYS


def _dominates(stmt: ast.stmt, call: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """True when ``stmt`` runs before ``call`` on every path to it: both sit in the same
    statement list, ``stmt`` earlier (the call may be nested inside a later sibling)."""
    parent = parents.get(stmt)
    if parent is None:
        return False
    siblings = None
    for field in ("body", "orelse", "finalbody", "handlers"):
        lst = getattr(parent, field, None)
        if isinstance(lst, list) and any(x is stmt for x in lst):
            siblings = lst
            break
    if siblings is None:
        return False
    pos = next(i for i, x in enumerate(siblings) if x is stmt)
    cur: ast.AST | None = call
    while cur is not None and cur is not parent:
        p = parents.get(cur)
        if p is parent:
            return any(x is cur for x in siblings[pos + 1:])
        cur = p
    return False


def _is_stdin_subscript(t: ast.expr, name: str) -> bool:
    return (
        isinstance(t, ast.Subscript) and _is_name(t.value, name)
        and isinstance(t.slice, ast.Constant) and t.slice.value in _STDIN_KEYS
    )


def _is_name(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def _name_provides(
    name: str, scope: ast.AST, call: ast.AST, parents: dict[ast.AST, ast.AST], depth: int = 0
) -> bool:
    """True when the dict ``name`` certainly holds a real stdin when ``call`` runs."""
    if depth > 4 or isinstance(scope, ast.Lambda):
        return False
    nodes = _scope_nodes(scope)
    stores = [n for n in nodes if isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, ast.Store)]
    primary: ast.stmt | None = None
    if name in _param_names(scope):
        if stores:  # rebound
            return False
    else:
        if len(stores) != 1:  # unbound here, or rebound
            return False
        for s in nodes:
            if isinstance(s, (ast.Assign, ast.AnnAssign)) and isinstance(s.value, ast.Dict):
                targets = s.targets if isinstance(s, ast.Assign) else [s.target]
                if len(targets) == 1 and targets[0] is stores[0] and _dominates(s, call, parents):
                    primary = s
        if primary is None:  # conditional, or after the call
            return False

    # Anything that can take the key away or weaken it disqualifies the dict.
    for n in nodes:
        if isinstance(n, ast.Subscript) and _is_name(n.value, name) and isinstance(n.ctx, ast.Del):
            if isinstance(n.slice, ast.Constant) and n.slice.value in _STDIN_KEYS:
                return False
        if isinstance(n, ast.Assign) and not _real_stdin(n.value):
            if any(_is_stdin_subscript(t, name) for t in n.targets):
                return False
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and _is_name(n.func.value, name):
            if n.func.attr in {"pop", "popitem", "clear"}:
                return False
            if n.func.attr == "update":
                for kw in n.keywords:
                    if kw.arg in _STDIN_KEYS and not _real_stdin(kw.value):
                        return False
                for arg in n.args:
                    if isinstance(arg, ast.Dict):
                        for k, v in zip(arg.keys, arg.values):
                            if _key_is_stdin(k) and not _real_stdin(v):
                                return False

    if isinstance(primary, (ast.Assign, ast.AnnAssign)) and isinstance(primary.value, ast.Dict):
        if _dict_provides(primary.value, scope, call, parents, depth + 1):
            return True
    for s in nodes:
        if isinstance(s, ast.Assign) and _real_stdin(s.value) and any(_is_stdin_subscript(t, name) for t in s.targets):
            if _dominates(s, call, parents):
                return True
        if (
            isinstance(s, ast.Expr) and isinstance(s.value, ast.Call)
            and isinstance(s.value.func, ast.Attribute) and _is_name(s.value.func.value, name)
            and s.value.func.attr == "setdefault" and len(s.value.args) == 2
            and isinstance(s.value.args[0], ast.Constant) and s.value.args[0].value in _STDIN_KEYS
            and _real_stdin(s.value.args[1]) and _dominates(s, call, parents)
        ):
            return True
    return False


def _dict_provides(
    d: ast.Dict, scope: ast.AST, call: ast.AST, parents: dict[ast.AST, ast.AST], depth: int = 0
) -> bool:
    """True when the dict literal ends up with a real stdin (a later ``**x`` can override it)."""
    ok = False
    for k, v in zip(d.keys, d.values):
        if k is None:  # **v
            ok = isinstance(v, ast.Name) and _name_provides(v.id, scope, call, parents, depth)
        elif _key_is_stdin(k):
            ok = _real_stdin(v)
    return ok


def _call_provides_stdin(call: ast.Call, scope: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    for kw in call.keywords:
        if kw.arg in _STDIN_KEYS:
            if _real_stdin(kw.value):
                return True
        elif kw.arg is None:  # **something
            v = kw.value
            if isinstance(v, ast.Dict) and _dict_provides(v, scope, call, parents):
                return True
            if isinstance(v, ast.Name) and _name_provides(v.id, scope, call, parents):
                return True
    return False


def _scope_name(scope: ast.AST) -> str:
    return "<lambda>" if isinstance(scope, ast.Lambda) else getattr(scope, "name", "<module>")


def _harmless_getattr(parent: ast.AST | None, module_name: ast.Name) -> bool:
    """``getattr(subprocess, "CREATE_NO_WINDOW", 0)``: a constant lookup of a name that
    is not one of the process-starting functions."""
    if not (isinstance(parent, ast.Call) and isinstance(parent.func, ast.Name) and parent.func.id == "getattr"):
        return False
    if len(parent.args) < 2 or parent.args[0] is not module_name:
        return False
    attr = parent.args[1]
    return isinstance(attr, ast.Constant) and isinstance(attr.value, str) and attr.value not in _ALL_FUNCS


def _annotation_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for n in ast.walk(tree):
        ann = None
        if isinstance(n, ast.arg):
            ann = n.annotation
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            ann = n.returns
        elif isinstance(n, ast.AnnAssign):
            ann = n.annotation
        if ann is not None:
            ids.update(id(x) for x in ast.walk(ann))
    return ids


def find_calls_without_stdin(source: str) -> list[tuple[int, str, str]]:
    """Return ``(line, what, enclosing function)`` for each child-process call or
    hidden reference in ``source`` that does not name a real stdin."""
    tree = ast.parse(source)
    parents = _parent_map(tree)
    annotations = _annotation_nodes(tree)
    sub_mods: set[str] = set()
    os_mods: set[str] = set()
    asyncio_mods: set[str] = set()
    direct: dict[str, str] = {}
    found: list[tuple[int, str, str]] = []

    def add(node: ast.AST, what: str) -> None:
        found.append((node.lineno, what, _scope_name(_enclosing_scope(node, parents))))  # type: ignore[attr-defined]

    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                bound = a.asname or a.name.split(".")[0]
                if a.name == "subprocess":
                    sub_mods.add(bound)
                elif a.name == "os":
                    os_mods.add(bound)
                elif a.name == "asyncio":
                    asyncio_mods.add(bound)
        elif isinstance(n, ast.ImportFrom):
            for a in n.names:
                if n.module == "subprocess":
                    if a.name == "*":
                        add(n, "from subprocess import *")
                    elif a.name in _ALL_FUNCS:
                        direct[a.asname or a.name] = a.name
                elif n.module == "os" and (a.name == "*" or _is_os_func(a.name)):
                    if a.name == "*":
                        add(n, "from os import *")
                    else:
                        direct[a.asname or a.name] = "os." + a.name
                elif n.module == "asyncio" and (a.name == "*" or a.name.startswith("create_subprocess_")):
                    if a.name == "*":
                        add(n, "from asyncio import *")
                    else:
                        direct[a.asname or a.name] = "asyncio." + a.name

    for n in ast.walk(tree):
        parent = parents.get(n)
        in_call_position = isinstance(parent, ast.Call) and parent.func is n
        if isinstance(n, ast.Call):
            f = n.func
            callee = None
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
                if f.value.id in sub_mods and f.attr in _ALL_FUNCS:
                    callee = f"subprocess.{f.attr}"
                elif f.value.id in os_mods and _is_os_func(f.attr):
                    callee = f"os.{f.attr}"
                elif f.value.id in asyncio_mods and f.attr.startswith("create_subprocess_"):
                    callee = f"asyncio.{f.attr}"
            elif isinstance(f, ast.Name) and f.id in direct:
                callee = direct[f.id]
            if callee is not None:
                if callee.startswith("os."):
                    add(n, callee)  # never takes a usable stdin
                elif callee.split(".")[-1] in _SHELL_FUNCS:
                    add(n, callee)
                elif not _call_provides_stdin(n, _enclosing_scope(n, parents), parents):
                    add(n, callee)
            # importlib.import_module("subprocess") / __import__("subprocess")
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            if name in {"__import__", "import_module"} and n.args:
                a0 = n.args[0]
                if isinstance(a0, ast.Constant) and isinstance(a0.value, str) and a0.value.split(".")[0] == "subprocess":
                    add(n, f"{name}('subprocess')")
        elif isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
            if n.value.id in sub_mods and n.attr in _ALL_FUNCS and not in_call_position and id(n) not in annotations:
                add(n, f"subprocess.{n.attr} (reference, not a call)")
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and id(n) not in annotations:
            if n.id in sub_mods and not (isinstance(parent, ast.Attribute) and parent.value is n):
                if not _harmless_getattr(parent, n):
                    add(n, "subprocess (module used as a value)")
            elif n.id in direct and not in_call_position:
                add(n, f"{direct[n.id]} (reference, not a call)")
    return sorted(set(found))


def _scan_repo() -> list[tuple[str, int, str, str]]:
    out: list[tuple[str, int, str, str]] = []
    for d in SCAN_DIRS:
        for path in sorted((ROOT / d).rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            for line, what, func in find_calls_without_stdin(path.read_text(encoding="utf-8")):
                out.append((rel, line, what, func))
    return out


def test_every_child_process_call_names_its_stdin():
    offenders = [
        f"{rel}:{line} {what} in {func}()"
        for rel, line, what, func in _scan_repo()
        if (rel, func) not in ALLOWED
    ]
    assert not offenders, (
        "These calls start a child process without a real stdin, so the child "
        "inherits the worker's command pipe (pass stdin=subprocess.DEVNULL, or "
        "PIPE/input= when the child is fed):\n  " + "\n  ".join(offenders)
    )


def test_allow_list_has_no_stale_entries():
    hit = {(rel, func) for rel, _line, _what, func in _scan_repo()}
    stale = sorted(set(ALLOWED) - hit)
    assert not stale, f"ALLOWED entries that no longer match a flagged spot: {stale}"


# ----------------------------------------------------------- the checker itself
# Controls: it must flag the known-bad shapes and pass the known-good ones.

def _s(text: str) -> str:
    return textwrap.dedent(text).lstrip("\n")


_BAD = {
    "plain run": _s("""
        import subprocess
        def f():
            subprocess.run(['x'])
    """),
    "popen no stdin": _s("""
        import subprocess
        def f():
            subprocess.Popen(['x'], stdout=subprocess.PIPE)
    """),
    "alias import": _s("""
        import subprocess as sp
        def f():
            sp.check_output(['x'])
    """),
    "from import": _s("""
        from subprocess import run as r
        def f():
            r(['x'])
    """),
    "capture_output only": _s("""
        import subprocess
        def f():
            subprocess.run(['x'], capture_output=True)
    """),
    "os.system": _s("""
        import os
        def f():
            os.system('x')
    """),
    "os.execv": _s("""
        import os
        def f():
            os.execv('x', ['x'])
    """),
    "os.spawnl": _s("""
        import os
        def f():
            os.spawnl(os.P_WAIT, 'x', 'x')
    """),
    "getoutput": _s("""
        import subprocess
        def f():
            return subprocess.getoutput('x')
    """),
    "getstatusoutput": _s("""
        import subprocess
        def f():
            return subprocess.getstatusoutput('x')
    """),
    "stdin=None": _s("""
        import subprocess
        def f():
            subprocess.run(['x'], stdin=None)
    """),
    "input=None": _s("""
        import subprocess
        def f():
            subprocess.run(['x'], input=None)
    """),
    "stdin=sys.stdin": _s("""
        import subprocess, sys
        def f():
            subprocess.run(['x'], stdin=sys.stdin)
    """),
    "stdin=0": _s("""
        import subprocess
        def f():
            subprocess.Popen(['x'], stdin=0)
    """),
    "alias of Popen": _s("""
        import subprocess
        P = subprocess.Popen
        def f():
            P(['x'])
    """),
    "Popen as a default argument": _s("""
        import subprocess
        def f(popen=subprocess.Popen):
            popen(['x'])
    """),
    "getattr(subprocess, 'run')": _s("""
        import subprocess
        def f():
            getattr(subprocess, 'run')(['x'])
    """),
    "star import": _s("""
        from subprocess import *
        def f():
            run(['x'])
    """),
    "module used as a value": _s("""
        import subprocess
        sp = subprocess
        def f():
            sp.run(['x'])
    """),
    "reference to a from-imported name": _s("""
        from subprocess import Popen
        runner = Popen
        def f():
            runner(['x'])
    """),
    "getattr with a computed name": _s("""
        import subprocess
        def f(n):
            getattr(subprocess, n)(['x'])
    """),
    "dict built in a try, call after it": _s("""
        import subprocess
        def f():
            try:
                kw = {'stdin': subprocess.DEVNULL}
            except OSError:
                kw = {}
            subprocess.run(['x'], **kw)
    """),
    "import_module": _s("""
        import importlib
        def f():
            importlib.import_module('subprocess').run(['x'])
    """),
    "kwargs dict without stdin": _s("""
        import subprocess
        def f():
            kw = {'stdout': subprocess.PIPE}
            subprocess.run(['x'], **kw)
    """),
    "kwargs from a parameter": _s("""
        import subprocess
        def f(**kw):
            subprocess.run(['x'], **kw)
    """),
    "stdin in another function": _s("""
        import subprocess
        def g():
            kw = {'stdin': subprocess.DEVNULL}
            return kw
        def f():
            kw = {}
            subprocess.run(['x'], **kw)
    """),
    "kwargs dict with stdin=None": _s("""
        import subprocess
        def f():
            kw = {'stdin': None}
            subprocess.run(['x'], **kw)
    """),
    "conditional dict": _s("""
        import subprocess
        def f(c):
            if c:
                kw = {'stdin': subprocess.DEVNULL}
            else:
                kw = {}
            subprocess.run(['x'], **kw)
    """),
    "dict rebound afterwards": _s("""
        import subprocess
        def f():
            kw = {'stdin': subprocess.DEVNULL}
            kw = {'timeout': 5}
            subprocess.run(['x'], **kw)
    """),
    "dict built after the call": _s("""
        import subprocess
        def f(kw):
            subprocess.run(['x'], **kw)
            kw = {'stdin': subprocess.DEVNULL}
    """),
    "stdin set only in a branch": _s("""
        import subprocess
        def f(c):
            kw = {}
            if c:
                kw['stdin'] = subprocess.DEVNULL
            subprocess.run(['x'], **kw)
    """),
    "stdin overwritten with None": _s("""
        import subprocess
        def f(c):
            kw = {'stdin': subprocess.DEVNULL}
            if c:
                kw['stdin'] = None
            subprocess.run(['x'], **kw)
    """),
    "stdin popped": _s("""
        import subprocess
        def f(c):
            kw = {'stdin': subprocess.DEVNULL}
            if c:
                kw.pop('stdin')
            subprocess.run(['x'], **kw)
    """),
    "stdin deleted": _s("""
        import subprocess
        def f():
            kw = {'stdin': subprocess.DEVNULL}
            del kw['stdin']
            subprocess.run(['x'], **kw)
    """),
    "update with stdin=None": _s("""
        import subprocess
        def f():
            kw = {'stdin': subprocess.DEVNULL}
            kw.update(stdin=None)
            subprocess.run(['x'], **kw)
    """),
    "update with a dict holding None": _s("""
        import subprocess
        def f():
            kw = {'stdin': subprocess.DEVNULL}
            kw.update({'stdin': None})
            subprocess.run(['x'], **kw)
    """),
    "later ** can override stdin": _s("""
        import subprocess
        def f(k):
            subprocess.run(['x'], **{'stdin': subprocess.DEVNULL, **k})
    """),
    "setdefault only in a branch": _s("""
        import subprocess
        def f(c, **kw):
            if c:
                kw.setdefault('stdin', subprocess.DEVNULL)
            subprocess.run(['x'], **kw)
    """),
    "setdefault with None": _s("""
        import subprocess
        def f(**kw):
            kw.setdefault('stdin', None)
            subprocess.run(['x'], **kw)
    """),
    "setdefault after the call": _s("""
        import subprocess
        def f(**kw):
            subprocess.run(['x'], **kw)
            kw.setdefault('stdin', subprocess.DEVNULL)
    """),
}
_GOOD = {
    "stdin keyword": _s("""
        import subprocess
        def f():
            subprocess.run(['x'], stdin=subprocess.DEVNULL)
    """),
    "input keyword": _s("""
        import subprocess
        def f():
            subprocess.run(['x'], input=b'y')
    """),
    "stdin pipe": _s("""
        import subprocess
        def f():
            subprocess.Popen(['x'], stdin=subprocess.PIPE)
    """),
    "kwargs dict with stdin": _s("""
        import subprocess
        def f():
            kw: dict = {'stdin': subprocess.DEVNULL}
            subprocess.run(['x'], **kw)
    """),
    "kwargs dict then update from a helper": _s("""
        import subprocess
        def f(extra):
            kw = {'stdin': subprocess.DEVNULL}
            kw.update(extra())
            subprocess.run(['x'], **kw)
    """),
    "kwargs subscript at the top level": _s("""
        import subprocess
        def f():
            kw = {}
            kw['stdin'] = subprocess.DEVNULL
            subprocess.run(['x'], **kw)
    """),
    "stdin first, ** before it": _s("""
        import subprocess
        def f(k):
            subprocess.run(['x'], **{**k, 'stdin': subprocess.DEVNULL})
    """),
    "setdefault on a kwargs parameter": _s("""
        import subprocess
        def f(**kw):
            kw.setdefault('stdin', subprocess.DEVNULL)
            subprocess.run(['x'], **kw)
    """),
    "setdefault and an inline merge": _s("""
        import subprocess
        def f(helper, **kw):
            kw.setdefault('stdin', subprocess.DEVNULL)
            subprocess.Popen(['x'], **{**helper(), **kw})
    """),
    "module-level call": _s("""
        import subprocess
        kw = {'stdin': subprocess.DEVNULL}
        subprocess.run(['x'], **kw)
    """),
    "from import with stdin": _s("""
        from subprocess import run
        def f():
            run(['x'], stdin=-3)
    """),
    "getattr of a constant": _s("""
        import subprocess
        def f():
            return getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    """),
    "dict and call in the same try": _s("""
        import subprocess
        def f(c):
            try:
                kw = {'stdin': subprocess.DEVNULL}
                if c:
                    kw['creationflags'] = 1
                subprocess.run(['x'], **kw)
            except OSError:
                pass
    """),
    "type annotations only": _s("""
        import subprocess
        from typing import Optional
        class A:
            p: Optional[subprocess.Popen[str]] = None
            def stop(self, proc: subprocess.Popen[str]) -> subprocess.Popen[str]:
                return proc
    """),
    "unrelated run": _s("""
        def f(o):
            o.run(['x'])
    """),
    "other subprocess names": _s("""
        import subprocess
        def f():
            try:
                subprocess.run(['x'], stdin=subprocess.DEVNULL)
            except subprocess.TimeoutExpired:
                return subprocess.PIPE
    """),
}


@pytest.mark.parametrize("name", sorted(_BAD))
def test_checker_flags_known_bad_shapes(name):
    assert find_calls_without_stdin(_BAD[name]), name


@pytest.mark.parametrize("name", sorted(_GOOD))
def test_checker_passes_known_good_shapes(name):
    assert find_calls_without_stdin(_GOOD[name]) == [], name


def test_run_killing_tree_defaults_stdin_to_devnull_and_honours_the_caller(monkeypatch):
    from core import yt_dlp_update as ydu

    seen: list[dict] = []

    class _Proc:
        returncode = 0

        def __init__(self, cmd, **kwargs):
            seen.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def communicate(self, timeout=None):
            return ("", "")

    monkeypatch.setattr(ydu.subprocess, "Popen", _Proc)
    ydu.run_killing_tree(["x"], timeout=5)
    ydu.run_killing_tree(["x"], timeout=5, stdin=ydu.subprocess.PIPE)
    assert seen[0]["stdin"] is ydu.subprocess.DEVNULL
    assert seen[1]["stdin"] is ydu.subprocess.PIPE
