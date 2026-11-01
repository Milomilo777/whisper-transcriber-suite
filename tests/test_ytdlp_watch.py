"""Tests for tools/ytdlp_watch.py: classification of yt-dlp answers and the exit verdict (no network)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ytdlp_watch", ROOT / "tools" / "ytdlp_watch.py")
assert spec and spec.loader
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)


def fake_runner(table: dict[str, tuple[int, str, str]]):
    def run(cmd: list[str]) -> tuple[int, str, str]:
        if cmd[-1] == "--version":
            return 0, "2099.01.01\n", ""
        return table[cmd[-1]]
    return run


def test_classify_ok_needs_extractor_and_duration():
    assert watch.classify(0, "youtube|635|Title\n", "") == "ok"
    assert watch.classify(0, "youtube|NA|Title\n", "") == "fail"  # extractor ran but gave no media: not healthy
    assert watch.classify(0, "", "") == "fail"


def test_classify_blocked_is_not_a_verdict():
    err = "ERROR: [youtube] x: Sign in to confirm you're not a bot"
    assert watch.classify(1, "", err) == "blocked"
    assert watch.classify(1, "", "HTTP Error 429: Too Many Requests") == "blocked"
    assert watch.classify(1, "", "ERROR: Unsupported URL") == "fail"
    assert watch.classify(124, "", "timed out after 150 s") == "fail"


def test_verdict_rules():
    ok, blocked, fail = ({"status": s} for s in ("ok", "blocked", "fail"))
    assert watch.verdict([ok, ok]) == 0
    assert watch.verdict([ok, blocked]) == 0  # a blocked site alone only warns
    assert watch.verdict([ok, fail]) == 1
    assert watch.verdict([blocked, blocked]) == 1  # no usable answer at all
    assert watch.verdict([]) == 1


def _urls(tmp_path: Path, names: dict[str, str]) -> Path:
    p = tmp_path / "urls.json"
    p.write_text(json.dumps([{"name": n, "url": u} for n, u in names.items()]), encoding="utf-8")
    return p


def test_main_exit_codes_with_fake_yt_dlp(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    urls = _urls(tmp_path, {"A": "https://a.example/1", "B": "https://b.example/2"})
    good = {"https://a.example/1": (0, "a|10|t\n", ""), "https://b.example/2": (0, "b|20|t\n", "")}
    assert watch.main(["--urls", str(urls), "--yt-dlp", "yt-dlp"], runner=fake_runner(good)) == 0
    broken = dict(good, **{"https://b.example/2": (1, "", "ERROR: Unable to extract video data")})
    assert watch.main(["--urls", str(urls), "--yt-dlp", "yt-dlp"], runner=fake_runner(broken)) == 1
    out = capsys.readouterr().out
    assert "::error title=yt-dlp 2099.01.01 cannot read B" in out and "PROBLEM" in out


def test_main_writes_job_summary(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    urls = _urls(tmp_path, {"A": "https://a.example/1"})
    watch.main(["--urls", str(urls), "--yt-dlp", "yt-dlp"],
               runner=fake_runner({"https://a.example/1": (0, "a|10|t\n", "")}))
    text = summary.read_text(encoding="utf-8")
    assert "| A | OK |" in text and "2099.01.01" in text


def test_main_reports_a_yt_dlp_that_does_not_start(tmp_path):
    urls = _urls(tmp_path, {"A": "https://a.example/1"})
    assert watch.main(["--urls", str(urls), "--yt-dlp", "nope"], runner=lambda _cmd: (1, "", "boom")) == 1


def test_run_command_reports_a_missing_program_instead_of_raising():
    rc, out, err = watch.run_command(["definitely-not-a-real-program-xyz", "--version"])
    assert rc == 127 and out == "" and "cannot start" in err


def test_shipped_url_list_is_valid():
    entries = json.loads((ROOT / "tools" / "ytdlp_watch_urls.json").read_text(encoding="utf-8"))
    assert len(entries) >= 3
    assert all(e["url"].startswith("https://") and e["name"] for e in entries)
