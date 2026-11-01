"""core.diagnostic: nothing from the person's computer may survive in a diagnostic record."""
from __future__ import annotations

import json
import re
import sys
import types

import pytest

from core import diagnostic as dg
from core.diagnostic_vocab import VOCABULARY

LEAKY = [
    r"[WinError 5] Access is denied: 'C:\Users\JohnSmith\Videos\Private Project\interview.mp4'",
    "could not open /home/maria.garcia/Documents/secret-plan.wav",
    "HTTP Error 403: Forbidden for https://example.com/watch?v=abc123&token=SECRET9876543210",
    "mail me at jane.doe@example.org about 4155550123",
    "Invalid language identifier JohnSmithPrivateProject",
    "Authentication failed for account admin_company",
    r"Access denied to \\NAS\Confidential\Project",
    "unable to allocate 123456789 bytes for shape (1, 2) in 'MyFolder'",
]
SECRET_WORDS = (
    "john", "smith", "maria", "garcia", "secret", "example", "jane", "doe", "project",
    "nas", "confidential", "admin", "company", "interview", "myfolder", "abc123", "4155550123", "123456789",
    "users", "videos", "documents",
)


@pytest.mark.parametrize("text", LEAKY)
def test_shape_keeps_no_personal_word(text):
    shape = dg.message_shape(text)
    for word in SECRET_WORDS:
        assert word not in shape.lower().split(), (word, shape)
    for token in shape.split():
        assert token == "*" or token == "#" or token.isdigit() or token in VOCABULARY, (token, shape)


def test_shape_keeps_the_useful_part():
    shape = dg.message_shape("Unable to allocate 5 bytes for an array with shape (1, 2) and data type float32")
    assert "unable to allocate 5 bytes for an array with shape # and data type float32" == shape


def test_runs_of_short_numbers_never_survive():
    # an IPv4 address, a phone number and a date are rows of short numbers
    for text in ("connection to 192.168.1.20 port 8080 refused", "call 415 555 0123", "on 2026 11 02 error 5"):
        shape = dg.message_shape(text)
        assert not any(t.isdigit() and t not in ("5",) for t in shape.split()), shape
    assert dg.message_shape("[WinError 5] Access is denied") == "winerror 5 access is denied"


def test_sanitise_keeps_the_placeholders_of_a_real_shape():
    rec = {"cls": "ValueError", "os": "0", "frames": "core.worker:run:12", "shape": "invalid * value # 5 bytes",
           "hash": "ab12cd34"}
    assert dg.sanitise(rec)["shape"] == "invalid * value # 5 bytes"
    assert dg.sanitise(dict(rec, shape="invalid johnsmith value"))["shape"] == "invalid value"
    assert dg.sanitise(dict(rec, frames="home.maria.secret:run:3"))["frames"] == ""


def test_long_numbers_and_empty_input():
    assert dg.message_shape("error 1234567") == "error #"
    assert dg.message_shape(None) == ""
    assert dg.message_shape("") == ""
    assert len(dg.message_shape("error " * 500)) <= dg.MAX_SHAPE_CHARS


def test_shape_is_ascii_even_for_non_latin_input():
    assert dg.message_shape("خطا در فایل 日本語 файл") == ""
    assert dg.message_shape("ошибка file").isascii()


def test_negative_control_a_leaky_variant_is_caught():
    def leaky(text):  # the obvious wrong implementation: keep every token
        return " ".join(re.findall(r"[A-Za-z0-9]+", text)).lower()
    assert "johnsmith" in leaky(LEAKY[0]).split()  # the check below WOULD fail for this implementation
    assert "johnsmith" not in dg.message_shape(LEAKY[0]).split()


def _raise_in(module_name, func_name="boom"):
    mod = types.ModuleType(module_name)
    exec(f"def {func_name}(msg):\n    raise ValueError(msg)\n", mod.__dict__)
    sys.modules[module_name] = mod
    return mod


