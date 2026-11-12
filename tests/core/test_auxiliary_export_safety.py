"""Generated sidecars and explicit HTML exports preserve unrelated saved text."""
from pathlib import Path
import os
import queue
import threading
from types import SimpleNamespace

import pytest

from app.dialogs import transcript_viewer as viewer
from app.services.download_service import DownloadService
from core.writers import html_transcript
from core import convert


SEGMENTS = [{"start": 0.0, "end": 2.0, "text": "COMPLETE ORIGINAL WORDS"}]


@pytest.fixture
def bilingual(tmp_path, monkeypatch):
    shown, errors = [], []
    fake = SimpleNamespace(
        _closing=False, _bilingual_cancel=None, json_path=str(tmp_path / "talk.json"), media_path="",
        _ai_cancel_btn=SimpleNamespace(pack_forget=lambda: None),
        _ai_progress_var=SimpleNamespace(set=lambda value: None), _set_ai_buttons_busy=lambda busy: None,
    )
    for name in ("showinfo", "showwarning"):
        monkeypatch.setattr(viewer.messagebox, name, lambda title, message, **kwargs: shown.append(message))
    monkeypatch.setattr(viewer, "show_error", lambda *args, **kwargs: errors.append(kwargs))
    return fake, shown, errors


def finish_translation(fake, text="COMPLETE TRANSLATED WORDS"):
    viewer.TranscriptViewer._finish_bilingual_translate(fake, SEGMENTS, [text], "French", None)


def test_bilingual_generation_keeps_previous_manual_translation(tmp_path, bilingual):
    fake, shown, errors = bilingual
    previous = tmp_path / "talk.bilingual.french.srt"
    previous.write_bytes(b"previous manually edited translation")
    finish_translation(fake)
    assert previous.read_bytes() == b"previous manually edited translation"
    output = tmp_path / "talk.bilingual.french (1).srt"
    text = output.read_text(encoding="utf-8")
    assert "COMPLETE ORIGINAL WORDS" in text and "COMPLETE TRANSLATED WORDS" in text
    assert output.name in shown[-1] and not errors


@pytest.mark.parametrize("kind", ["bilingual", "html"])
def test_export_does_not_take_an_existing_recovery_part(tmp_path, bilingual, kind):
    fake, shown, errors = bilingual
    target = tmp_path / ("talk.bilingual.french.srt" if kind == "bilingual" else "talk.html")
    foreign = Path(str(target) + ".part")
    foreign.write_bytes(b"another export's recoverable text")
    if kind == "bilingual":
        finish_translation(fake)
        assert not errors
    else:
        html_transcript.write_page(SEGMENTS, "", out_path=str(target), audio="none")
    assert foreign.read_bytes() == b"another export's recoverable text"
    assert "COMPLETE ORIGINAL WORDS" in target.read_text(encoding="utf-8")


@pytest.mark.parametrize("kind", ["bilingual", "html"])
def test_valid_long_final_names_do_not_require_longer_part_names(tmp_path, bilingual, kind):
    fake, shown, errors = bilingual
    if os.name == "nt":
        tmp_path = Path(chr(92) * 2 + "?" + chr(92) + str(tmp_path.resolve()))
    if kind == "bilingual":
        base = "x" * 232
        fake.json_path = str(tmp_path / (base + ".json"))
        Path(fake.json_path).write_text("[]", encoding="utf-8")
        target = tmp_path / (base + ".bilingual.french.srt")
        finish_translation(fake)
        assert not errors
    else:
        target = tmp_path / ("x" * 247 + ".html")
        target.write_bytes(b"previous explicit target")
        html_transcript.write_page(SEGMENTS, "", out_path=str(target), audio="none")
    assert "COMPLETE ORIGINAL WORDS" in target.read_text(encoding="utf-8")


