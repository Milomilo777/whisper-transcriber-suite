"""tools/build_manifest.py: the manifest writer and the compare / strict-prefix logic."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


build_manifest = _load("build_manifest")


def _manifest(tree: str, files: dict[str, tuple[int, str]]):
    return {"tree": tree,
            "files": {rel: {"size": size, "sha256": sha} for rel, (size, sha) in files.items()}}


def test_area_groups_site_packages_by_package():
    assert build_manifest.area("Lib/site-packages/numpy/core.py") == "Lib/site-packages/numpy"
    assert build_manifest.area(
        "Lib/site-packages/numpy-1.26.4.dist-info/METADATA") == "Lib/site-packages/numpy"
    assert build_manifest.area("app/core.py") == "app"
    assert build_manifest.area("gui.py") == "(top level)"


def test_compare_identical_trees_has_no_failures():
    files = {"app/x.py": (3, "a"), "lib/site-packages/np/__init__.py": (5, "b")}
    lines, failures = build_manifest.compare(
        _manifest("A", files), _manifest("B", files), [], 0.10)
    assert failures == []
    assert "A = A (2 files), B = B (2 files)" in lines[0]


def test_compare_ignores_pycache():
    files = {"app/x.py": (3, "a")}
    pyc = {"app/__pycache__/x.cpython-312.pyc": (100, "z")}
    _lines, failures = build_manifest.compare(
        _manifest("A", files), _manifest("B", {**files, **pyc}), [], 0.10)
    assert failures == []


def test_strict_prefix_does_not_match_a_sibling_that_shares_the_text():
    # "app2/x.py" is not under the prefix "app": only a real path-component
    # boundary counts, otherwise --strict app also guards app2/.
    a = _manifest("A", {"app/y.py": (1, "a"), "app2/x.py": (1, "a")})
    b = _manifest("B", {"app/y.py": (1, "a"), "app2/x.py": (2, "b")})
    _lines, failures = build_manifest.compare(a, b, ["app"], 10.0)
    assert failures == []
