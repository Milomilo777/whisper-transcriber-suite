"""Collect the interface texts marked for translation and write app/locales/en.json.

Standard library only. Scans app/ and gui.py (app/i18n.py itself excluded) for calls of
``_``, ``ngettext``, ``pgettext``, ``N_`` and ``lazy`` (also as ``i18n.<name>``) and reports
what would break translation:

  * a message that is not a string literal (an f-string, a variable, a ``%`` or ``+``
    expression); implicit concatenation of literals is fine;
  * a positional placeholder (``{}`` or ``{0}``) in a message that gets formatted, or a named one
    the call does not pass;
  * a function (or module) that both assigns the name ``_`` (``for _ in ...``, ``a, _ = ...``)
    and calls ``_()``: the call would raise UnboundLocalError;
  * one message used both as a plain text and as a plural, or with two different plurals.

``translate(x)`` takes a constant marked with ``N_``; it is checked only for f-strings and
``%`` / ``+`` expressions, and a literal argument is collected like ``_()``.

Usage:
  python tools/i18n_extract.py                  write app/locales/en.json (exit 1 on an error)
  python tools/i18n_extract.py --check          exit 1 when en.json is stale or an error exists
  python tools/i18n_extract.py --find-unwrapped FILE...   list literals that look like
                                                 interface text but are not marked (exit 0)
  python tools/i18n_extract.py --missing CODE   list messages app/locales/CODE.json lacks
See docs/TRANSLATING.md.
"""
from __future__ import annotations

import argparse
import ast
import json
import string
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTEXT_SEPARATOR = "\x04"
MARKERS = {"_", "ngettext", "pgettext", "N_", "lazy"}
RUNTIME = {"translate"}
_MSG_ARGS = {"_": (0,), "N_": (0,), "lazy": (0,), "ngettext": (0, 1), "pgettext": (0, 1),
             "translate": (0,)}
_FORMATTED = {"_", "lazy", "ngettext", "pgettext", "translate"}
_TEXT_KEYWORDS = {"text", "title", "label", "message"}
_TEXT_FUNCTIONS = {"show_error", "notify", "set"}


@dataclass
class Result:
    messages: dict[str, str | list[str]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    _where: dict[str, str] = field(default_factory=dict)

    def add(self, key: str, value: str | list[str], where: str) -> None:
        old = self.messages.get(key)
        if old is not None and old != value:
            kind = "plural" if isinstance(value, list) or isinstance(old, list) else "text"
            self.errors.append(f"{where}: message {key!r} conflicts with {self._where[key]} ({kind})")
            return
        self.messages[key] = value
        self._where.setdefault(key, where)


def _marker_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name) and func.id in MARKERS | RUNTIME:
        return func.id
    if (isinstance(func, ast.Attribute) and func.attr in MARKERS | RUNTIME
            and isinstance(func.value, ast.Name) and func.value.id == "i18n"):
        return func.attr
    return None


def _literal(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _describe(node: ast.expr) -> str:
    if isinstance(node, ast.JoinedStr):
        return "an f-string"
    if isinstance(node, ast.BinOp):
        return "a % or + expression"
    if isinstance(node, ast.Call):
        return "a call result"
    return "not a string literal"


def _placeholders(text: str) -> list[str] | None:
    try:
        return [name for _lit, name, _spec, _conv in string.Formatter().parse(text) if name is not None]
    except ValueError:
        return None


def _check_placeholders(name: str, call: ast.Call, texts: list[str], where: str, out: Result) -> None:
    has_splat = any(k.arg is None for k in call.keywords)
    given = {k.arg for k in call.keywords if k.arg is not None}
    if name == "ngettext":
        given.add("n")
    formatted = name == "ngettext" or bool(call.keywords)
    for text in texts:
        fields = _placeholders(text)
        if fields is None:
            if formatted:
                out.errors.append(f"{where}: {text!r} has an unbalanced brace")
            continue
        for f in fields:
            base = f.split(".")[0].split("[")[0]
            if base == "" or base.isdigit():
                if formatted or name == "N_":
                    out.errors.append(f"{where}: {text!r} uses a positional placeholder; name it")
            elif formatted and not has_splat and base not in given:
                out.errors.append(f"{where}: {text!r} needs the keyword argument {base}=")


def _visit_call(call: ast.Call, name: str, where: str, out: Result) -> None:
    positions = _MSG_ARGS[name]
    if len(call.args) <= max(positions):
        out.errors.append(f"{where}: {name}() needs its message as a positional string literal")
        return
    args = [call.args[i] for i in positions]
    texts = [_literal(a) for a in args]
    if name == "translate":
        arg = args[0]
        if isinstance(arg, (ast.JoinedStr, ast.BinOp)) or (
                isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute)
                and arg.func.attr == "format"):
            out.errors.append(f"{where}: translate() got {_describe(arg)}; build the text with "
                              "named placeholders instead")
        if texts[0] is None:
            return  # a constant marked with N_ where it is defined
    for arg, text in zip(args, texts):
        if text is None:
            out.errors.append(f"{where}: {name}() message is {_describe(arg)}; use a string literal "
                              "with named placeholders")
            return
    msgs = [t for t in texts if t is not None]
    _check_placeholders(name, call, msgs[1:] if name == "pgettext" else msgs, where, out)
    if name == "ngettext":
        out.add(msgs[0], [msgs[0], msgs[1]], where)
    elif name == "pgettext":
        out.add(msgs[0] + CONTEXT_SEPARATOR + msgs[1], msgs[1], where)
    else:
        out.add(msgs[0], msgs[0], where)