def test_repeated_bilingual_generation_keeps_both_complete_results(tmp_path, bilingual):
    fake, shown, errors = bilingual
    finish_translation(fake, "FIRST TRANSLATION")
    first = tmp_path / "talk.bilingual.french.srt"
    original = first.read_bytes()
    finish_translation(fake, "SECOND TRANSLATION")
    assert first.read_bytes() == original
    second = tmp_path / "talk.bilingual.french (1).srt"
    assert "SECOND TRANSLATION" in second.read_text(encoding="utf-8")
    assert second.name in shown[-1] and not errors


def test_page_description_keeps_previous_edited_file(tmp_path):
    events = queue.Queue()
    fake = SimpleNamespace(app=SimpleNamespace(download_events=events))
    task = SimpleNamespace(folder=str(tmp_path))
    episode = SimpleNamespace(transcript_text="COMPLETE PAGE DESCRIPTION")
    previous = tmp_path / "clip.description.txt"
    previous.write_bytes(b"previous edited page description")
    DownloadService._write_smtv_transcript(fake, task, episode, "clip.mp4")
    assert previous.read_bytes() == b"previous edited page description"
    output = tmp_path / "clip.description (1).txt"
    assert output.read_bytes() == b"COMPLETE PAGE DESCRIPTION\n"
    assert output.name in events.get_nowait()[2]


@pytest.mark.parametrize("kind", ["bilingual", "html", "description"])
@pytest.mark.parametrize("failure", [OSError, convert.ConvertError])
def test_failed_publication_preserves_previous_files_and_reports_failure(
    tmp_path, bilingual, monkeypatch, kind, failure,
):
    fake, shown, errors = bilingual
    names = {"bilingual": "talk.bilingual.french.srt", "html": "talk.html",
             "description": "clip.description.txt"}
    target = tmp_path / names[kind]
    target.write_bytes(b"previous saved or edited output")
    foreign = Path(str(target) + ".part")
    foreign.write_bytes(b"other operation's recovery text")
    attempts = []

    def fail_publish(staged, destination):
        assert Path(staged).stat().st_size > 0
        attempts.append(str(staged))
        raise failure("synthetic auxiliary publication failure")

    if kind == "html":
        monkeypatch.setattr(convert.os, "replace", fail_publish)
        with pytest.raises(failure, match="synthetic auxiliary"):
            html_transcript.write_page(SEGMENTS, "", out_path=str(target), audio="none")
    else:
        monkeypatch.setattr(convert, "_install_new_output", fail_publish)
        if kind == "bilingual":
            finish_translation(fake)
            assert len(errors) == 1 and not shown
        else:
            events = queue.Queue()
            actor = SimpleNamespace(app=SimpleNamespace(download_events=events))
            DownloadService._write_smtv_transcript(actor, SimpleNamespace(folder=str(tmp_path)),
                                                  SimpleNamespace(transcript_text="NEW DESCRIPTION"), "clip.mp4")
            assert "write failed" in events.get_nowait()[2]
    assert attempts
    assert target.read_bytes() == b"previous saved or edited output"
    assert foreign.read_bytes() == b"other operation's recovery text"
    assert list(tmp_path.glob("*.part")) == [foreign]


def test_cancelled_bilingual_result_does_not_change_previous_output(tmp_path, bilingual):
    fake, shown, errors = bilingual
    previous = tmp_path / "talk.bilingual.french.srt"
    previous.write_bytes(b"previous manually edited translation")
    fake._bilingual_cancel = threading.Event()
    fake._bilingual_cancel.set()
    finish_translation(fake)
    assert previous.read_bytes() == b"previous manually edited translation"
    assert list(tmp_path.glob("*.srt")) == [previous]
    assert len(shown) == 1 and not errors


def test_blank_page_description_leaves_previous_file_alone(tmp_path):
    previous = tmp_path / "clip.description.txt"
    previous.write_bytes(b"previous edited page description")
    events = queue.Queue()
    actor = SimpleNamespace(app=SimpleNamespace(download_events=events))
    DownloadService._write_smtv_transcript(actor, SimpleNamespace(folder=str(tmp_path)),
                                          SimpleNamespace(transcript_text=" \n "), "clip.mp4")
    assert previous.read_bytes() == b"previous edited page description" and events.empty()
