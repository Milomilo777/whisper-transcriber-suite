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
``check_output`` / ``check_call`` / ``call`` (any import spelling), ``os.system``,
``os.popen`` and ``asyncio.create_subprocess_*`` call passes ``stdin=`` or
``input=``, directly or through a ``**kwargs`` dict built in the same function.
A child that never needs input gets ``stdin=subprocess.DEVNULL``; a child that is
fed gets ``subprocess.PIPE`` (or ``input=``).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCAN_DIRS = ("core", "app")

# (file relative to the repo root, enclosing function) -> why it is exempt.
# Keep this list short; every entry is re-checked below so it cannot go stale.
ALLOWED: dict[tuple[str, str], str] = {
    ("core/yt_dlp_update.py", "run_killing_tree"): (
        "forwards the caller's **kwargs to Popen; its only caller (_update) always "
        "passes stdin=DEVNULL, and the tests of update_cached_copy exercise that path"
    ),
}

_SUBPROCESS_FUNCS = {"run", "Popen", "check_output", "check_call", "call"}
_OS_FUNCS = {"system", "popen"}
_STDIN_KEYS = {"stdin", "input"}


def _parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}


def _enclosing_scope(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> ast.AST:
    cur = node
    while cur in parents:
        cur = parents[cur]
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.Module)):
            return cur
    return cur


def _dict_has_stdin(d: ast.Dict) -> bool:
    return any(isinstance(k, ast.Constant) and k.value in _STDIN_KEYS for k in d.keys)


def _name_provides_stdin(name: str, scope: ast.AST) -> bool:
    """True when ``name`` is a dict built in ``scope`` that holds a stdin/input key."""
    for n in ast.walk(scope):
        if isinstance(n, (ast.Assign, ast.AnnAssign)):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            value = n.value
            for t in targets:
                if isinstance(t, ast.Name) and t.id == name and isinstance(value, ast.Dict):
                    if _dict_has_stdin(value):
                        return True
                # kwargs["stdin"] = ...
                if (
                    isinstance(t, ast.Subscript)
                    and isinstance(t.value, ast.Name)
                    and t.value.id == name
                    and isinstance(t.slice, ast.Constant)
                    and t.slice.value in _STDIN_KEYS
                ):
                    return True
    return False


def _call_provides_stdin(call: ast.Call, scope: ast.AST) -> bool:
    for kw in call.keywords:
        if kw.arg in _STDIN_KEYS:
            return True
        if kw.arg is None:  # **something
            v = kw.value
            if isinstance(v, ast.Dict) and _dict_has_stdin(v):
                return True
            if isinstance(v, ast.Name) and _name_provides_stdin(v.id, scope):
                return True
    return False


def _scope_name(scope: ast.AST) -> str:
    return getattr(scope, "name", "<module>") if not isinstance(scope, ast.Lambda) else "<lambda>"


def find_calls_without_stdin(source: str) -> list[tuple[int, str, str]]:
    """Return ``(line, callee, enclosing function)`` for each child-process call
    in ``source`` that does not name its stdin."""
    tree = ast.parse(source)
    parents = _parent_map(tree)
    sub_mods: set[str] = set()
    os_mods: set[str] = set()
    asyncio_mods: set[str] = set()
    direct: dict[str, str] = {}
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
        elif isinstance(n, ast.ImportFrom) and n.module == "subprocess":
            for a in n.names:
                if a.name in _SUBPROCESS_FUNCS:
                    direct[a.asname or a.name] = a.name
        elif isinstance(n, ast.ImportFrom) and n.module == "os":
            for a in n.names:
                if a.name in _OS_FUNCS:
                    direct[a.asname or a.name] = "os." + a.name
        elif isinstance(n, ast.ImportFrom) and n.module == "asyncio":
            for a in n.names:
                if a.name.startswith("create_subprocess_"):
                    direct[a.asname or a.name] = "asyncio." + a.name

    found: list[tuple[int, str, str]] = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        callee = None
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            if f.value.id in sub_mods and f.attr in _SUBPROCESS_FUNCS:
                callee = f"subprocess.{f.attr}"
            elif f.value.id in os_mods and f.attr in _OS_FUNCS:
                callee = f"os.{f.attr}"  # takes no stdin argument at all
            elif f.value.id in asyncio_mods and f.attr.startswith("create_subprocess_"):
                callee = f"asyncio.{f.attr}"
        elif isinstance(f, ast.Name) and f.id in direct:
            callee = direct[f.id]
        if callee is None:
            continue
        scope = _enclosing_scope(n, parents)
        if callee.startswith("os."):
            found.append((n.lineno, callee, _scope_name(scope)))
        elif not _call_provides_stdin(n, scope):
            found.append((n.lineno, callee, _scope_name(scope)))
    return sorted(found)