_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ListComp, ast.SetComp,
           ast.DictComp, ast.GeneratorExp, ast.ClassDef)


def _binds_underscore(node: ast.AST) -> bool:
    """True when ``node`` (one statement or expression, not a nested scope) binds ``_``."""
    if isinstance(node, ast.Name) and node.id == "_" and isinstance(node.ctx, (ast.Store, ast.Del)):
        return True
    if isinstance(node, ast.arg) and node.arg == "_":
        return True
    if isinstance(node, ast.ExceptHandler) and node.name == "_":
        return True
    if isinstance(node, ast.alias) and (node.asname or node.name) == "_":
        return True
    if isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name == "_":
        return True
    return False


def _scope_nodes(scope: ast.AST) -> list[ast.AST]:
    """Every node in ``scope`` that belongs to it, not to a nested function/class/comprehension."""
    found: list[ast.AST] = []
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        found.append(node)
        if isinstance(node, _SCOPES):
            # Decorators, defaults and the first iterable are evaluated in the outer scope;
            # treating them as nested only misses a rare case, never flags a correct one.
            continue
        stack.extend(ast.iter_child_nodes(node))
    return found


def _check_underscore_shadowing(tree: ast.Module, rel: str, out: Result) -> None:
    def calls_underscore(nodes: list[ast.AST], scope: ast.AST) -> list[int]:
        lines = [n.lineno for n in nodes if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == "_"]
        # Nested scopes that do not bind ``_`` themselves see the outer binding.
        for n in nodes:
            if isinstance(n, _SCOPES) and n is not scope:
                inner = _scope_nodes(n)
                if not any(_binds_underscore(x) for x in inner):
                    lines += calls_underscore(inner, n)
        return lines

    def check(scope: ast.AST, label: str) -> None:
        nodes = _scope_nodes(scope)
        declared_global = any(isinstance(n, (ast.Global, ast.Nonlocal)) and "_" in n.names
                              for n in nodes)
        binders = [n for n in nodes if _binds_underscore(n)]
        if binders and not declared_global:
            calls = calls_underscore(nodes, scope)
            if calls:
                first = getattr(binders[0], "lineno", calls[0])
                out.errors.append(
                    f"{rel}:{calls[0]}: {label} assigns the name _ (line {first}) and calls _(); "
                    "rename the throwaway variable (for example to _unused)")
        for n in nodes:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                check(n, f"function {n.name}()")
            elif isinstance(n, ast.Lambda):
                check(n, "a lambda")
            elif isinstance(n, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                check(n, "a comprehension")
            elif isinstance(n, ast.ClassDef):
                check(n, f"class {n.name}")

    tree_nodes = _scope_nodes(tree)
    imports_marker = any(isinstance(n, ast.ImportFrom) and any(a.name == "_" and a.asname is None
                                                               for a in n.names)
                         for n in tree_nodes)
    if imports_marker:
        # The import itself binds ``_`` at module level; flag only other module-level bindings.
        others = [n for n in tree_nodes if _binds_underscore(n) and not isinstance(n, ast.alias)]
        if others and calls_underscore(tree_nodes, tree):
            line = getattr(others[0], "lineno", 1)
            out.errors.append(f"{rel}:{line}: the module rebinds _ after importing it; rename "
                              "the throwaway variable")
        for n in tree_nodes:
            if isinstance(n, _SCOPES):
                label = f"function {n.name}()" if isinstance(
                    n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else "a nested scope"
                check(n, label)
    else:
        check(tree, "the module")


def scan_source(source: str, rel: str, out: Result) -> None:
    try:
        tree = ast.parse(source, filename=rel)
    except SyntaxError as e:
        out.errors.append(f"{rel}:{e.lineno}: cannot parse ({e.msg})")
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _marker_name(node.func)
            if name is not None:
                _visit_call(node, name, f"{rel}:{node.lineno}", out)
    _check_import_time_calls(tree, rel, out)
    _check_underscore_shadowing(tree, rel, out)


_IMPORT_TIME_REFUSED = {"_", "ngettext", "pgettext", "translate"}


def _check_import_time_calls(tree: ast.Module, rel: str, out: Result) -> None:
    """A translation call at module or class level runs at import time, which can be before
    the language is set at start-up: the text would stay English. Mark the constant with
    N_() and translate it where it is shown (lazy() is fine: it runs later)."""
    pending: list[ast.AST] = [tree]
    while pending:
        scope = pending.pop()
        for node in _scope_nodes(scope):
            if isinstance(node, ast.ClassDef):
                pending.append(node)
            elif isinstance(node, ast.Call) and _marker_name(node.func) in _IMPORT_TIME_REFUSED:
                out.errors.append(f"{rel}:{node.lineno}: {_marker_name(node.func)}() runs at import "
                                  "time, maybe before the language is set; use N_() here and "
                                  "translate() where the text is shown")


def source_files(root: Path) -> list[Path]:
    files = sorted(p for p in (root / "app").rglob("*.py")
                   if "__pycache__" not in p.parts and p != root / "app" / "i18n.py")
    gui = root / "gui.py"
    if gui.is_file():
        files.append(gui)
    return files


def extract(root: Path) -> Result:
    out = Result()
    for path in source_files(root):
        rel = path.relative_to(root).as_posix()
        scan_source(path.read_text(encoding="utf-8"), rel, out)
    return out


def render_catalog(messages: dict[str, str | list[str]]) -> bytes:
    doc = {
        "_meta": {"code": "en", "direction": "ltr", "name": "English", "plural": "one_other",
                  "status": "source"},
        "messages": messages,
    }
    return (json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def catalog_path(root: Path, code: str = "en") -> Path:
    return root / "app" / "locales" / f"{code}.json"


def find_unwrapped(paths: list[Path]) -> list[str]:
    """Heuristic: string literals passed as interface text that are not wrapped in _()."""
    hits: list[str] = []
    for path in paths:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError) as e:
            hits.append(f"{path}: cannot read ({e})")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            candidates: list[ast.expr] = [k.value for k in node.keywords if k.arg in _TEXT_KEYWORDS]
            func = node.func
            fname = func.attr if isinstance(func, ast.Attribute) else (
                func.id if isinstance(func, ast.Name) else "")
            in_messagebox = (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
                             and func.value.id == "messagebox")
            if (in_messagebox or fname in _TEXT_FUNCTIONS or fname == "title") and node.args:
                candidates.extend(node.args[:2] if in_messagebox else node.args[:1])
            for arg in candidates:
                text = _literal(arg)
                if isinstance(arg, ast.JoinedStr):
                    hits.append(f"{path}:{arg.lineno}: f-string")
                elif text is not None and any(c.isalpha() for c in text):
                    hits.append(f"{path}:{arg.lineno}: {text!r}")
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root (tests)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="exit 1 when en.json is stale")
    group.add_argument("--find-unwrapped", nargs="+", type=Path, metavar="FILE")
    group.add_argument("--missing", metavar="CODE", help="messages CODE.json lacks")
    args = parser.parse_args(argv)
    root: Path = args.root

    if args.find_unwrapped:
        for hit in find_unwrapped(args.find_unwrapped):
            print(hit)
        return 0

    result = extract(root)
    for err in result.errors:
        print(f"error: {err}", file=sys.stderr)
    target = catalog_path(root)
    rendered = render_catalog(result.messages)

    if args.missing:
        other = catalog_path(root, args.missing)
        try:
            doc = json.loads(other.read_text(encoding="utf-8"))
            have = doc.get("messages", {}) if isinstance(doc, dict) else {}
        except (OSError, ValueError) as e:
            print(f"error: cannot read {other}: {e}", file=sys.stderr)
            return 2
        missing = [k for k in sorted(result.messages) if k not in have or have[k] in ("", [])]
        for key in missing:
            print(key.replace(CONTEXT_SEPARATOR, " | "))
        print(f"{len(missing)} of {len(result.messages)} messages missing in {args.missing}",
              file=sys.stderr)
        return 1 if result.errors else 0

    if args.check:
        try:
            current = target.read_bytes()
        except OSError:
            current = b""
        if current != rendered:
            print(f"error: {target} is stale; run python tools/i18n_extract.py", file=sys.stderr)
            return 1
        return 1 if result.errors else 0

    if result.errors:
        print(f"{len(result.errors)} error(s); {target} not written", file=sys.stderr)
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(rendered)
    print(f"wrote {target} ({len(result.messages)} messages)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
