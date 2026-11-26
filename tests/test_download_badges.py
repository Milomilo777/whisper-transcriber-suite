from __future__ import annotations

import io
import json
from urllib.error import HTTPError
import xml.etree.ElementTree as ET

import pytest

from tools import download_badges as badges


REPO = "example/project"
API = f"https://api.github.com/repos/{REPO}/releases"
SVG = "{http://www.w3.org/2000/svg}"


def release(tag, *counts, draft=False):
    return {"tag_name": tag, "draft": draft,
            "assets": [{"download_count": count} for count in counts]}


def fake_api(monkeypatch, *pages):
    calls = []

    def open_page(request, *, timeout):
        calls.append(request)
        page, link = pages[len(calls) - 1]
        if isinstance(page, Exception):
            raise page
        response = io.BytesIO(json.dumps(page).encode())
        response.headers = {"Link": link}
        return response

    monkeypatch.setattr(badges, "urlopen", open_page)
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    return calls


@pytest.mark.parametrize(("count", "expected"), [
    (0, "0"), (999, "999"), (1000, "1k"), (1050, "1.1k"),
    (4199, "4.2k"), (9950, "10k"), (17000, "17k"),
    (999500, "1M"), (1200000, "1.2M"), (17000000, "17M"),
    (1234000000, "1.2B"),
])
def test_format_count(count, expected):
    assert badges.format_count(count) == expected


def test_pagination_draft_and_svg_files(monkeypatch, tmp_path):
    # GitHub can use the numeric repository URL in a Link response.
    next_url = "https://api.github.com/repositories/123/releases?per_page=100&page=2"
    calls = fake_api(monkeypatch,
                     ([release("v2.0.0", 4000, 200)], f'<{next_url}>; rel="next", <{next_url}>; rel="last"'),
                     ([release("v1.0.0", 800), release("v3.0.0", 700, draft=True)], ""))
    assert badges.main([REPO, str(tmp_path)]) == 0
    assert [req.full_url for req in calls] == [f"{API}?per_page=100", next_url]
    assert all(req.get_header("Authorization") == "Bearer test-token" for req in calls)
    expected = {"total.svg": ("downloads", "5k", "207a80"),
                "total-all-versions.svg": ("all versions", "5k", "207a80")}
    for tag, count in [("v1.0.0", "800"), ("v2.0.0", "4.2k"), ("v3.0.0", "0")]:
        expected[f"{tag}.svg"] = (tag, count, "207a80")
        expected[f"{tag}-grey.svg"] = (tag, count, "8a8a8a")
        expected[f"{tag}-this-version.svg"] = ("this version", count, "207a80")
    assert {path.name for path in tmp_path.iterdir()} == expected.keys()
    for name, (label, value, color) in expected.items():
        svg = ET.parse(tmp_path / name).getroot()
        assert svg.tag == f"{SVG}svg"
        assert svg.attrib["aria-label"] == f"{label}: {value}"
        assert svg.findtext(f"{SVG}title") == f"{label}: {value}"
        assert {node.attrib.get("fill") for node in svg.iter()} >= {"#555", f"#{color}"}


def test_widths_grow_and_svg_escapes_label():
    small = ET.fromstring(badges.render_badge("i", "1", "207a80"))
    wide = ET.fromstring(badges.render_badge("W", "1", "207a80"))
    long = ET.fromstring(badges.render_badge('wide <&" tag', "123", "207a80"))
    assert int(small.attrib["width"]) < int(wide.attrib["width"]) < int(long.attrib["width"])
    assert long.findtext(f"{SVG}title") == 'wide <&" tag: 123'


def test_deterministic_bytes_and_preserves_old_files(monkeypatch, tmp_path):
    older = tmp_path / "v0.0.1.svg"
    older.write_bytes(b"existing")
    first, second = release("v2.0.0", 42), release("v1.0.0", 7)
    fake_api(monkeypatch, ([first, second], ""))
    assert badges.main([REPO, str(tmp_path)]) == 0
    snapshot = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.iterdir()}
    fake_api(monkeypatch, ([second, first], ""))
    assert badges.main([REPO, str(tmp_path)]) == 0
    assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.iterdir()} == snapshot
    assert older.read_bytes() == b"existing"


@pytest.mark.parametrize("page", [[], {"message": "error"}, [release("v2.0.0", -1)],
                                 [release("../escape", 1)], [release("total", 1)],
                                 [release("v2.0.0", 1), release("v2.0.0-grey", 2)]])
def test_invalid_or_empty_api_leaves_output_untouched(monkeypatch, tmp_path, page):
    fake_api(monkeypatch, (page, ""))
    old = tmp_path / "total.svg"
    old.write_bytes(b"old badge")
    assert badges.main([REPO, str(tmp_path)]) == 1
    assert list(tmp_path.iterdir()) == [old]
    assert old.read_bytes() == b"old badge"


def test_second_page_failure_leaves_output_untouched(monkeypatch, tmp_path):
    next_url = f"{API}?per_page=100&page=2"
    fake_api(monkeypatch, ([release("v2.0.0", 42)], f'<{next_url}>; rel="next"'),
             (HTTPError(next_url, 503, "unavailable", {}, None), ""))
    output = tmp_path / "missing"
    assert badges.main([REPO, str(output)]) == 1
    assert not output.exists()


def test_rejects_offsite_pagination_before_sending_token(monkeypatch, tmp_path):
    calls = fake_api(monkeypatch, ([release("v2.0.0", 42)],
                                  '<https://example.net/releases?page=2>; rel="next"'))
    assert badges.main([REPO, str(tmp_path)]) == 1
    assert len(calls) == 1
    assert not list(tmp_path.iterdir())


def test_published_release_takes_priority_over_draft_with_same_tag(monkeypatch):
    fake_api(monkeypatch, ([release("v2.0.0", 8), release("v2.0.0", draft=True),
                           release("", draft=True), release("v3.0.0", draft=True)], ""))
    assert badges.release_counts(REPO, "token") == {"v2.0.0": 8, "v3.0.0": 0}
