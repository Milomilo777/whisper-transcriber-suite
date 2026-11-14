"""Error-rate reservations recover from backward wall-clock corrections."""
from core import stats

INSTALL = "00000000-0000-4000-8000-000000000001"


def row(number):
    return {"status": "error", "fingerprint": f"{number:012x}"}


def test_future_reservations_do_not_silence_corrected_clock(tmp_path):
    path = tmp_path / "rate.json"
    for i in range(5):
        assert stats.limit_error_row(row(i), INSTALL, path=path, now=2_000_000_000.0) is not None
    assert stats.limit_error_row(row(10), INSTALL, path=path, now=1_000_000_000.0) is not None
    assert stats.limit_error_row(row(10), INSTALL, path=path, now=1_000_000_010.0) is None


def test_out_of_order_clock_keeps_only_valid_past_reservations(tmp_path):
    path = tmp_path / "rate.json"
    assert stats.limit_error_row(row(1), INSTALL, path=path, now=100.0) is not None
    assert stats.limit_error_row(row(2), INSTALL, path=path, now=200.0) is not None
    assert stats.limit_error_row(row(3), INSTALL, path=path, now=150.0) is not None
    assert stats.limit_error_row(row(1), INSTALL, path=path, now=160.0) is None
    assert stats.limit_error_row(row(2), INSTALL, path=path, now=160.0) is not None


def test_valid_reservations_still_limit_five_per_hour(tmp_path):
    path = tmp_path / "rate.json"
    for i in range(5):
        assert stats.limit_error_row(row(i), INSTALL, path=path, now=1000.0 + i) is not None
    assert stats.limit_error_row(row(8), INSTALL, path=path, now=1010.0) is None
    assert stats.limit_error_row(row(1), INSTALL, path=path, now=1010.0) is None
    assert stats.limit_error_row(row(8), INSTALL, path=path, now=4605.0) is not None