def _scan_repo() -> list[tuple[str, int, str, str]]:
    out: list[tuple[str, int, str, str]] = []
    for d in SCAN_DIRS:
        for path in sorted((ROOT / d).rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            for line, callee, func in find_calls_without_stdin(path.read_text(encoding="utf-8")):
                out.append((rel, line, callee, func))
    return out


def test_every_child_process_call_names_its_stdin():
    offenders = [
        f"{rel}:{line} {callee} in {func}()"
        for rel, line, callee, func in _scan_repo()
        if (rel, func) not in ALLOWED
    ]
    assert not offenders, (
        "These calls start a child process without naming its stdin, so the child "
        "inherits the worker's command pipe (pass stdin=subprocess.DEVNULL, or "
        "PIPE/input= when the child is fed):\n  " + "\n  ".join(offenders)
    )


def test_allow_list_has_no_stale_entries():
    hit = {(rel, func) for rel, _line, _callee, func in _scan_repo()}
    stale = sorted(set(ALLOWED) - hit)
    assert not stale, f"ALLOWED entries that no longer match an unnamed-stdin call: {stale}"


# ----------------------------------------------------------- the checker itself
# Controls: it must flag the known-bad shapes and pass the known-good ones.

_BAD = {
    "plain run": "import subprocess\ndef f():\n    subprocess.run(['x'])\n",
    "popen no stdin": "import subprocess\ndef f():\n    subprocess.Popen(['x'], stdout=subprocess.PIPE)\n",
    "alias import": "import subprocess as sp\ndef f():\n    sp.check_output(['x'])\n",
    "from import": "from subprocess import run as r\ndef f():\n    r(['x'])\n",
    "kwargs dict without stdin": (
        "import subprocess\ndef f():\n    kw = {'stdout': subprocess.PIPE}\n    subprocess.run(['x'], **kw)\n"
    ),
    "kwargs from a parameter": "import subprocess\ndef f(**kw):\n    subprocess.run(['x'], **kw)\n",
    "stdin in another function": (
        "import subprocess\ndef g():\n    kw = {'stdin': subprocess.DEVNULL}\n    return kw\n"
        "def f():\n    kw = {}\n    subprocess.run(['x'], **kw)\n"
    ),
    "os.system": "import os\ndef f():\n    os.system('x')\n",
    "capture_output only": "import subprocess\ndef f():\n    subprocess.run(['x'], capture_output=True)\n",
}
_GOOD = {
    "stdin keyword": "import subprocess\ndef f():\n    subprocess.run(['x'], stdin=subprocess.DEVNULL)\n",
    "input keyword": "import subprocess\ndef f():\n    subprocess.run(['x'], input=b'y')\n",
    "stdin pipe": "import subprocess\ndef f():\n    subprocess.Popen(['x'], stdin=subprocess.PIPE)\n",
    "kwargs dict with stdin": (
        "import subprocess\ndef f():\n    kw: dict = {'stdin': subprocess.DEVNULL}\n    subprocess.run(['x'], **kw)\n"
    ),
    "kwargs subscript": (
        "import subprocess\ndef f():\n    kw = {}\n    kw['stdin'] = subprocess.DEVNULL\n    subprocess.run(['x'], **kw)\n"
    ),
    "inline ** dict": "import subprocess\ndef f(k):\n    subprocess.run(['x'], **{'stdin': subprocess.DEVNULL, **k})\n",
    "from import with stdin": "from subprocess import run\ndef f():\n    run(['x'], stdin=-3)\n",
    "unrelated run": "def f(o):\n    o.run(['x'])\n",
}


@pytest.mark.parametrize("name", sorted(_BAD))
def test_checker_flags_known_bad_shapes(name):
    assert find_calls_without_stdin(_BAD[name]), name


@pytest.mark.parametrize("name", sorted(_GOOD))
def test_checker_passes_known_good_shapes(name):
    assert find_calls_without_stdin(_GOOD[name]) == [], name
