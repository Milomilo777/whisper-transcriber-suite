"""Select compatible native libraries before PyInstaller copies and signs them."""
import ast
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "platform/macos/pyinstaller/whisper_project_mac.spec"


def _selector(versions):
    tree = ast.parse(SPEC.read_text(encoding="utf-8"))
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_select_compatible_dylibs"]
    assert functions, "Dylib conflict handling must run before COLLECT, including regular files"
    namespace = {"os": os, "_compat_version": lambda p: versions[str(p)]}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(SPEC), "exec"), namespace)
    return namespace["_select_compatible_dylibs"]


def test_regular_top_level_lzma_uses_the_version_required_by_pillow(tmp_path):
    av = tmp_path / "av" / "liblzma.5.dylib"
    pillow = tmp_path / "PIL" / "liblzma.5.dylib"
    for p in (av, pillow):
        p.parent.mkdir(); p.write_bytes(b"native library fixture")
    rows = [("liblzma.5.dylib", str(av), "BINARY"), ("av/.dylibs/liblzma.5.dylib", str(av), "BINARY"), ("liblzma-link", "liblzma.5.dylib", "SYMLINK")]
    select = _selector({str(av): (10, 0, 0), str(pillow): (14, 0, 0)})
    result = select(rows, [str(pillow)])
    assert result == [(rows[0][0], str(pillow), "BINARY"), (rows[1][0], str(pillow), "BINARY"), rows[2]]
    assert rows[0][1] == str(av), "Leave the source inventory available for inspection"


def test_never_downgrades_or_changes_unrelated_collected_files(tmp_path):
    old = tmp_path / "old" / "liblzma.5.dylib"
    new = tmp_path / "new" / "liblzma.5.dylib"
    for p in (old, new):
        p.parent.mkdir(); p.write_bytes(b"fixture")
    rows = [("liblzma.5.dylib", str(new), "BINARY"), ("metadata", str(old), "DATA"), ("Python", "Python.framework/Versions/3.12/Python", "SYMLINK")]
    select = _selector({str(old): (10, 0, 0), str(new): (14, 0, 0)})
    assert select(rows, [str(old)]) == rows


def test_dylib_selection_precedes_collection_and_signing():
    text = SPEC.read_text(encoding="utf-8")
    tree = ast.parse(text)
    calls = [n for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)]
    select = next((n for n in calls if isinstance(n.value.func, ast.Name) and n.value.func.id == "_select_compatible_dylibs"), None)
    assert select is not None
    collect = next(n for n in calls if isinstance(n.value.func, ast.Name) and n.value.func.id == "COLLECT")
    assert select.lineno < collect.lineno
