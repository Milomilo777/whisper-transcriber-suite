"""The macOS app declares the audio and video it can open from Finder.

``platform/macos/pyinstaller/document_types.py`` builds the Info.plist
``CFBundleDocumentTypes`` list from ``core/media_types.py``; the mac spec calls
it. The spec cannot be run here (no PyInstaller, no Mac), so the tests run the
spec's own loader code and read the ``info_plist`` it hands to ``BUNDLE``.
"""
from __future__ import annotations

import ast
import importlib.util
import os
import plistlib
from pathlib import Path
from typing import Any

import pytest

from core.media_types import MEDIA_EXTENSIONS

ROOT = Path(__file__).resolve().parent.parent
PYI = ROOT / "platform" / "macos" / "pyinstaller"
SPEC = PYI / "whisper_project_mac.spec"
SPECS = (
    ROOT / "whisper_project_onefile.spec",
    ROOT / "whisper_project_onedir.spec",
    SPEC,
)


def _module() -> Any:
    loader = importlib.util.spec_from_file_location("_doc_types_under_test", PYI / "document_types.py")
    assert loader is not None and loader.loader is not None
    mod = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(mod)
    return mod


def _spec_tree() -> ast.Module:
    return ast.parse(SPEC.read_text(encoding="utf-8"))


def _bundle_info_plist() -> ast.Dict:
    for node in ast.walk(_spec_tree()):
        if (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "BUNDLE"
        ):
            for kw in node.keywords:
                if kw.arg == "info_plist" and isinstance(kw.value, ast.Dict):
                    return kw.value
    raise AssertionError("no BUNDLE(info_plist={...}) in the mac spec")


def _spec_document_types() -> Any:
    """Run the spec's own code that computes ``_DOCUMENT_TYPES`` and return the value."""
    wanted: list[ast.stmt] = []
    for node in _spec_tree().body:
        if isinstance(node, ast.Import) and any(a.asname == "_ilu" for a in node.names):
            wanted.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name == "_load_by_path":
            wanted.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "_DOCUMENT_TYPES" for t in node.targets
        ):
            wanted.append(node)
    assert len(wanted) == 3, "the spec's document-type loader changed shape"
    namespace: dict[str, Any] = {"os": os, "_REPO_ROOT": str(ROOT)}
    exec(compile(ast.Module(body=wanted, type_ignores=[]), str(SPEC), "exec"), namespace)  # noqa: S102
    return namespace["_DOCUMENT_TYPES"]


def test_the_spec_puts_document_types_in_the_info_plist() -> None:
    plist = _bundle_info_plist()
    keys = {k.value: v for k, v in zip(plist.keys, plist.values) if isinstance(k, ast.Constant)}
    assert "CFBundleDocumentTypes" in keys
    value = keys["CFBundleDocumentTypes"]
    assert isinstance(value, ast.Name) and value.id == "_DOCUMENT_TYPES"


def test_the_spec_computes_the_same_list_as_the_helper() -> None:
    assert _spec_document_types() == _module().document_types(MEDIA_EXTENSIONS)


def test_every_entry_is_a_viewer_with_alternate_rank_never_the_default() -> None:
    entries = _spec_document_types()
    assert len(entries) >= 2
    for entry in entries:
        assert entry["CFBundleTypeRole"] == "Viewer"
        assert entry["LSHandlerRank"] == "Alternate"
        assert entry["CFBundleTypeName"]
        assert "LSIsAppleDefaultForType" not in entry
        assert "NSDocumentClass" not in entry  # not a document-based app


def test_system_audio_and_movie_types_are_declared_and_extensions_cover_the_rest() -> None:
    entries = _spec_document_types()
    utis = {u for e in entries for u in e.get("LSItemContentTypes", [])}
    assert {"public.audio", "public.movie"} <= utis
    extensions = {x for e in entries for x in e.get("CFBundleTypeExtensions", [])}
    for must in ("mp3", "wav", "m4a", "mp4", "mov", "mkv", "webm", "flac", "ogg", "opus"):
        assert must in extensions, must


def test_every_media_extension_the_app_accepts_is_declared_except_ts() -> None:
    extensions = {x for e in _spec_document_types() for x in e.get("CFBundleTypeExtensions", [])}
    accepted = {e.lstrip(".").lower() for e in MEDIA_EXTENSIONS}
    assert accepted - extensions == {"ts"}
    assert extensions <= accepted  # nothing invented


def test_ts_has_no_explicit_extension_entry() -> None:
    """.ts is TypeScript far more often than an MPEG transport stream.

    Only the explicit extension list is checked: ``public.movie`` may still list the app
    for some .ts files, at rank Alternate (Open With only).
    """
    for entry in _spec_document_types():
        assert "ts" not in entry.get("CFBundleTypeExtensions", [])


def test_extension_list_is_plain_sorted_lowercase_and_unique() -> None:
    for entry in _spec_document_types():
        exts = entry.get("CFBundleTypeExtensions")
        if exts is None:
            continue
        assert exts == sorted(set(exts))
        assert all(x == x.lower() and not x.startswith(".") and x for x in exts)


def test_the_list_is_a_valid_info_plist_value() -> None:
    data = plistlib.dumps({"CFBundleDocumentTypes": _spec_document_types()})
    back = plistlib.loads(data)["CFBundleDocumentTypes"]
    assert back == _spec_document_types()


def test_helper_drops_dots_case_and_excluded_extensions() -> None:
    entries = _module().document_types([".MP4", "mkv", ".ts", ".Mp4"])
    assert entries[-1]["CFBundleTypeExtensions"] == ["mkv", "mp4"]


@pytest.mark.parametrize("spec", SPECS, ids=lambda p: p.name)
def test_all_three_specs_list_the_new_module_as_a_hidden_import(spec: Path) -> None:
    assert "'app.mac_native'," in spec.read_text(encoding="utf-8")


def test_the_bundle_checks_look_for_the_document_types() -> None:
    for script in ("verify_mac_bundle.sh", "test_dmg.sh"):
        text = (PYI / script).read_text(encoding="utf-8")
        assert "CFBundleDocumentTypes" in text, script
        assert "LSHandlerRank" in text, script  # never the default app for a type
