"""The star invitation rules (core.star_invite), tested without Tk."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from core import config as cfg_mod
from core import star_invite as s

_FIRST = date(2026, 10, 1)


def _ready(**over):
    """A config that is eligible on _FIRST + 7 days."""
    config = {
        s.KEY_FIRST_RUN: _FIRST.isoformat(),
        s.KEY_JOBS: s.MIN_JOBS,
        s.KEY_SHOWN: 0,
        s.KEY_LAST_SHOWN: "",
        s.KEY_DONT_ASK: False,
    }
    config.update(over)
    return config


def _ask(config, today=_FIRST + timedelta(days=s.MIN_DAYS), **kw):
    kw.setdefault("job_running", False)
    kw.setdefault("offline", False)
    return s.should_invite(config, today, **kw)


# ------------------------------------------------------------------ thresholds

def test_all_conditions_met_invites():
    assert _ask(_ready()) is True


def test_one_job_short_does_not_invite():
    assert _ask(_ready(**{s.KEY_JOBS: s.MIN_JOBS - 1})) is False


def test_one_day_short_does_not_invite():
    assert _ask(_ready(), today=_FIRST + timedelta(days=s.MIN_DAYS - 1)) is False


def test_many_jobs_but_a_new_install_does_not_invite():
    assert _ask(_ready(**{s.KEY_JOBS: 500}), today=_FIRST) is False


def test_old_install_but_few_jobs_does_not_invite():
    assert _ask(_ready(**{s.KEY_JOBS: 1}), today=_FIRST + timedelta(days=400)) is False


def test_missing_first_run_date_does_not_invite():
    assert _ask(_ready(**{s.KEY_FIRST_RUN: ""})) is False
    assert _ask(_ready(**{s.KEY_FIRST_RUN: "not a date"})) is False


# ------------------------------------------------------- never when it must not

def test_never_during_a_running_job():
    assert _ask(_ready(), job_running=True) is False


def test_never_in_offline_mode():
    assert _ask(_ready(), offline=True) is False


def test_dont_ask_again_stops_it_for_good():
    config = _ready()
    s.decline(config)
    assert _ask(config, today=_FIRST + timedelta(days=1000)) is False


def test_only_a_real_true_counts_as_dont_ask():
    # A hand-edited string must not silently disable the feature in either direction.
    assert _ask(_ready(**{s.KEY_DONT_ASK: "yes"})) is True


# ------------------------------------------------------------------ at most two

def test_at_most_two_times_ever():
    config = _ready()
    today = _FIRST + timedelta(days=s.MIN_DAYS)
    s.mark_shown(config, today)
    later = today + timedelta(days=s.MIN_GAP_DAYS)
    assert _ask(config, today=later) is True
    s.mark_shown(config, later)
    assert config[s.KEY_SHOWN] == 2
    assert _ask(config, today=later + timedelta(days=3650)) is False


def test_second_invitation_waits_for_the_gap():
    config = _ready()
    today = _FIRST + timedelta(days=s.MIN_DAYS)
    s.mark_shown(config, today)
    assert _ask(config, today=today + timedelta(days=s.MIN_GAP_DAYS - 1)) is False
    assert _ask(config, today=today + timedelta(days=s.MIN_GAP_DAYS)) is True


def test_a_bad_last_shown_date_never_lets_the_second_ask_through_at_once():
    config = _ready(**{s.KEY_SHOWN: 1, s.KEY_LAST_SHOWN: "garbage"})
    assert _ask(config) is False
    future = (_FIRST + timedelta(days=500)).isoformat()
    assert _ask(_ready(**{s.KEY_SHOWN: 1, s.KEY_LAST_SHOWN: future})) is False


def test_a_shown_count_already_at_the_limit_stops_it_even_without_a_date():
    assert _ask(_ready(**{s.KEY_SHOWN: s.MAX_INVITES})) is False


# ---------------------------------------------------------------------- counters

def test_record_success_counts_and_stamps_first_run():
    config: dict = {}
    s.record_success(config, _FIRST)
    s.record_success(config, _FIRST + timedelta(days=2))
    assert config[s.KEY_JOBS] == 2
    assert config[s.KEY_FIRST_RUN] == _FIRST.isoformat()


@pytest.mark.parametrize("bad", ["3", 2.5, None, True, -4, [1]])
def test_a_damaged_counter_restarts_from_zero(bad):
    config = {s.KEY_JOBS: bad}
    s.record_success(config, _FIRST)
    assert config[s.KEY_JOBS] == 1


def test_ensure_first_run_is_stable_and_repairs_a_future_date():
    config: dict = {}
    assert s.ensure_first_run(config, _FIRST) is True
    assert s.ensure_first_run(config, _FIRST + timedelta(days=30)) is False
    assert config[s.KEY_FIRST_RUN] == _FIRST.isoformat()
    config[s.KEY_FIRST_RUN] = (_FIRST + timedelta(days=99)).isoformat()
    assert s.ensure_first_run(config, _FIRST) is True
    assert config[s.KEY_FIRST_RUN] == _FIRST.isoformat()


# ----------------------------------------------------------------- config wiring

def test_every_key_is_a_default_and_local_only():
    for key in s.KEYS:
        assert key in cfg_mod.DEFAULT_CONFIG, key
        assert key in cfg_mod.LOCAL_ONLY_KEYS, key


def test_the_online_config_cannot_set_or_clear_them():
    online = {
        s.KEY_FIRST_RUN: "2000-01-01", s.KEY_JOBS: 99, s.KEY_SHOWN: 0,
        s.KEY_LAST_SHOWN: "2000-01-01", s.KEY_DONT_ASK: True,
    }
    # Nothing saved locally: the online values must not leak in over the defaults.
    merged = cfg_mod.merge_config_sources(dict(cfg_mod.DEFAULT_CONFIG), online, {})
    assert merged[s.KEY_JOBS] == 0
    assert merged[s.KEY_DONT_ASK] is False
    assert merged[s.KEY_FIRST_RUN] == ""
    # A saved local choice stays as the user made it.
    local = {s.KEY_JOBS: 3, s.KEY_DONT_ASK: True}
    merged = cfg_mod.merge_config_sources(
        dict(cfg_mod.DEFAULT_CONFIG), {s.KEY_JOBS: 0, s.KEY_DONT_ASK: False}, local,
    )
    assert merged[s.KEY_JOBS] == 3
    assert merged[s.KEY_DONT_ASK] is True


def test_the_link_is_the_repo_page_not_the_stargazers_list():
    assert s.REPO_URL == "https://github.com/Milomilo777/whisper-transcriber-suite"
    assert "stargazers" not in s.REPO_URL


def test_the_statistics_payload_has_no_star_field():
    from core import stats

    payload = stats.build_stats_payload(
        model="small", language="en", audio_duration=1.0,
        transcription_time=1.0, status="finished", word_count=1,
    )
    assert not [k for k in payload if k.startswith("star")]
