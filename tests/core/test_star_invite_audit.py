from __future__ import annotations


from core import star_invite as s

def test_parse_date_coverage():
    assert s._parse_date(123) is None
    assert s._parse_date("2024-02-30") is None  # invalid day

def test_count_coverage():
    assert s._count({}, "nonexistent") == 0
    assert s._count({"val": "not an int"}, "val") == 0
    assert s._count({"val": True}, "val") == 0
    assert s._count({"val": -5}, "val") == 0

def test_should_invite_coverage():
    import datetime
    today = datetime.date(2026, 10, 1)
    # A date that is future but unreadable -> just now -> False
    config = {
        s.KEY_FIRST_RUN: "2026-09-01",
        s.KEY_JOBS: 10,
        s.KEY_SHOWN: 1,
        s.KEY_DONT_ASK: False,
        s.KEY_LAST_SHOWN: "2026-12-01"  # future
    }
    assert s.should_invite(config, today, job_running=False, offline=False) is False
