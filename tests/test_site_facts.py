"""site/facts.json and site/llms.txt: one source of truth, checked against the code.

The repo root no longer carries a second llms.txt; site/llms.txt is the only
one and tools/build_llms_full.py builds llms-full.txt from it. site/facts.json
is the machine-readable twin: formats and engines must match the code, the
version and date must match the llms.txt line the release workflow refreshes.
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

from core.backends.availability import ENGINE_CHOICES
from core.writers import supported_formats

ROOT = Path(__file__).resolve().parents[1]
FACTS = ROOT / "site" / "facts.json"
LLMS = ROOT / "site" / "llms.txt"
LLMS_FULL = ROOT / "site" / "llms-full.txt"

# Writer ids that are a layout of another format, not a format of their own.
NOT_A_FORMAT = {"smtv_docx"}
LOCAL_ENGINES = {"faster_whisper", "whisper_cpp", "nvidia_asr"}


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def facts() -> dict:
    return json.loads(FACTS.read_text(encoding="utf-8"))


def test_single_llms_txt():
    assert not (ROOT / "llms.txt").exists(), "llms.txt at the repo root is a second source of truth"
    assert LLMS.exists()


def test_output_formats_match_code(facts):
    assert sorted(facts["output_formats"]) == sorted(set(supported_formats()) - NOT_A_FORMAT)


def test_engines_match_code(facts):
    in_code = {value for _, value in ENGINE_CHOICES}
    listed = set(facts["engines"]["local"]) | set(facts["engines"]["cloud_opt_in"])
    assert listed == in_code
    assert set(facts["engines"]["local"]) == LOCAL_ENGINES


def test_license_matches_pyproject(facts):
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert f'license = {{ text = "{facts["license"]}" }}' in pyproject


def test_version_and_date_match_llms_txt(facts):
    text = LLMS.read_text(encoding="utf-8")
    m = re.search(r"Latest version (v[\d.]+), released (\d{4}-\d{2}-\d{2})", text)
    assert m, "site/llms.txt lost its 'Latest version ..., released ...' line"
    assert (facts["version"], facts["released"]) == m.groups()


def test_facts_links_are_https_and_listed_in_llms(facts):
    text = LLMS.read_text(encoding="utf-8")
    for key, url in facts["links"].items():
        assert url.startswith("https://"), key
    assert "https://whisper-transcriber-suite.pages.dev/facts.json" in text


def test_every_llms_link_to_a_repo_doc_resolves():
    text = LLMS.read_text(encoding="utf-8")
    prefix = "https://github.com/Milomilo777/whisper-transcriber-suite/blob/master/"
    paths = re.findall(r"\]\(" + re.escape(prefix) + r"([^)#]+)\)", text)
    assert len(paths) >= 12
    for rel in paths:
        assert (ROOT / rel).exists(), f"site/llms.txt links to a missing file: {rel}"


def test_llms_full_is_current():
    mod = _load("build_llms_full", "tools/build_llms_full.py")
    assert mod.build().replace("\r\n", "\n") == LLMS_FULL.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_render_facts_updates_only_version_and_date():
    usd = _load("update_site_data", "tools/update_site_data.py")
    data = {"version": "v2.0.0", "released": "2027-01-02", "downloads": 1, "files": {}}
    src = FACTS.read_text(encoding="utf-8")
    out = usd.render_facts(src, data)
    parsed = json.loads(out)
    assert (parsed["version"], parsed["released"]) == ("v2.0.0", "2027-01-02")
    expected = json.loads(src)
    expected.update(version="v2.0.0", released="2027-01-02")
    assert parsed == expected
    assert usd.render_facts(out, data) == out
