"""Every interface catalog in app/locales is valid, fits en.json, and en.json is current.

Missing translations are reported as warnings, never as failures: a catalog may be partial.
"""
from __future__ import annotations

import json
import string
import subprocess
import sys
import warnings
from pathlib import Path
from typing import Any

import pytest

from app import i18n

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "app" / "locales"
EXTRACTOR = ROOT / "tools" / "i18n_extract.py"


def _fields(text: str) -> set[str] | None:
    try:
        return {name for _lit, name, _spec, _conv in string.Formatter().parse(text) if name is not None}
    except ValueError:
        return None


def catalog_problems(path: Path, source: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(problems, missing keys) of one catalog file against the source messages."""
    problems: list[str] = []
    try:
        raw = path.read_bytes()
        doc = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        return [f"not valid UTF-8 JSON: {e}"], []
    if b"\r" in raw:
        problems.append("has CR line endings (LF only)")
    if not isinstance(doc, dict) or set(doc) != {"_meta", "messages"}:
        return problems + ["top level must be exactly _meta and messages"], []
    meta, messages = doc["_meta"], doc["messages"]
    if not isinstance(meta, dict) or not isinstance(messages, dict):
        return problems + ["_meta and messages must be objects"], []
    code = path.stem
    lang = i18n.LANGUAGES_BY_CODE.get(code)
    if lang is None:
        return problems + [f"{code} is not in SUPPORTED_LANGUAGES"], []
    if meta.get("code") != code:
        problems.append(f"_meta.code {meta.get('code')!r} differs from the file name")
    if meta.get("name") != lang.endonym:
        problems.append(f"_meta.name {meta.get('name')!r} is not {lang.endonym!r}")
    if meta.get("direction") != lang.direction:
        problems.append(f"_meta.direction {meta.get('direction')!r} is not {lang.direction!r}")
    if meta.get("plural") != lang.plural:
        problems.append(f"_meta.plural {meta.get('plural')!r} is not {lang.plural!r}")
    expected_status = {"source"} if code == "en" else {"machine", "reviewed"}
    if meta.get("status") not in expected_status:
        problems.append(f"_meta.status {meta.get('status')!r} not in {sorted(expected_status)}")
    nforms = i18n.PLURAL_RULES[lang.plural][0]
    for key, value in messages.items():
        if key not in source:
            problems.append(f"{key!r} is not in en.json")
            continue
        msgid = key.split(i18n.CONTEXT_SEPARATOR, 1)[-1]
        if isinstance(source[key], list):
            if not (isinstance(value, list) and all(isinstance(v, str) for v in value)):
                problems.append(f"{key!r} needs a list of {nforms} plural forms")
                continue
            if any(value) and len(value) != nforms:
                problems.append(f"{key!r} has {len(value)} plural forms, rule {lang.plural} needs {nforms}")
            wanted = (_fields(source[key][0]) or set()) | (_fields(source[key][1]) or set())
            for form in value:
                got = _fields(form)
                if form and (got is None or not got <= wanted | {"n"}):
                    problems.append(f"{key!r} form {form!r} has placeholders {got} (allowed {wanted | {'n'}})")
        else:
            if not isinstance(value, str):
                problems.append(f"{key!r} must be a string")
                continue
            if value and _fields(value) != _fields(msgid):
                problems.append(f"{key!r}: placeholders {_fields(value)} differ from {_fields(msgid)}")
    if code == "en":
        for key, value in messages.items():
            want = source.get(key)
            if value != want:
                problems.append(f"en.json {key!r} is {value!r}, expected {want!r}")
    missing = [k for k in source if k not in messages or messages[k] in ("", [])]
    return problems, missing


def _source() -> dict[str, Any]:
    return json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))["messages"]


CATALOGS = sorted(LOCALES.glob("*.json"))


def test_en_json_exists_and_is_the_source() -> None:
    assert (LOCALES / "en.json") in CATALOGS
    doc = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
    assert doc["_meta"]["status"] == "source"
    for key, value in doc["messages"].items():
        msgid = key.split(i18n.CONTEXT_SEPARATOR, 1)[-1]
        assert value == msgid or (isinstance(value, list) and len(value) == 2 and value[0] == key)


@pytest.mark.parametrize("path", CATALOGS, ids=lambda p: p.name)
def test_catalog_is_valid(path: Path) -> None:
    problems, missing = catalog_problems(path, _source())
    assert problems == []
    if missing:
        warnings.warn(f"{path.name}: {len(missing)} of {len(_source())} messages not translated",
                      stacklevel=1)


def test_en_json_is_current() -> None:
    res = subprocess.run([sys.executable, str(EXTRACTOR), "--check"], capture_output=True, text=True,
                         stdin=subprocess.DEVNULL, timeout=120)
    assert res.returncode == 0, res.stdout + res.stderr


# --- the validator itself catches each kind of broken catalog -------------------------------

SOURCE = {"Save": "Save", "Saved {name}": "Saved {name}", "{n} file": ["{n} file", "{n} files"],
          "menu\x04Open": "Open"}


def _write(tmp_path: Path, code: str, messages: Any, meta: dict[str, Any] | None = None) -> Path:
    lang = i18n.LANGUAGES_BY_CODE.get(code)
    base = {"code": code, "name": lang.endonym if lang else code, "plural": lang.plural if lang else "x",
            "direction": lang.direction if lang else "ltr", "status": "machine"}
    base.update(meta or {})
    path = tmp_path / f"{code}.json"
    path.write_text(json.dumps({"_meta": base, "messages": messages}, ensure_ascii=False), encoding="utf-8")
    return path


def test_validator_accepts_a_good_partial_catalog(tmp_path: Path) -> None:
    path = _write(tmp_path, "ru", {"Saved {name}": "Сохранено: {name}",
                                   "{n} file": ["{n} файл", "{n} файла", "{n} файлов"]})
    problems, missing = catalog_problems(path, SOURCE)
    assert problems == []
    assert sorted(missing) == ["Save", "menu\x04Open"]


@pytest.mark.parametrize("code,messages,meta,needle", [
    ("de", {"Unknown": "x"}, {}, "not in en.json"),
    ("de", {"Saved {name}": "Gespeichert {nom}"}, {}, "placeholders"),
    ("de", {"Saved {name}": "Gespeichert"}, {}, "placeholders"),
    ("ru", {"{n} file": ["{n} файл", "{n} файлов"]}, {}, "plural forms"),
    ("de", {"{n} file": "Datei"}, {}, "list"),
    ("de", {"Save": ["a"]}, {}, "must be a string"),
    ("de", {}, {"code": "fr"}, "differs from the file name"),
    ("de", {}, {"status": "draft"}, "status"),
    ("de", {}, {"plural": "pl"}, "plural"),
    ("de", {}, {"direction": "rtl"}, "direction"),
    ("xx", {}, {}, "not in SUPPORTED_LANGUAGES"),
])
def test_validator_catches(tmp_path: Path, code: str, messages: Any, meta: dict[str, Any],
                           needle: str) -> None:
    problems, _missing = catalog_problems(_write(tmp_path, code, messages, meta), SOURCE)
    assert any(needle in p for p in problems), problems


def test_validator_catches_bad_json_and_crlf(tmp_path: Path) -> None:
    bad = tmp_path / "de.json"
    bad.write_bytes(b"{nope")
    assert catalog_problems(bad, SOURCE)[0]
    crlf = _write(tmp_path, "fr", {})
    crlf.write_bytes(crlf.read_bytes().replace(b"\n", b"\r\n") + b"\r\n")
    assert any("CR" in p for p in catalog_problems(crlf, SOURCE)[0])
