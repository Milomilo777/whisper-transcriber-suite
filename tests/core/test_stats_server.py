"""Static checks of the usage-stats server script (platform/stats-server/).

PHP is not part of the test toolchain, so these read the script as text and
pin its privacy contract: the client's network address is never read,
nothing is looked up over the network, the old IP columns get empty
strings, the country is validated, and every field the app sends is
accepted and length-capped.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from core import stats

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = REPO_ROOT / "platform" / "stats-server"
SCRIPT = SERVER_DIR / "transcription_stats.php"

NUMERIC_FIELDS = {
    "audio_duration", "transcription_time", "word_count", "cpu_count",
    "mem_total",
}


def _source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _code() -> str:
    """The script without comments, so prose cannot satisfy a check."""
    text = re.sub(r"/\*.*?\*/", "", _source(), flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", text)


def _payload_fields() -> set[str]:
    payload = stats.build_stats_payload(
        model="m", language="en", audio_duration=1.0,
        transcription_time=1.0, status="finished", word_count=1,
    )
    return set(payload) - {"form_submitted"}


def _text_limits() -> dict[str, int]:
    block = re.search(r"\$text_limits = array\((.*?)\);", _code(), re.S)
    assert block, "$text_limits block not found"
    return {k: int(v) for k, v in re.findall(r"'(\w+)'\s*=>\s*(\d+)", block.group(1))}


def test_script_moved_out_of_repo_root():
    assert SCRIPT.is_file()
    assert (SERVER_DIR / "README.md").is_file()
    assert not (REPO_ROOT / "stats" / "transcription_stats.php").exists()


@pytest.mark.parametrize("token", [
    "REMOTE_ADDR", "HTTP_X_FORWARDED_FOR", "HTTP_X_REAL_IP", "HTTP_CLIENT_IP",
    "HTTP_FORWARDED", "$_SERVER", "getenv", "getallheaders",
    "apache_request_headers",
])
def test_client_address_is_never_read(token):
    assert token not in _source()


@pytest.mark.parametrize("token", [
    "geoip", "file_get_contents", "fopen", "curl_", "fsockopen",
    "stream_socket_client", "stream_context_create", "SoapClient",
    "http://", "https://",
])
def test_no_outbound_request(token):
    assert token.lower() not in _source().lower()


@pytest.mark.parametrize("column", ["client_ip", "ip_location_json", "platform_node"])
def test_old_ip_columns_kept_but_written_empty(column):
    code = _code()
    assert re.search(rf"\b{column} TEXT\b", code), "column must stay in the schema"
    binds = re.findall(rf"bindValue\(':{column}',\s*([^)]*)\)", code)
    assert binds == ["''"]


def test_no_destructive_sql():
    assert not re.search(r"\b(DROP|DELETE|UPDATE|VACUUM)\b", _code())


def test_country_must_be_two_upper_case_letters():
    code = _code()
    # D: `$` must not also match before a trailing newline ("DE\n").
    assert "preg_match('/^[A-Z]{2}$/D', $_POST[$name])" in code
    assert "$country_code = post_country('country');" in code
    assert "bindValue(':country_code', $country_code)" in code


def test_every_payload_field_is_read():
    code = _code()
    missing = [f for f in sorted(_payload_fields()) if f"'{f}'" not in code]
    assert missing == []


def test_computer_name_is_not_read():
    assert "post_text('platform_node'" not in _code()
    assert "platform_node" not in _payload_fields()


def test_every_text_field_is_length_capped():
    code = _code()
    limits = _text_limits()
    text_fields = _payload_fields() - NUMERIC_FIELDS - {"country"}
    assert sorted(text_fields - set(limits)) == []
    assert all(0 < n <= 1024 for n in limits.values())
    # Each text field is bound through the capped post_text loop.
    loop = re.search(r"foreach \(array\((.*?)\) as \$field\)", code, re.S)
    assert loop, "post_text loop not found"
    assert "post_text($field, $text_limits[$field])" in code
    looped = set(re.findall(r"'(\w+)'", loop.group(1)))
    assert sorted(text_fields - looped) == []


def test_file_name_is_never_read_and_new_rows_store_null():
    # Older app versions still post file_name; the script must ignore it.
    code = _code()
    assert re.search(r"\bfile_name TEXT\b", code), "column must stay for old rows"
    assert "'file_name'" not in code, "file_name must not be read or capped"
    assert "post_file_basename" not in code
    binds = re.findall(r"bindValue\(':file_name',\s*([^)]*)\)", code)
    assert binds == ["null, PDO::PARAM_NULL"]
    assert "file_name" not in _text_limits()
    assert "file_name" not in _payload_fields()


def test_numeric_fields_are_clamped():
    code = _code()
    for field in sorted(NUMERIC_FIELDS):
        assert re.search(rf"post_(number|int)\('{field}',", code), field
