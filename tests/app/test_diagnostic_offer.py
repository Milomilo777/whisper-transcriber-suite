"""The rules of the quiet failure-details offer (no Tk: the bar itself is replaced)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.services import diagnostic_offer as mod
from app.services.diagnostic_offer import DiagnosticOffer
from core import diagnostic


def _task(cls="ValueError", shape="invalid value", frames="core.worker:run:10", code="none"):
    record = diagnostic.sanitise({"cls": cls, "os": "0", "frames": frames, "shape": shape,
                                  "hash": "ab12cd34"})
    return SimpleNamespace(
        failure_diag=record, audio_duration=4000.0,
        failure_clue={"observed_code": code, "failure_site": "worker.segments", "device": "cuda"},
    )


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostic, "log_path", lambda: tmp_path / "diagnostics.jsonl")
    monkeypatch.setattr(mod.offline, "is_offline", lambda cfg=None: bool((cfg or {}).get("work_offline")))
    shown, scheduled = [], []
    cfg = {"telemetry_opt_in": True, "diagnostic_offer": True, "diagnostic_offer_last": 0.0,
           "stats_url": "https://example.test/stats", "work_offline": False}
    app = SimpleNamespace(app_config=cfg, _closing=False, busy=False,
                          after=lambda ms, fn: scheduled.append(fn), _jobs_active=lambda: app.busy)
    offer = DiagnosticOffer(app, clock=lambda: 1_000_000.0)
    monkeypatch.setattr(offer, "_show", lambda: (shown.append(offer.lines()), setattr(offer, "_offered_this_session", True),
                                                   offer._seen.update(offer._pending)))

    def run():
        while scheduled:
            scheduled.pop(0)()
    return SimpleNamespace(app=app, offer=offer, shown=shown, run=run, cfg=cfg, tmp=tmp_path)


def test_unexplained_failure_is_offered_once_the_queue_is_idle(env):
    env.offer.note(_task())
    env.run()
    assert len(env.shown) == 1
    assert env.shown[0][0].startswith("E=ValueError site=worker.segments h=ab12cd34")


def test_busy_queue_delays_the_offer_until_idle(env):
    env.app.busy = True
    env.offer.note(_task())
    # one tick while busy: nothing shown, a new tick is queued
    env.offer._tick()
    assert env.shown == []
    env.app.busy = False
    env.offer._tick()
    assert len(env.shown) == 1


def test_known_cause_is_not_offered(env):
    env.offer.note(_task(code="disk_full"))
    env.run()
    assert env.shown == []


@pytest.mark.parametrize("key,value", [
    ("telemetry_opt_in", False), ("diagnostic_offer", False), ("work_offline", True), ("stats_url", ""),
    ("diagnostic_offer_last", 1_000_000.0 - 3600),
])
def test_switches_and_cooldown_block_the_offer(env, key, value):
    env.cfg[key] = value
    env.offer.note(_task())
    env.run()
    assert env.shown == []


def test_cooldown_ends_after_a_day(env):
    env.cfg["diagnostic_offer_last"] = 1_000_000.0 - 24 * 3600 - 1
    env.offer.note(_task())
    env.run()
    assert len(env.shown) == 1


def test_same_failure_ten_times_is_one_offer_and_different_ones_share_it(env):
    for _ in range(10):
        env.offer.note(_task())
    env.offer.note(_task(cls="KeyError", frames="core.worker:run:99"))
    env.run()
    assert len(env.shown) == 1 and len(env.shown[0]) == 2


def test_only_one_offer_per_session(env):
    env.offer.note(_task())
    env.run()
    env.offer.note(_task(cls="KeyError", frames="core.x:y:1"))
    env.run()
    assert len(env.shown) == 1


def test_the_local_file_is_written_even_when_nothing_is_offered(env):
    env.cfg["telemetry_opt_in"] = False
    env.offer.note(_task())
    rows = (env.tmp / "diagnostics.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1 and json.loads(rows[0])["d"].startswith("E=ValueError")


def test_no_record_means_nothing_happens(env):
    env.offer.note(SimpleNamespace(failure_diag=None, failure_clue={}))
    env.run()
    assert env.shown == [] and not (env.tmp / "diagnostics.jsonl").exists()


def test_never_turns_the_offer_off_for_good(env, monkeypatch):
    monkeypatch.setattr(env.offer, "_save", lambda: None)
    monkeypatch.setattr(env.offer, "_close_bar", lambda: None)
    env.offer.never()
    assert env.cfg["diagnostic_offer"] is False


def test_send_uses_the_problem_report_path_with_the_exact_shown_text(env, monkeypatch):
    sent = []
    monkeypatch.setattr(mod.pr, "send", lambda cfg, text: sent.append(text))
    monkeypatch.setattr(mod, "safe_thread", lambda fn, **k: fn())
    monkeypatch.setattr(env.offer, "_close_bar", lambda: None)
    env.app.after = lambda ms, fn: None
    env.offer.note(_task())
    shown_text = env.offer.lines()
    env.offer.send()
    assert sent == ["[auto] " + t for t in shown_text]
    assert env.offer.lines() == []
