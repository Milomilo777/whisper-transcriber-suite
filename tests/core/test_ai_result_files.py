"""Successful AI responses use independent, verifiable plain-text copies."""
from pathlib import Path
import errno

from core import config, llm


def test_save_result_keeps_unicode_text_and_source_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "user_data_dir", lambda: tmp_path)
    body = "\u0633\u0644\u0627\u0645 \u4e16\u754c\nA complete answer"
    result = llm.save_ai_result(body, action="Ask", source_json="transcript (1).json", language="fa")
    assert result.text == body and not result.save_error
    text = Path(result.saved_path).read_text(encoding="utf-8")
    assert text.endswith(body)
    assert "AI action: Ask" in text and '"transcript (1).json"' in text
    assert "Result language: fa" in text
    assert llm.ai_result_is_saved(result)
    assert Path(result.saved_path).parent == tmp_path / "ai-results"


def test_failed_profile_save_keeps_text_for_file_only_retry(tmp_path, monkeypatch):
    blocked = tmp_path / "blocked"
    blocked.write_bytes(b"unrelated original")
    monkeypatch.setattr(config, "user_data_dir", lambda: blocked)
    result = llm.save_ai_result("completed response", action="Summarise", source_json="source.json")
    assert result.text == "completed response" and result.save_error and not result.saved_path
    assert blocked.read_bytes() == b"unrelated original"
    monkeypatch.setattr(config, "user_data_dir", lambda: tmp_path / "restored")
    retried = llm.retry_save_ai_result(result)
    assert retried.text == result.text and retried.source_json == result.source_json
    assert llm.ai_result_is_saved(retried)


def test_edited_recovery_is_preserved_and_new_copy_keeps_original_response(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "user_data_dir", lambda: tmp_path)
    result = llm.save_ai_result("provider response", action="Translate", source_json="source.json")
    previous = Path(result.saved_path)
    previous.write_text("edited owner translation", encoding="utf-8")
    assert not llm.ai_result_is_saved(result)
    retried = llm.retry_save_ai_result(result)
    assert previous.read_text(encoding="utf-8") == "edited owner translation"
    assert retried.saved_path != result.saved_path
    assert Path(retried.saved_path).read_text(encoding="utf-8").endswith("provider response")


def test_retry_of_verified_result_does_not_create_duplicate(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "user_data_dir", lambda: tmp_path)
    result = llm.save_ai_result("finished", action="Action items", source_json="source.json")
    retried = llm.retry_save_ai_result(result)
    assert retried.saved_path == result.saved_path
    assert len(list((tmp_path / "ai-results").glob("*.txt"))) == 1


def test_native_publication_refusal_does_not_claim_a_saved_result(tmp_path, monkeypatch):
    from core import convert
    monkeypatch.setattr(config, "user_data_dir", lambda: tmp_path)
    attempts = []
    def refuse(staged, target):
        attempts.append(staged)
        assert Path(staged).read_bytes().endswith(b"finished text")
        raise PermissionError(errno.EACCES, "synthetic publication refusal")
    monkeypatch.setattr(convert, "_install_new_output", refuse)
    result = llm.save_ai_result("finished text", action="Summarise", source_json="source.json")
    assert attempts and not result.saved_path and result.save_error
    assert result.text == "finished text"


def test_failed_strict_sync_does_not_advertise_or_remove_new_copy(tmp_path, monkeypatch):
    from core import _checkpoint
    monkeypatch.setattr(config, "user_data_dir", lambda: tmp_path)
    def refuse(stream):
        raise OSError(errno.EIO, "synthetic recovery sync refusal")
    monkeypatch.setattr(_checkpoint, "_strict_sync", refuse)
    result = llm.save_ai_result("finished text", action="Ask", source_json="source.json")
    assert not result.saved_path and result.save_error
    saved, = (tmp_path / "ai-results").glob("*.txt")
    assert saved.read_text(encoding="utf-8").endswith("finished text")


def test_collision_does_not_overwrite_prior_copy(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(config, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(llm.uuid, "uuid4", lambda: SimpleNamespace(hex="fixed-id"))
    first = llm.save_ai_result("first response", action="Ask", source_json="first.json")
    second = llm.save_ai_result("second response", action="Ask", source_json="second.json")
    assert first.saved_path != second.saved_path
    assert Path(first.saved_path).read_text(encoding="utf-8").endswith("first response")
    assert Path(second.saved_path).read_text(encoding="utf-8").endswith("second response")


def test_edit_between_verification_and_sync_creates_a_new_copy(tmp_path, monkeypatch):
    import builtins
    monkeypatch.setattr(config, "user_data_dir", lambda: tmp_path)
    result = llm.save_ai_result("original completed answer", action="Ask", source_json="source.json")
    prior = Path(result.saved_path)
    original_open = builtins.open
    edited = []
    def edit_before_open(path, mode="r", *args, **kwargs):
        if str(path) == str(prior) and mode == "r+b" and not edited:
            edited.append(True)
            prior.write_text("owner edit arrived before verification handle", encoding="utf-8")
        return original_open(path, mode, *args, **kwargs)
    monkeypatch.setattr(builtins, "open", edit_before_open)
    retried = llm.retry_save_ai_result(result)
    assert edited and retried.saved_path != result.saved_path
    assert prior.read_text(encoding="utf-8") == "owner edit arrived before verification handle"
    assert Path(retried.saved_path).read_text(encoding="utf-8").endswith("original completed answer")


def test_corrupted_published_copy_is_not_advertised_or_deleted(tmp_path, monkeypatch):
    from core import convert
    monkeypatch.setattr(config, "user_data_dir", lambda: tmp_path)
    publish = convert._publish_new_output
    changed = []
    def corrupt(path, payload):
        saved = publish(path, payload)
        Path(saved).write_bytes(b"synthetic post-publication edit")
        changed.append(saved)
        return saved
    monkeypatch.setattr(convert, "_publish_new_output", corrupt)
    result = llm.save_ai_result("completed response", action="Ask", source_json="source.json")
    assert result.save_error and not result.saved_path
    assert result.text == "completed response"
    assert Path(changed[0]).read_bytes() == b"synthetic post-publication edit"


def test_ai_result_copies_are_not_reaped_by_checkpoint_sweep(tmp_path, monkeypatch):
    import os
    from core import _checkpoint
    monkeypatch.setattr(config, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(_checkpoint, "user_data_dir", lambda: tmp_path)
    result = llm.save_ai_result("retained complete answer", action="Ask", source_json="source.json")
    path = Path(result.saved_path)
    original = path.read_bytes()
    os.utime(path, (1, 1))
    _checkpoint.sweep_partials(max_age_days=0, slice_max_age_minutes=0)
    assert path.read_bytes() == original
