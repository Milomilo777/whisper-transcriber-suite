import hashlib
import json

"""Error-rate reservations recover from backward wall-clock corrections."""
from core import stats

INSTALL = "00000000-0000-4000-8000-000000000001"


def row(number):
    return {"status": "error", "fingerprint": f"{number:012x}"}


def test_future_reservations_expire_within_one_corrected_hour(tmp_path):
    path = tmp_path / "rate.json"
    for i in range(5):
        assert stats.limit_error_row(row(i), INSTALL, path=path, now=2_000_000_000.0) is not None
    assert stats.limit_error_row(row(10), INSTALL, path=path, now=1_000_000_000.0) is None
    assert stats.limit_error_row(row(10), INSTALL, path=path, now=1_000_000_010.0) is None
    assert stats.limit_error_row(row(10), INSTALL, path=path, now=1_000_003_599.0) is None
    assert stats.limit_error_row(row(10), INSTALL, path=path, now=1_000_003_600.0) is not None


def test_out_of_order_clock_preserves_recent_reservations(tmp_path):
    path = tmp_path / "rate.json"
    assert stats.limit_error_row(row(1), INSTALL, path=path, now=100.0) is not None
    assert stats.limit_error_row(row(2), INSTALL, path=path, now=200.0) is not None
    assert stats.limit_error_row(row(3), INSTALL, path=path, now=150.0) is not None
    assert stats.limit_error_row(row(1), INSTALL, path=path, now=160.0) is None
    assert stats.limit_error_row(row(2), INSTALL, path=path, now=160.0) is None


def test_valid_reservations_still_limit_five_per_hour(tmp_path):
    path = tmp_path / "rate.json"
    for i in range(5):
        assert stats.limit_error_row(row(i), INSTALL, path=path, now=1000.0 + i) is not None
    assert stats.limit_error_row(row(8), INSTALL, path=path, now=1010.0) is None
    assert stats.limit_error_row(row(1), INSTALL, path=path, now=1010.0) is None
    assert stats.limit_error_row(row(8), INSTALL, path=path, now=4605.0) is not None


def test_small_backward_step_preserves_quota_and_fingerprints(tmp_path):
    path = tmp_path / 'rate.json'
    for i in range(5):
        assert stats.limit_error_row(row(i), INSTALL, path=path, now=1000.0+i) is not None
    assert stats.limit_error_row(row(10), INSTALL, path=path, now=990.0) is None
    assert stats.limit_error_row(row(0), INSTALL, path=path, now=990.0) is None
    assert stats.limit_error_row(row(10), INSTALL, path=path, now=4589.0) is None
    assert stats.limit_error_row(row(10), INSTALL, path=path, now=4590.0) is not None


def test_same_clock_tick_preserves_limit_and_duplicate_filter(tmp_path):
    path = tmp_path / 'rate.json'
    for i in range(5):
        assert stats.limit_error_row(row(i), INSTALL, path=path, now=1000.0) is not None
    assert stats.limit_error_row(row(10), INSTALL, path=path, now=1000.0) is None
    assert stats.limit_error_row(row(0), INSTALL, path=path, now=1000.0) is None


def test_unrepresentable_timestamp_does_not_silence_all_errors(tmp_path):
    path = tmp_path / 'rate.json'
    install = hashlib.sha256(INSTALL.encode('ascii')).hexdigest()[:12]
    path.write_text(json.dumps({'install': install, 'sent': [{'t': 10**400, 'fp': row(0)['fingerprint']}], 'pending': {}}))
    assert stats.limit_error_row(row(1), INSTALL, path=path, now=1000.0) is not None
    saved = json.loads(path.read_text())
    assert len(saved['sent']) == 1
    assert saved['sent'][0]['fp'] == row(1)['fingerprint']


def test_backward_step_keeps_duplicate_repeat_bucket_until_expiry(tmp_path):
    path = tmp_path / 'rate.json'
    assert stats.limit_error_row(row(1), INSTALL, path=path, now=200.0) is not None
    assert stats.limit_error_row(row(1), INSTALL, path=path, now=150.0) is None
    assert stats.limit_error_row(row(1), INSTALL, path=path, now=3750.0)['repeat_bucket'] == '1-2'
