"""Opt-out stays responsive; technical excerpts never retain private spans."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import config, diagnostic, stats


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_path", lambda: str(tmp_path / "config.json"))
    monkeypatch.setattr(diagnostic, "log_path", lambda: tmp_path / "diagnostics.jsonl")
    yield
    done = getattr(stats, "_ERASURE_DONE", None)
    if done is not None:
        assert done.wait(3), "Owned erasure worker did not finish before profile teardown"


def test_opt_out_returns_while_actual_sender_is_blocked(monkeypatch):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    cfg = {"telemetry_opt_in": True, "telemetry_notice_version": 2, "stats_url": "https://example.invalid/v1/runs"}

    def blocked(*args):
        entered.set()
        release.wait(1.0)
        finished.set()

    monkeypatch.setattr(stats, "_post", blocked)
    row = stats.build_stats_payload(model="base", language="en", audio_duration=1,
                                    transcription_time=1, status="finished")
    assert stats.post_stats_async(cfg, row)
    assert entered.wait(2)
    try:
        assert stats._ERROR_LOCK.acquire(timeout=0.1), "The network request holds the local-state lock"
        stats._ERROR_LOCK.release()
        cfg["telemetry_opt_in"] = False
        start = time.monotonic()
        stats.forget_install_id(cfg)
        assert time.monotonic() - start < 0.2, "Opt-out waited for an in-flight HTTP request"
    finally:
        release.set()
        assert finished.wait(2)


def test_disk_erasure_runs_off_the_caller_thread(monkeypatch, tmp_path):
    rate = tmp_path / "telemetry-errors.json"
    rate.write_text("{}", encoding="utf-8")
    main = threading.get_ident()
    called = []
    original = Path.unlink

    def slow_unlink(path, *args, **kwargs):
        if path == rate:
            called.append(threading.get_ident())
            time.sleep(0.3)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", slow_unlink)
    start = time.monotonic()
    stats.forget_install_id({"telemetry_opt_in": False})
    assert time.monotonic() - start < 0.2, "The caller performed disk erasure"
    done = getattr(stats, "_ERASURE_DONE", None)
    if done is not None:
        assert done.wait(2)
    assert called and all(identity != main for identity in called)
    assert not rate.exists()


def test_opt_out_erases_previously_collected_diagnostics(tmp_path):
    path = tmp_path / "diagnostics.jsonl"
    path.write_text('{"d":"old technical excerpt"}\n', encoding="utf-8")
    stats.forget_install_id({"telemetry_opt_in": False})
    done = getattr(stats, "_ERASURE_DONE", None)
    if done is not None:
        assert done.wait(2)
    assert not path.exists()


@pytest.mark.parametrize("message", [
    r"cannot open 'D:\Private\Last Will Audio.mp3'",
    'cannot open "private last will audio mp3"',
    'cannot open “private last will audio mp3”',
    'cannot open «private last will audio mp3»',
    "cannot open b'private last will audio mp3'",
    "cannot open rb'private last will audio mp3'",
    "cannot open f'private last will audio mp3'",
    r"cannot open D:\Private\Last Will Audio.mp3",
    "cannot open /private/last will audio.mp3",
    "cannot open private/last will audio.mp3",
])
def test_private_spans_do_not_turn_into_allowed_vocabulary(message):
    shape = diagnostic.message_shape(message)
    assert not set(shape.split()) & {"private", "last", "will", "audio", "mp3"}, shape


def test_quoted_title_property():
    hypothesis = pytest.importorskip("hypothesis")
    strategies = pytest.importorskip("hypothesis.strategies")

    @hypothesis.given(strategies.lists(strategies.sampled_from(
        ["private", "last", "will", "audio", "video", "name", "cookies"]), min_size=1, max_size=8))
    @hypothesis.settings(max_examples=75, deadline=None)
    def check(words):
        for left, right in [('"', '"'), ("'", "'"), ("“", "”"), ("«", "»"), ("`", "`")]:
            shape = diagnostic.message_shape("cannot open " + left + " ".join(words) + right)
            assert not set(words) & set(shape.split())

    check()


def test_saved_opt_out_blocks_another_stale_config_copy(monkeypatch, tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"telemetry_opt_in": False}), encoding="utf-8")
    calls, finished = [], threading.Event()

    def posted(*args):
        calls.append(args)
        finished.set()

    monkeypatch.setattr(stats, "_post", posted)
    cfg = {"telemetry_opt_in": True, "telemetry_notice_version": 2, "stats_url": "https://example.invalid/v1/runs"}
    row = stats.build_stats_payload(model="base", language="en", audio_duration=1,
                                    transcription_time=1, status="finished")
    stats.post_stats_async(cfg, row)
    assert not finished.wait(0.2)
    assert calls == []


def test_failed_diagnostic_send_does_not_claim_nothing_was_lost(monkeypatch):
    from app.services.diagnostic_offer import DiagnosticOffer
    from app.widgets import notice

    shown = []
    monkeypatch.setattr(notice, "notify", lambda app, text: shown.append(text))
    offer = DiagnosticOffer(SimpleNamespace())
    offer._after_send(False)
    assert shown and "Nothing was lost" not in shown[0]


def test_cancelled_reservation_never_reaches_the_network(monkeypatch):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    calls = []
    cfg = {"telemetry_opt_in": True, "telemetry_notice_version": 2, "stats_url": "https://example.invalid/v1/runs",
           "install_id": "00000000-0000-4000-8000-000000000000"}

    def reserve(row, *args):
        entered.set()
        assert release.wait(2)
        finished.set()
        return row

    monkeypatch.setattr(stats, "limit_error_row", reserve)
    monkeypatch.setattr(stats, "_post", lambda *args: calls.append(args))
    row = stats.build_stats_payload(model="base", language="en", audio_duration=0,
                                    transcription_time=0, status="error")
    assert stats.post_stats_async(cfg, row)
    assert entered.wait(2)
    try:
        cfg["telemetry_opt_in"] = False
        stats.forget_install_id(cfg)
        cfg["telemetry_opt_in"] = True  # Even a quick re-enable cannot revive it.
    finally:
        release.set()
    assert finished.wait(2)
    assert stats._ERASURE_DONE.wait(2)
    assert calls == []


def test_reenable_waits_for_old_cleanup_before_new_state(monkeypatch, tmp_path):
    entered, release, sent = threading.Event(), threading.Event(), threading.Event()
    path = tmp_path / "diagnostics.jsonl"
    path.write_text("old", encoding="utf-8")
    original = Path.unlink

    def blocked(path_arg, *args, **kwargs):
        if path_arg == path:
            entered.set()
            assert release.wait(2)
        return original(path_arg, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", blocked)
    monkeypatch.setattr(stats, "_post", lambda *args: sent.set())
    cfg = {"telemetry_opt_in": False, "telemetry_notice_version": 2, "stats_url": "https://example.invalid/v1/runs"}
    stats.forget_install_id(cfg)
    assert entered.wait(2)
    try:
        cfg["telemetry_opt_in"] = True
        assert not stats.diagnostics_enabled(cfg)
        row = stats.build_stats_payload(model="base", language="en", audio_duration=1,
                                        transcription_time=1, status="finished")
        assert stats.post_stats_async(cfg, row)
        assert not sent.wait(0.1)
    finally:
        release.set()
    assert sent.wait(2)
    assert stats.diagnostics_enabled(cfg)
    diagnostic.remember("new technical excerpt")
    assert "new technical excerpt" in path.read_text(encoding="utf-8")


def test_erasure_io_failure_does_not_poison_next_cleanup(monkeypatch, tmp_path):
    original = Path.unlink
    path = tmp_path / "telemetry-errors.json"
    path.write_text("{}", encoding="utf-8")

    def denied(target, *args, **kwargs):
        if target == path:
            raise PermissionError("test denial")
        return original(target, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", denied)
    stats.forget_install_id({"telemetry_opt_in": False})
    assert stats._ERASURE_DONE.wait(2)
    assert path.exists()
    monkeypatch.setattr(Path, "unlink", original)
    stats.forget_install_id({"telemetry_opt_in": False})
    assert stats._ERASURE_DONE.wait(2)
    assert not path.exists()


@pytest.mark.parametrize("raw", ['{', '[]', '{"telemetry_opt_in":"false"}', 'x' * (1024 * 1024 + 1)],
                         ids=["malformed-json", "wrong-container", "nonboolean-consent", "oversized"])
def test_unreadable_saved_consent_fails_closed(tmp_path, raw):
    path = tmp_path / "config.json"
    path.write_text(raw, encoding="utf-8")
    assert not stats._saved_consent_allows(path)


def test_filter_preserves_technical_codes_but_removes_unclosed_quotes():
    assert "winerror 5" in diagnostic.message_shape("[WinError 5] Access is denied")
    assert "private" not in diagnostic.message_shape('cannot open "private last will audio')
    assert "private" not in diagnostic.message_shape("cannot open ‘private last will audio’")
    assert diagnostic.message_shape("a" * 16384) == "*"


@pytest.mark.parametrize("reenable", [False, True])
def test_opt_out_during_final_disk_read_invalidates_send(monkeypatch, reenable):
    entered, release = threading.Event(), threading.Event()
    calls, threads = [], []
    original = threading.Thread
    reads = 0

    def tracked(*args, **kwargs):
        thread = original(*args, **kwargs)
        threads.append(thread)
        return thread

    def consent(path):
        nonlocal reads
        reads += 1
        if reads == 2:
            entered.set()
            assert release.wait(2)
        return True

    monkeypatch.setattr(stats.threading, "Thread", tracked)
    monkeypatch.setattr(stats, "_saved_consent_allows", consent)
    monkeypatch.setattr(stats, "_post", lambda *args: calls.append(args))
    cfg = {"telemetry_opt_in": True, "telemetry_notice_version": 2, "stats_url": "https://example.invalid/v1/runs"}
    row = stats.build_stats_payload(model="base", language="en", audio_duration=1,
                                    transcription_time=1, status="finished")
    assert stats.post_stats_async(cfg, row)
    assert entered.wait(2)
    try:
        cfg["telemetry_opt_in"] = False
        stats.forget_install_id(cfg)
        cfg["telemetry_opt_in"] = reenable
    finally:
        release.set()
    for thread in threads:
        thread.join(2)
        assert not thread.is_alive()
    assert calls == []
