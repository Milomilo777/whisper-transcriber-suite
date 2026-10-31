"""Online-config trust boundaries and cache revocation, without a GUI."""
from __future__ import annotations

import io
import json
import logging
import time
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import config as cfg


URL = "https://example.invalid/app.json"
SAFE_STATS = "https://stats.whisper-transcriber-suite.com/v1/runs"
CACHE_TIME_KEY = "_wts_saved_at"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("unexpected network request")

    monkeypatch.setattr(cfg, "urlopen_https_only", refuse)
    cfg._ONLINE_MEMO.clear()
    cfg._ONLINE_REVOKED_CACHES.clear()
    cfg._forget_last_good()
    yield
    cfg._ONLINE_MEMO.clear()
    cfg._ONLINE_REVOKED_CACHES.clear()
    cfg._forget_last_good()


def use_local_file(monkeypatch, tmp_path, data):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(cfg, "config_path", lambda: str(path))
    monkeypatch.setattr(cfg, "user_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(cfg, "migrate_config_location", lambda: None)
    return path


def http_error(code):
    return urllib.error.HTTPError(URL, code, "error", {}, None)


def test_default_config_url_is_owned_and_never_saved(monkeypatch, tmp_path):
    assert cfg.DEFAULT_CONFIG["config_url"] == (
        "https://whisper-transcriber-suite.com/app_config.json"
    )
    path = use_local_file(monkeypatch, tmp_path, {})
    cfg.save_config(cfg.load_config(fetch_online=False))
    assert "config_url" not in json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("url", ["", "https://example.invalid/custom.json"])
def test_local_config_url_is_preserved_and_blank_opts_out(monkeypatch, tmp_path, url):
    path = use_local_file(monkeypatch, tmp_path, {"config_url": url})
    calls = []
    monkeypatch.setattr(cfg, "fetch_online_config", lambda address: calls.append(address) or {})
    config = cfg.load_config()
    cfg.save_config(config)
    assert json.loads(path.read_text(encoding="utf-8"))["config_url"] == url
    assert calls == ([url] if url else [])


@pytest.mark.parametrize("value", [
    "https://whisper-transcriber-suite.com/collect",
    SAFE_STATS,
    "https://A.B.whisper-transcriber-suite.com:443/path?x=1",
])
def test_online_stats_accepts_only_the_project_https_hosts(value):
    merged = cfg.merge_config_sources(cfg.DEFAULT_CONFIG, {"stats_url": value}, None)
    assert merged["stats_url"] == value


@pytest.mark.parametrize("value", [
    "http://whisper-transcriber-suite.com/x", "https://evil.example/x",
    "https://notwhisper-transcriber-suite.com/x",
    "https://whisper-transcriber-suite.com.evil.example/x",
    "https://user:pass@whisper-transcriber-suite.com/x",
    "https://@whisper-transcriber-suite.com/x",
    "https://whisper-transcriber-suite.com:444/x",
    "https://whisper-transcriber-suite.com:/x",
    "https://whisper-transcriber-suite.com:bad/x",
    "https://foo..whisper-transcriber-suite.com/x",
    "https://whisper-transcriber-suite.com\n.evil.example/x",
    " https://whisper-transcriber-suite.com/x", "", None, 12,
])
def test_online_stats_rejection_falls_back_once_and_logs_no_url(value, caplog):
    with caplog.at_level(logging.DEBUG, logger="core.config"):
        merged = cfg.merge_config_sources(cfg.DEFAULT_CONFIG, {"stats_url": value}, None)
    assert merged["stats_url"] == cfg.DEFAULT_CONFIG["stats_url"]
    messages = [record.getMessage() for record in caplog.records
                if record.levelno == logging.DEBUG]
    assert len(messages) == 1
    assert "stats_url" in messages[0]
    assert "pass" not in messages[0]


@pytest.mark.parametrize("local_url", ["", "http://localhost:9999/collect", "https://other.example/x"])
def test_local_stats_url_is_not_restricted(local_url):
    result = cfg.merge_config_sources(cfg.DEFAULT_CONFIG, {"stats_url": SAFE_STATS},
                                      {"stats_url": local_url})
    assert result["stats_url"] == local_url


def test_410_removes_cache_and_is_remembered(monkeypatch, tmp_path):
    cache = tmp_path / "online.json"
    cache.write_text(json.dumps({"stats_url": SAFE_STATS, "latest_version": "1.2.3"}), encoding="utf-8")
    calls = []

    def gone(*args, **kwargs):
        calls.append(1)
        raise http_error(410)

    monkeypatch.setattr(cfg, "urlopen_https_only", gone)
    assert cfg.fetch_online_config(URL, cache_path=cache) == {}
    assert not cache.exists()
    assert cfg.fetch_online_config(URL, cache_path=cache) == {}
    assert len(calls) == 1


def test_410_does_not_reuse_cache_when_deletion_fails(monkeypatch, tmp_path):
    cache = tmp_path / "online.json"
    cache.write_text(json.dumps({"stats_url": SAFE_STATS}), encoding="utf-8")
    unlink = Path.unlink

    def fail_cache(self, *args, **kwargs):
        if self == cache:
            raise PermissionError("locked")
        return unlink(self, *args, **kwargs)

    def gone(*args, **kwargs):
        raise http_error(410)

    monkeypatch.setattr(Path, "unlink", fail_cache)
    monkeypatch.setattr(cfg, "urlopen_https_only", gone)
    assert cfg.fetch_online_config(URL, cache_path=cache) == {}
    assert cache.exists()
    assert cfg.fetch_online_config(URL, cache_path=cache) == {}
    assert cfg.fetch_online_config("", cache_path=cache) == {}


def test_410_still_deletes_cache_if_tombstone_cannot_be_written(monkeypatch, tmp_path):
    cache = tmp_path / "online.json"
    cache.write_text(json.dumps({"stats_url": SAFE_STATS}), encoding="utf-8")
    write = cfg._write_text_atomic

    def fail_tombstone(path, text):
        if path == cfg._online_revoked_marker(cache):
            raise PermissionError("cannot write tombstone")
        write(path, text)

    def gone(*args, **kwargs):
        raise http_error(410)

    monkeypatch.setattr(cfg, "_write_text_atomic", fail_tombstone)
    monkeypatch.setattr(cfg, "urlopen_https_only", gone)
    assert cfg.fetch_online_config(URL, cache_path=cache) == {}
    assert not cache.exists()


def test_410_stays_revoked_in_process_when_deletion_and_tombstone_fail(monkeypatch, tmp_path):
    cache = tmp_path / "online.json"
    cache.write_text(json.dumps({"stats_url": SAFE_STATS}), encoding="utf-8")
    write = cfg._write_text_atomic
    unlink = Path.unlink

    def fail_tombstone(path, text):
        if path == cfg._online_revoked_marker(cache):
            raise PermissionError("cannot write tombstone")
        write(path, text)

    def fail_cache(self, *args, **kwargs):
        if self == cache:
            raise PermissionError("cannot delete cache")
        return unlink(self, *args, **kwargs)

    def gone(*args, **kwargs):
        raise http_error(410)

    monkeypatch.setattr(cfg, "_write_text_atomic", fail_tombstone)
    monkeypatch.setattr(Path, "unlink", fail_cache)
    monkeypatch.setattr(cfg, "urlopen_https_only", gone)
    assert cfg.fetch_online_config(URL, cache_path=cache) == {}
    assert cfg.fetch_online_config(URL, cache_path=cache) == {}
    assert cfg.fetch_online_config("", cache_path=cache) == {}


@pytest.mark.parametrize("failure", [404, 500, "network", "json"])
def test_failures_keep_a_fresh_last_good_cache(monkeypatch, tmp_path, failure):
    cache = tmp_path / "online.json"
    cached = {"stats_url": SAFE_STATS, "latest_version": "1.2.3"}
    cache.write_text(json.dumps({**cached, CACHE_TIME_KEY: time.time()}), encoding="utf-8")

    def fail(*args, **kwargs):
        if failure == "json":
            return io.BytesIO(b"not json")
        if failure == "network":
            raise urllib.error.URLError("offline")
        raise http_error(failure)

    monkeypatch.setattr(cfg, "urlopen_https_only", fail)
    assert cfg.fetch_online_config(URL, cache_path=cache) == cached


def test_success_writes_cache_timestamp_and_empty_object_revokes(monkeypatch, tmp_path):
    cache = tmp_path / "online.json"
    cache.write_text(json.dumps({"stats_url": SAFE_STATS}), encoding="utf-8")
    monkeypatch.setattr(cfg, "urlopen_https_only", lambda *a, **kw: io.BytesIO(b"{}"))
    before = time.time()
    assert cfg.fetch_online_config(URL, cache_path=cache) == {}
    stored = json.loads(cache.read_text(encoding="utf-8"))
    assert before <= stored.pop(CACHE_TIME_KEY) <= time.time()
    assert stored == {}
    assert cfg.fetch_online_config("", cache_path=cache) == {}


@pytest.mark.parametrize("age,expect_stats", [(0, True), (29 * 86400, True), (31 * 86400, False)])
def test_only_stats_expire_from_a_timestamped_cache(tmp_path, age, expect_stats):
    cache = tmp_path / "online.json"
    cache.write_text(json.dumps({"stats_url": SAFE_STATS, "latest_version": "1.2.3",
                                 "model_catalog": {"x": {"name": "x"}},
                                 CACHE_TIME_KEY: time.time() - age}), encoding="utf-8")
    result = cfg.fetch_online_config("", cache_path=cache)
    assert ("stats_url" in result) is expect_stats
    assert result["latest_version"] == "1.2.3"
    assert result["model_catalog"] == {"x": {"name": "x"}}
    assert CACHE_TIME_KEY not in result


def test_untimed_cache_supplies_no_stats_until_successful_rewrite(monkeypatch, tmp_path):
    cache = tmp_path / "online.json"
    cache.write_text(json.dumps({"stats_url": SAFE_STATS}), encoding="utf-8")
    assert "stats_url" not in cfg.fetch_online_config("", cache_path=cache)
    monkeypatch.setattr(cfg, "urlopen_https_only",
                        lambda *a, **kw: io.BytesIO(json.dumps({"stats_url": SAFE_STATS}).encode()))
    assert cfg.fetch_online_config(URL, cache_path=cache)["stats_url"] == SAFE_STATS
    assert CACHE_TIME_KEY in json.loads(cache.read_text(encoding="utf-8"))


def test_memoized_cached_stats_expire_during_a_long_running_process(monkeypatch, tmp_path):
    use_local_file(monkeypatch, tmp_path, {})
    cache = cfg.online_cache_path()
    cache.parent.mkdir(parents=True)
    now = time.time()
    cached_url = "https://cached.whisper-transcriber-suite.com/stats"
    cache.write_text(json.dumps({"stats_url": cached_url,
                                 CACHE_TIME_KEY: now - 29 * 86400}), encoding="utf-8")
    monkeypatch.setattr(cfg.time, "time", lambda: now)
    monkeypatch.setattr(cfg, "urlopen_https_only", lambda *a, **kw: (_ for _ in ()).throw(
        urllib.error.URLError("offline")))
    assert cfg.load_config()["stats_url"] == cached_url
    monkeypatch.setattr(cfg.time, "time", lambda: now + 2 * 86400)
    assert cfg.load_config()["stats_url"] == cfg.DEFAULT_CONFIG["stats_url"]


def test_stats_post_rechecks_cache_age_without_config_reload(monkeypatch, tmp_path):
    from core import stats

    use_local_file(monkeypatch, tmp_path, {})
    cache = cfg.online_cache_path()
    cache.parent.mkdir(parents=True)
    now = time.time()
    cached_url = "https://cached.whisper-transcriber-suite.com/stats"
    cache.write_text(json.dumps({"stats_url": cached_url,
                                 CACHE_TIME_KEY: now - 29 * 86400}), encoding="utf-8")
    monkeypatch.setattr(cfg.time, "time", lambda: now)
    monkeypatch.setattr(cfg, "urlopen_https_only", lambda *a, **kw: (_ for _ in ()).throw(
        urllib.error.URLError("offline")))
    config = cfg.load_config()
    assert config["stats_url"] == cached_url
    sent = []

    class ImmediateThread:
        def __init__(self, *, target, args, **kwargs):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(stats, "threading", SimpleNamespace(Thread=ImmediateThread))
    monkeypatch.setattr(stats, "_post", lambda url, *args: sent.append(url))
    monkeypatch.setattr(cfg.time, "time", lambda: now + 2 * 86400)
    assert stats.post_stats_async(config, {"status": "finished"})
    assert sent == [cfg.DEFAULT_CONFIG["stats_url"]]
    config["stats_url"] = "http://localhost:9999/stats"
    assert stats.post_stats_async(config.copy(), {"status": "finished"})
    assert sent[-1] == "http://localhost:9999/stats"


@pytest.mark.parametrize("timestamp", [None, "yesterday", -1, True, 10**20])
def test_invalid_cache_timestamp_does_not_keep_stats_forever(tmp_path, timestamp):
    cache = tmp_path / "online.json"
    cache.write_text(json.dumps({"stats_url": SAFE_STATS, "latest_version": "1.2.3",
                                 CACHE_TIME_KEY: timestamp}), encoding="utf-8")
    assert cfg.fetch_online_config("", cache_path=cache) == {"latest_version": "1.2.3"}


@pytest.mark.parametrize("version", ["1.2.3", "999.000.1", "0.0.0"])
def test_online_latest_version_accepts_plain_numeric_versions(version):
    assert cfg.merge_config_sources({"latest_version": "default"},
                                    {"latest_version": version}, None)["latest_version"] == version


@pytest.mark.parametrize("version", ["1.2", "v1.2.3", "1.2.3-rc1", "1.2.3\n",
                                     "1000.2.3", "1.2.3.4", "\u0661.\u0662.\u0663", "", None, 123])
def test_online_latest_version_rejects_other_values_and_local_is_free(version):
    assert cfg.merge_config_sources({"latest_version": "default"},
                                    {"latest_version": version}, None)["latest_version"] == "default"
    assert cfg.merge_config_sources({"latest_version": "default"},
                                    {"latest_version": version},
                                    {"latest_version": "custom"})["latest_version"] == "custom"


@pytest.mark.parametrize("repo", ["https://evil.example/model", "//evil.example/model",
                                   "org/repo/extra", "../repo", "org/repo?endpoint=evil",
                                   "org\\repo", "user@evil.example", 123])
def test_online_catalog_rejects_non_repository_download_references(repo):
    online = {"model_catalog": {"bad": {"name": "bad", "hf_repo": repo}}}
    assert "bad" not in cfg.merge_config_sources({"model_catalog": {}}, online, None)["model_catalog"]


def test_online_catalog_keeps_normal_repos_and_local_catalog_is_free():
    online = {"model_catalog": {"good": {"name": "model", "hf_repo": "Systran/model-v1.2"}}}
    local = {"model_catalog": {"local": {"name": "local", "hf_repo": "http://custom"}}}
    result = cfg.merge_config_sources({"model_catalog": {}}, online, local)["model_catalog"]
    assert result == {**online["model_catalog"], **local["model_catalog"]}


@pytest.mark.parametrize("local,online,source,host", [
    ({}, {}, "default", "stats.whisper-transcriber-suite.com"),
    ({}, {"stats_url": "https://sub.whisper-transcriber-suite.com/x"}, "online", "sub.whisper-transcriber-suite.com"),
    ({}, {"stats_url": "http://evil.example"}, "default", "stats.whisper-transcriber-suite.com"),
    ({"stats_url": "http://user:secret@localhost:8123/path?token=secret"}, {}, "local", "localhost"),
    ({"stats_url": ""}, {}, "local", "<none>"),
    ({"stats_url": None}, {}, "default", "stats.whisper-transcriber-suite.com"),
])
def test_startup_stats_diagnostic_reports_effective_source_and_host(
    monkeypatch, tmp_path, caplog, local, online, source, host
):
    use_local_file(monkeypatch, tmp_path, local)
    monkeypatch.setattr(cfg, "fetch_online_config", lambda *args, **kwargs: online)
    config = cfg.load_config()
    with caplog.at_level(logging.INFO, logger="core.config"):
        cfg.log_effective_stats_url(config)
    # Other INFO lines (e.g. the model path) depend on the machine: count only this diagnostic.
    messages = [r.getMessage() for r in caplog.records
                if r.levelno == logging.INFO and r.getMessage().startswith("Effective stats_url")]
    assert len(messages) == 1
    assert f"source={source}" in messages[0]
    assert f"host={host}" in messages[0]
    assert "secret" not in messages[0]


@pytest.mark.parametrize("repo", ["SYSTRAN/faster-whisper-new", "systran/faster-whisper-new",
                                  "kblab/kb-whisper-small", "Ivrit-AI/whisper-large-v3-ct2"])
def test_online_catalog_accepts_built_in_owners_in_any_case(repo):
    online = {"model_catalog": {"new": {"name": "new", "hf_repo": repo}}}
    result = cfg.merge_config_sources({"model_catalog": {}}, online, None)["model_catalog"]
    assert result == {"new": {"name": "new", "hf_repo": repo}}


@pytest.mark.parametrize("entry", [
    {"name": "x", "hf_repo": "unknown-owner/faster-whisper-x"},
    {"name": "x", "hf_repo": ""},
    {"name": "x"},
    {"name": "x", "hf_repo": None},
    {"name": "x", "hf_repo": "faster-whisper-x"},
    {"name": "x", "hf_repo": "/faster-whisper-x"},
    {"name": "x", "hf_repo": "Systran/faster..whisper"},
    {"name": "x", "hf_repo": "Systran/model.."},
    {"name": "x", "hf_repo": "Systran../model"},
])
def test_online_catalog_drops_untrusted_empty_and_ownerless_repos(entry):
    good = {"name": "g", "hf_repo": "Systran/faster-whisper-g"}
    online = {"model_catalog": {"bad": entry, "good": good}}
    result = cfg.merge_config_sources({"model_catalog": {}}, online, None)["model_catalog"]
    assert result == {"good": good}


def test_local_catalog_entry_with_an_unknown_owner_still_works(monkeypatch, tmp_path):
    entry = {"label": "Mine", "name": "faster-whisper-mine", "hf_repo": "someone-else/whisper-mine"}
    online = {"model_catalog": {"mine": {"name": "online", "hf_repo": "someone-else/online"}}}
    merged = cfg.merge_config_sources({"model_catalog": {}}, online, {"model_catalog": {"mine": entry}})
    assert merged["model_catalog"] == {"mine": entry}
    use_local_file(monkeypatch, tmp_path, {"model_catalog": {"mine": entry}})
    assert cfg.load_config(fetch_online=False)["model_catalog"]["mine"] == entry


def test_every_built_in_repo_owner_is_trusted():
    from core.model_manager import MODEL_REGISTRY

    repos = [entry["hf_repo"] for entry in MODEL_REGISTRY.values()]
    repos += [cfg.DEFAULT_CONFIG["model"]["hf_repo"], cfg.FRESH_INSTALL_MODEL["hf_repo"]]
    for repo in repos:
        assert repo.split("/")[0].lower() in cfg.ONLINE_MODEL_OWNERS, repo
    # The built-in catalog published as an online one passes the filter whole.
    online = {"model_catalog": {slug: dict(entry) for slug, entry in MODEL_REGISTRY.items()}}
    result = cfg.merge_config_sources({"model_catalog": {}}, online, None)["model_catalog"]
    assert result.keys() == MODEL_REGISTRY.keys()


def test_untimed_cache_keeps_other_keys(tmp_path):
    cache = tmp_path / "online.json"
    cached = {"latest_version": "1.2.3",
              "model_catalog": {"x": {"name": "x", "hf_repo": "Systran/x"}}}
    cache.write_text(json.dumps({**cached, "stats_url": SAFE_STATS}), encoding="utf-8")
    assert cfg.fetch_online_config("", cache_path=cache) == cached


def test_memoized_copy_without_timestamp_supplies_no_stats_url(monkeypatch, tmp_path):
    cached_url = "https://cached.whisper-transcriber-suite.com/stats"
    untimed = cfg._CachedOnlineConfig({"stats_url": cached_url, "latest_version": "1.2.3"}, None)
    assert cfg._unexpired_online(untimed) == {"latest_version": "1.2.3"}
    use_local_file(monkeypatch, tmp_path, {})
    monkeypatch.setattr(cfg, "fetch_online_config", lambda *args, **kwargs: untimed)
    config = cfg.load_config()
    assert config["stats_url"] == cfg.DEFAULT_CONFIG["stats_url"]
    assert cfg.effective_stats_url(config) == cfg.DEFAULT_CONFIG["stats_url"]
    assert config["latest_version"] == "1.2.3"


@pytest.mark.parametrize("value", [
    "https://whisper-transcriber-suite.com/a b",
    "https://whisper-transcriber-suite.com/a\tb",
    "https://whisper-transcriber-suite.com/a\u00a0b",
    "https://whisper-transcriber-suite.com/a\u2028b",
    "https://whisper-transcriber-suite.com/a\x7fb",
    "https://whisper-transcriber-suite.com/caf\u00e9",
    "https://st\u00e4ts.whisper-transcriber-suite.com/x",
])
def test_online_stats_rejects_whitespace_and_non_printable_ascii(value):
    assert not cfg._online_stats_url_allowed(value)
    merged = cfg.merge_config_sources(cfg.DEFAULT_CONFIG, {"stats_url": value}, None)
    assert merged["stats_url"] == cfg.DEFAULT_CONFIG["stats_url"]


def test_online_stats_host_is_at_most_253_characters():
    def host(length):
        prefix = ("a" * 63 + ".") * 3
        suffix = "." + cfg.ONLINE_STATS_HOST
        name = prefix + "b" * (length - len(prefix) - len(suffix)) + suffix
        assert len(name) == length
        return name

    assert cfg._online_stats_url_allowed(f"https://{host(253)}/x")
    assert not cfg._online_stats_url_allowed(f"https://{host(254)}/x")
