"""tools/update_site_data.py: marker filling must hit the right attributes."""
import importlib.util
import os

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "update_site_data.py")
_spec = importlib.util.spec_from_file_location("update_site_data", _PATH)
assert _spec is not None and _spec.loader is not None
usd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(usd)

DATA = {
    "version": "v2.0.0",
    "released": "2027-01-02",
    "downloads": 1234,
    "files": {"installer": {"url": "https://example.test/setup.exe", "mb": 240}},
}


def test_href_replaces_link_not_marker():
    html = '<a class="btn" data-auto-href="installer" href="https://old">Get</a>'
    out = usd.render_page(html, DATA)
    assert 'data-auto-href="installer"' in out
    assert 'href="https://example.test/setup.exe"' in out
    assert "https://old" not in out


def test_text_markers_and_json_ld():
    html = (
        '<span data-auto="version">v1.0.0</span> <strong data-auto="downloads">5</strong>'
        '<p class="dl-size" data-auto="size-installer">~1&nbsp;MB</p>'
        '"softwareVersion": "1.0.0", "dateModified": "2026-01-01", "userInteractionCount": 5'
    )
    out = usd.render_page(html, DATA)
    assert '<span data-auto="version">v2.0.0</span>' in out
    assert '<strong data-auto="downloads">1,200+</strong>' in out
    assert "~240&nbsp;MB" in out
    assert '"softwareVersion": "2.0.0"' in out
    assert '"dateModified": "2027-01-02"' in out
    assert '"userInteractionCount": 1234' in out


def test_render_is_idempotent():
    html = '<a data-auto-href="installer" href="x">a</a><span data-auto="version">v1</span>'
    once = usd.render_page(html, DATA)
    assert usd.render_page(once, DATA) == once


def test_downloads_label_never_overstates():
    assert usd.downloads_label(42) == "42"
    assert usd.downloads_label(912) == "900+"
    assert usd.downloads_label(1299) == "1,200+"


def test_llms_lines():
    text = "- [Latest release](u): v1.9.3 — free Windows installer\n- Latest version v1.9.3, released 2026-09-26; x"
    out = usd.render_llms(text, DATA)
    assert "v2.0.0 — free Windows installer" in out
    assert "Latest version v2.0.0, released 2027-01-02" in out


def test_mac_oneliner_tracks_version_and_is_escaped():
    html = '<code id="mac-cmd" data-auto="mac-oneliner">old</code>'
    out = usd.render_page(html, DATA)
    assert "releases/download/v2.0.0/WhisperTranscriberSuite-v2.0.0-macOS-$A.dmg" in out
    assert "&amp;&amp; hdiutil attach" in out
    assert " && " not in out


def test_checksum_marker_filled_from_digest():
    data = dict(DATA, files={"installer": {"url": "u", "mb": 1, "sha256": "ab" * 32}})
    out = usd.render_page('<code data-auto="sha-installer">—</code>', data)
    assert out == '<code data-auto="sha-installer">' + "ab" * 32 + "</code>"