def test_build_records_class_frames_and_hash_without_the_message():
    _raise_in("core.fake_site")
    try:
        sys.modules["core.fake_site"].boom(r"bad value in C:\Users\JohnSmith\x.wav")
    except ValueError as e:
        rec = dg.build(e)
    finally:
        sys.modules.pop("core.fake_site", None)
    assert rec["cls"] == "ValueError"
    assert "core.fake_site:boom:2" in rec["frames"]
    assert "johnsmith" not in json.dumps(rec).lower()
    assert re.fullmatch(r"[0-9a-f]{8}", rec["hash"])


_BOOM_SOURCE = "def boom(msg):\n    return NEXT(msg)\n"


def test_frames_skip_unknown_packages_and_keep_the_last_five():
    names = [f"core.m{i}" for i in range(7)]
    mods = []
    try:
        for i, n in enumerate(names):
            mod = types.ModuleType(n)
            exec(_BOOM_SOURCE, mod.__dict__)
            mods.append(mod)
            sys.modules[n] = mod
        for i, mod in enumerate(mods):
            mod.__dict__["NEXT"] = mods[i + 1].boom if i + 1 < len(mods) else _raise_value
        try:
            mods[0].boom("x")
        except ValueError as e:
            text = dg.frames_text(e.__traceback__)
    finally:
        for n in names:
            sys.modules.pop(n, None)
    frames = text.split(">")
    assert len(frames) == 5
    assert frames[-1].startswith("core.m6:boom:")
    assert all(f.startswith("core.") for f in frames)  # this test file itself is not allow-listed


def _raise_value(msg):
    raise ValueError(msg)


def test_frames_of_an_unknown_package_are_dropped():
    _raise_in("thirdparty_secret_pkg")
    try:
        try:
            sys.modules["thirdparty_secret_pkg"].boom("x")
        except ValueError as e:
            assert dg.frames_text(e.__traceback__) == ""
    finally:
        sys.modules.pop("thirdparty_secret_pkg", None)


def test_exception_class_from_an_unknown_package_is_reduced_to_its_builtin_base():
    cls = type("MyClientSecretError", (ValueError,), {})
    cls.__module__ = "some_private_company"
    rec = dg.build(cls("x"))
    assert rec["cls"] == "ValueError"


def test_sanitise_distrusts_the_worker():
    dirty = {"cls": "Bad Name!", "os": "12x", "frames": "C:\\Users\\x\\a.py", "shape": "john smith token abc",
             "hash": "nothex"}
    clean = dg.sanitise(dirty)
    assert clean == {"cls": "", "os": "0", "frames": "", "shape": "token *", "hash": ""} or "john" not in clean["shape"]
    assert "john" not in clean["shape"] and "smith" not in clean["shape"]
    assert dg.sanitise(None)["cls"] == ""
    assert dg.sanitise("nonsense")["cls"] == ""


def test_compose_orders_the_most_useful_first_and_stays_short():
    rec = {"cls": "ValueError", "os": "0", "frames": "core.worker:run:1207", "shape": "invalid value", "hash": "ab12cd34"}
    line = dg.compose(rec, site="worker.segments", device="cuda", duration="1-3h")
    assert line.startswith("E=ValueError site=worker.segments h=ab12cd34 F=core.worker:run:1207")
    assert line.endswith("M=invalid value")
    assert "os=" not in line


def test_duration_bucket_never_gives_the_exact_length():
    assert dg.duration_bucket(None) == "0"
    assert dg.duration_bucket(100) == "<5m"
    assert dg.duration_bucket(3 * 3600 - 1) == "1-3h"
    assert dg.duration_bucket(3 * 3600) == ">3h"
    assert dg.duration_bucket("x") == "0"


def test_remember_keeps_only_the_last_records_and_never_raises(tmp_path):
    path = tmp_path / "sub" / "d.jsonl"
    for i in range(40):
        dg.remember(f"line {i}", path=path, keep=5)
    rows = [json.loads(r)["d"] for r in path.read_text(encoding="utf-8").splitlines()]
    assert rows == [f"line {i}" for i in range(35, 40)]
    dg.remember("x", path=tmp_path / "sub" / "d.jsonl" / "impossible" / "f.jsonl")  # a file used as a folder
