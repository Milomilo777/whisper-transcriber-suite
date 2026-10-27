"""Finish hand-offs, round 3: other output formats, redirects, vault paths, names, privacy."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from core import finish_hooks as fh
from tests.core.test_finish_hooks import (  # noqa: F401  (fixtures are used by name)
    SEGMENTS,
    _config,
    _job,
    _online,
    receiver,
)


# --- notes from any written format ------------------------------------------

def _deliver_files(tmp_path: Path, names_and_text: dict[str, str]) -> list[str]:
    paths = []
    for name, text in names_and_text.items():
        p = tmp_path / name
        p.write_text(text, encoding="utf-8")
        paths.append(str(p))
    return paths


def test_txt_only_job_still_gets_a_note_without_fake_timestamps(tmp_path: Path) -> None:
    paths = _deliver_files(tmp_path, {"talk.txt": "First line.\nSecond line.\n"})
    fh.deliver(_config(tmp_path), _job(tmp_path, output_paths=paths))
    note = (tmp_path / "vault" / "My talk.md").read_text(encoding="utf-8")
    assert "First line." in note and "Second line." in note
    assert "**00:00:00**" not in note


def test_md_only_job_keeps_its_timestamps(tmp_path: Path) -> None:
    md = "# t\n\n**00:00:03** Hello.\n\n**00:01:05** _Ann:_ Later.\n"
    paths = _deliver_files(tmp_path, {"talk.md": md})
    fh.deliver(_config(tmp_path), _job(tmp_path, output_paths=paths))
    note = (tmp_path / "vault" / "My talk.md").read_text(encoding="utf-8")
    assert "**00:00:03** Hello." in note
    assert "**00:01:05** _Ann:_ Later." in note


def test_lrc_only_job_keeps_its_timestamps(tmp_path: Path) -> None:
    paths = _deliver_files(tmp_path, {"talk.lrc": "[00:03.50]Hello.\n[01:05.00]Later.\n"})
    fh.deliver(_config(tmp_path), _job(tmp_path, output_paths=paths))
    note = (tmp_path / "vault" / "My talk.md").read_text(encoding="utf-8")
    assert "**00:00:03** Hello." in note and "**00:01:05** Later." in note


def test_docx_only_job_gets_a_note(tmp_path: Path) -> None:
    docx = pytest.importorskip("docx")
    doc = docx.Document()
    doc.add_paragraph("Words from a Word file.")
    path = tmp_path / "talk.docx"
    doc.save(str(path))
    fh.deliver(_config(tmp_path), _job(tmp_path, output_paths=[str(path)]))
    assert "Words from a Word file." in (
        tmp_path / "vault" / "My talk.md").read_text(encoding="utf-8")


def test_webhook_text_comes_from_a_txt_only_job(tmp_path: Path, receiver) -> None:
    r = receiver()
    paths = _deliver_files(tmp_path, {"talk.txt": "Only text here.\n"})
    cfg = _config(tmp_path, r.url, finish_webhook_include_text=True, obsidian_vault_dir="")
    fh.deliver(cfg, _job(tmp_path, output_paths=paths))
    assert "Only text here." in r.requests[0]["body"]["transcript"]


def test_unreadable_outputs_log_the_real_reason(
        tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    paths = _deliver_files(tmp_path, {"talk.pdf": "%PDF not a transcript"})
    with caplog.at_level(logging.INFO, logger="core.finish_hooks"):
        fh.deliver(_config(tmp_path), _job(tmp_path, output_paths=paths))
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "no readable transcript" in text
    assert "no text" not in text


# --- redirects and status codes ---------------------------------------------

def _send(url: str, tmp_path: Path) -> bool:
    return fh.send_webhook(url, _job(tmp_path), secret="", include_text=False,
                           segments=[], sleep=lambda s: None)


def test_a_redirect_is_delivered_not_retried_and_not_followed(
        tmp_path: Path, receiver) -> None:
    r = receiver([302])
    assert _send(r.url, tmp_path) is True
    assert len(r.requests) == 1


def test_a_client_error_is_not_retried(tmp_path: Path, receiver) -> None:
    r = receiver([404])
    assert _send(r.url, tmp_path) is False
    assert len(r.requests) == 1


def test_a_server_error_is_retried_once(tmp_path: Path, receiver) -> None:
    r = receiver([503])
    assert _send(r.url, tmp_path) is False
    assert len(r.requests) == 2


def test_a_dropped_connection_is_retried_once(tmp_path: Path) -> None:
    calls: list[int] = []

    def refuse(request: Any, timeout: float) -> None:
        calls.append(1)
        raise ConnectionRefusedError("down")

    ok = fh.send_webhook("https://example.com/h", _job(tmp_path), secret="",
                         include_text=False, segments=[], sleep=lambda s: None,
                         opener=refuse)
    assert ok is False and len(calls) == 2


# --- the vault path ----------------------------------------------------------

@pytest.mark.parametrize("raw", ['"{p}"', "'{p}'", '  "{p}"  ', "{p}"])
def test_quoted_vault_path_is_cleaned(tmp_path: Path, raw: str) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    assert fh.resolve_vault_dir(raw.format(p=vault)) == str(vault)


def test_vault_path_expands_the_home_folder(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert fh.resolve_vault_dir("~/Notes") == str(tmp_path / "Notes")


def test_relative_vault_path_is_refused_with_a_log_line(
        caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="core.finish_hooks"):
        assert fh.resolve_vault_dir("notes/vault") is None
    assert "absolute" in " ".join(r.getMessage() for r in caplog.records)


def test_deliver_uses_a_quoted_vault_path(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    paths = _deliver_files(tmp_path, {"talk.txt": "Hi there.\n"})
    fh.deliver({"obsidian_vault_dir": f'"{vault}"'}, _job(tmp_path, output_paths=paths))
    assert (vault / "My talk.md").is_file()


def test_the_dialog_warns_about_a_missing_vault_and_stores_it_clean(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.dialogs import advanced as adv
    from tests.core.test_advanced_simplified import _base_cfg, _fake_app, _fake_dialog, _V

    warned: list[str] = []
    from tkinter import messagebox
    monkeypatch.setattr(messagebox, "showwarning", lambda *a, **k: warned.append(a[0]))
    monkeypatch.setattr(adv, "save_config", lambda _c: None)
    cfg = _base_cfg()
    missing = tmp_path / "nope"
    adv.AdvancedDialog._save_and_close(  # type: ignore[arg-type]
        _fake_dialog(_fake_app(cfg), _obsidian_vault_dir=_V(f' "{missing}" ')))
    assert len(warned) == 1
    assert cfg["obsidian_vault_dir"] == str(missing)

    warned.clear()
    present = tmp_path / "there"
    present.mkdir()
    adv.AdvancedDialog._save_and_close(  # type: ignore[arg-type]
        _fake_dialog(_fake_app(_base_cfg()), _obsidian_vault_dir=_V(str(present))))
    assert warned == []


# --- file names --------------------------------------------------------------

def test_stem_is_limited_by_utf8_bytes() -> None:
    for raw in ("é" * 300, "کتاب" * 100, "日本語" * 100, "a" * 300):
        stem = fh.safe_note_stem(raw)
        assert len(stem.encode("utf-8")) <= 200
        assert stem == stem.strip(" .") and stem
        stem.encode("utf-8")  # whole characters only


@pytest.mark.parametrize("raw", [
    "CON .txt", "con.", "NUL  ", "COM1 . x", "COM¹", "lpt².log", "COM³",
    "CONIN$", "conout$", "CONIN$.txt", "AUX.tar.gz",
])
def test_more_reserved_windows_names_are_prefixed(raw: str) -> None:
    assert fh.safe_note_stem(raw).startswith("_")


@pytest.mark.parametrize("raw", ["CONSOLE", "COM10", "Concert", "NULL", "AUXILIARY"])
def test_ordinary_names_are_left_alone(raw: str) -> None:
    assert fh.safe_note_stem(raw) == raw


# --- privacy -----------------------------------------------------------------

def test_signed_url_parameters_are_removed_from_the_note(tmp_path: Path) -> None:
    url = ("https://user:pw@cdn.example.com/v/clip.mp4?v=abc123&X-Amz-Signature=SECRET"
           "&token=SECRET2&Expires=1&t=30#frag")
    text = fh.build_note(SEGMENTS, _job(tmp_path, source=url))
    assert "SECRET" not in text and "pw@" not in text and "frag" not in text
    assert "https://cdn.example.com/v/clip.mp4?v=abc123&t=30" in text


def test_a_plain_video_link_keeps_its_id(tmp_path: Path) -> None:
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert f'source: "{url}"' in fh.build_note(SEGMENTS, _job(tmp_path, source=url))


def test_markdown_link_is_not_broken_by_parentheses(tmp_path: Path) -> None:
    url = "https://example.com/a_(b)?x=1"
    text = fh.build_note(SEGMENTS, _job(tmp_path, source=url))
    assert "](https://example.com/a_%28b%29?x=1)" in text
    assert text.count("](") == 1


def test_payload_has_names_not_folders(tmp_path: Path) -> None:
    payload = fh.webhook_payload(
        _job(tmp_path, output_paths=[str(tmp_path / "Users" / "Jane" / "a.srt")]),
        include_text=False, segments=[])
    assert payload["outputs"] == ["a.srt"]
    assert "Jane" not in json.dumps(payload)
