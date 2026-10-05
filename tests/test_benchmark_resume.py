"""tools/benchmark_multilingual.py: resume per (language, model), the read-only model hub,
the fixed sampling seed, aggregation, the report and the fast/best picks."""
import csv
import importlib.util
import os
import sys
from pathlib import Path

import pytest

_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tools", "benchmark_multilingual.py",
)
_spec = importlib.util.spec_from_file_location("benchmark_multilingual_resume", _PATH)
assert _spec is not None and _spec.loader is not None
bm = importlib.util.module_from_spec(_spec)
sys.modules["benchmark_multilingual_resume"] = bm  # dataclasses looks the module up by name
_spec.loader.exec_module(bm)


def _row(lang, model, uid, errors=1, ref_len=10, audio="10.00", decode="5.00"):
    return {
        "language": lang, "model": model, "utterance_id": uid,
        "metric": bm.LANGUAGES[lang][1], "score": f"{errors / ref_len:.4f}",
        "ref_len": str(ref_len), "errors": str(errors),
        "audio_s": audio, "decode_s": decode, "rtf": "0.500",
    }


def _write(path, rows):
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=bm.CSV_FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


class FakeBackend:
    def __init__(self, slug, log):
        self.slug, self.log = slug, log

    def transcribe_to_segments(self, path, *, language=None, duration=0.0):
        self.log.append(("decode", self.slug, language, Path(path).stem))
        return [{"text": "uno dos"}], None

    def unload(self):
        self.log.append(("unload", self.slug))


@pytest.fixture
def fake_run(tmp_path, monkeypatch):
    """run() with fake audio, a fake backend and a counted seed call."""
    log = []
    utterances = {
        lang: [(f"{lang}{i}", tmp_path / f"{lang}{i}.wav", "uno dos tres") for i in (1, 2)]
        for lang in ("es", "fa")
    }
    monkeypatch.setattr(bm, "fetch_utterances", lambda lang, count, cache: utterances[lang][:count])
    monkeypatch.setattr(bm, "audio_seconds", lambda wav: 4.0)

    def fake_load(slug, cache, model_hub=None):
        log.append(("load", slug, model_hub))
        return FakeBackend(slug, log), 0.1

    monkeypatch.setattr(bm, "load_backend", fake_load)
    monkeypatch.setattr(bm, "_seed_decoder", lambda: log.append(("seed",)))
    return log


def test_resume_keeps_complete_pairs_and_redoes_partial_ones(tmp_path, fake_run):
    out = tmp_path / "results.csv"
    complete = [_row("es", "tiny", "es1"), _row("es", "tiny", "es2")]
    partial = [_row("es", "base", "es1")]                 # interrupted after one utterance
    other = [_row("fa", "tiny", "fa1")]                   # a pair this run does not ask for
    _write(out, complete + partial + other)

    bm.run(["es"], ["tiny", "base"], 2, tmp_path, out, resume=True)

    rows = bm.read_results(out)
    assert rows[:2] == complete                           # kept byte for byte
    assert other[0] in rows                               # unrequested pair untouched
    base = [r for r in rows if r["model"] == "base"]
    assert [r["utterance_id"] for r in base] == ["es1", "es2"]
    assert base[0]["errors"] == "1" and base[0]["ref_len"] == "3"   # measured again
    assert ("load", "tiny", None) not in fake_run         # a complete model is never loaded
    assert [e for e in fake_run if e[0] == "load"] == [("load", "base", None)]


def test_resume_redoes_a_pair_measured_with_other_utterances(tmp_path, fake_run):
    out = tmp_path / "results.csv"
    _write(out, [_row("es", "tiny", "es1"), _row("es", "tiny", "es9")])
    bm.run(["es"], ["tiny"], 2, tmp_path, out, resume=True)
    assert [r["utterance_id"] for r in bm.read_results(out)] == ["es1", "es2"]


def test_resume_redoes_a_pair_measured_with_a_smaller_n(tmp_path, fake_run):
    out = tmp_path / "results.csv"
    _write(out, [_row("es", "tiny", "es1")])
    bm.run(["es"], ["tiny"], 2, tmp_path, out, resume=True)
    assert [r["utterance_id"] for r in bm.read_results(out)] == ["es1", "es2"]


def test_without_resume_the_file_starts_empty(tmp_path, fake_run):
    out = tmp_path / "results.csv"
    _write(out, [_row("fa", "tiny", "fa1")])
    bm.run(["es"], ["tiny"], 2, tmp_path, out)
    assert {r["language"] for r in bm.read_results(out)} == {"es"}


def test_rows_survive_a_crash_mid_pair_and_resume_finishes(tmp_path, fake_run, monkeypatch):
    out = tmp_path / "results.csv"
    calls = {"n": 0}
    original = FakeBackend.transcribe_to_segments

    def crash_on_second(self, path, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise KeyboardInterrupt
        return original(self, path, **kw)

    monkeypatch.setattr(FakeBackend, "transcribe_to_segments", crash_on_second)
    with pytest.raises(KeyboardInterrupt):
        bm.run(["es"], ["tiny"], 2, tmp_path, out)
    assert [r["utterance_id"] for r in bm.read_results(out)] == ["es1"]   # flushed
    monkeypatch.setattr(FakeBackend, "transcribe_to_segments", original)
    bm.run(["es"], ["tiny"], 2, tmp_path, out, resume=True)
    assert [r["utterance_id"] for r in bm.read_results(out)] == ["es1", "es2"]


def test_resume_redoes_a_pair_whose_last_row_was_cut_off(tmp_path, fake_run):
    out = tmp_path / "results.csv"
    _write(out, [_row("es", "tiny", "es1")])
    with out.open("a", encoding="utf-8", newline="") as fh:
        fh.write("es,tiny,es2,wer,0.33\n")              # killed mid-row
    bm.run(["es"], ["tiny"], 2, tmp_path, out, resume=True)
    rows = bm.read_results(out)
    assert [r["utterance_id"] for r in rows] == ["es1", "es2"]
    assert all(r["rtf"] for r in rows)
    assert ("load", "tiny", None) in fake_run


def test_seed_is_set_before_every_utterance(tmp_path, fake_run):
    bm.run(["es", "fa"], ["tiny"], 2, tmp_path, tmp_path / "r.csv")
    seq = [e[0] for e in fake_run if e[0] in ("seed", "decode")]
    assert seq == ["seed", "decode"] * 4


def test_model_hub_is_passed_through(tmp_path, fake_run):
    hub = tmp_path / "hub"
    bm.run(["es"], ["tiny"], 1, tmp_path, tmp_path / "r.csv", model_hub=hub)
    assert ("load", "tiny", hub) in fake_run


def test_complete_pairs_needs_the_exact_utterance_list():
    utt = {"es": [("a", Path("a.wav"), ""), ("b", Path("b.wav"), "")]}
    rows = [_row("es", "tiny", "a"), _row("es", "tiny", "b"),
            _row("es", "base", "b"), _row("es", "base", "a"),     # wrong order
            _row("es", "small", "a")]                              # too few
    assert bm.complete_pairs(rows, utt, ["tiny", "base", "small", "medium"]) == {("es", "tiny")}


def test_read_results_refuses_other_columns(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("language,model\nes,tiny\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="unexpected columns"):
        bm.read_results(p)


# ------------------------------------------------------------- read-only model hub

def _patch_backend(monkeypatch, log, existing_ok=True):
    sys.path.insert(0, str(bm.ROOT))
    from core.backends import faster_whisper_be as fwb

    class Probe:
        def load(self):
            log.append("load")          # would download through ensure_model

        def load_existing(self, status_cb=None):
            log.append("load_existing")
            if not existing_ok and status_cb:
                status_cb("Existing model failed to load: boom")
            return existing_ok

    monkeypatch.setattr(fwb, "FasterWhisperBackend", Probe)
    monkeypatch.setattr(fwb, "load_config", fwb.load_config)   # restored after the test
    return fwb


def test_model_hub_loads_in_place_without_download(tmp_path, monkeypatch):
    log = []
    fwb = _patch_backend(monkeypatch, log)
    folder = tmp_path / "hub" / "models--Systran--faster-whisper-tiny"
    folder.mkdir(parents=True)
    (folder / "model.bin").write_bytes(b"x")
    bm.load_backend("tiny", tmp_path / "cache", tmp_path / "hub")
    assert log == ["load_existing"]
    cfg = fwb.load_config()
    assert cfg["model_path"] == str(folder) and cfg["device"] == "cpu"
    assert not (tmp_path / "cache").exists()


def test_model_hub_without_the_model_is_an_error_not_a_download(tmp_path, monkeypatch):
    log = []
    _patch_backend(monkeypatch, log)
    (tmp_path / "hub").mkdir()
    with pytest.raises(SystemExit, match="never downloaded into"):
        bm.load_backend("tiny", tmp_path / "cache", tmp_path / "hub")
    assert log == []
    assert list((tmp_path / "hub").iterdir()) == []


def test_model_hub_load_failure_is_raised(tmp_path, monkeypatch):
    _patch_backend(monkeypatch, [], existing_ok=False)
    folder = tmp_path / "hub" / "models--Systran--faster-whisper-tiny"
    folder.mkdir(parents=True)
    (folder / "model.bin").write_bytes(b"x")
    with pytest.raises(RuntimeError, match="boom"):
        bm.load_backend("tiny", tmp_path / "cache", tmp_path / "hub")


def test_without_a_hub_the_app_download_path_is_used(tmp_path, monkeypatch):
    log = []
    _patch_backend(monkeypatch, log)
    bm.load_backend("tiny", tmp_path / "cache")
    assert log == ["load"]


# ------------------------------------------------------------ aggregate + picks

def _agg(rate, rtf):
    return bm.Aggregate("wer", 1, int(rate * 1000), 1000, 100.0, rtf * 100.0)


def test_aggregate_is_corpus_level():
    rows = [_row("es", "tiny", "a", errors=1, ref_len=2, audio="2.0", decode="1.0"),
            _row("es", "tiny", "b", errors=1, ref_len=8, audio="18.0", decode="5.0")]
    a = bm.aggregate(rows)[("es", "tiny")]
    assert (a.n, a.errors, a.ref_len) == (2, 2, 10)
    assert a.rate == pytest.approx(0.2) and a.rtf == pytest.approx(0.3)


SIZES = {"tiny": 0.075, "base": 0.145, "small": 0.5, "medium": 1.5,
         "large-v3-turbo": 1.6, "large-v3": 3.0}


def test_best_is_the_lowest_error_rate():
    picks = bm.recommend({("fa", "tiny"): _agg(0.9, 0.2), ("fa", "large-v3"): _agg(0.2, 2.0),
                          ("fa", "small"): _agg(0.4, 0.45)}, SIZES)
    assert picks["fa"] == ("small", "large-v3")


def test_fast_is_the_most_accurate_model_up_to_half_a_gigabyte():
    picks = bm.recommend({("es", "tiny"): _agg(0.3, 0.1), ("es", "base"): _agg(0.2, 0.3),
                          ("es", "small"): _agg(0.1, 0.6),
                          ("es", "large-v3-turbo"): _agg(0.05, 1.4)}, SIZES)
    assert picks["es"] == ("small", "large-v3-turbo")      # 0.5 GB is inside the cap
    picks = bm.recommend({("es", "tiny"): _agg(0.3, 0.1), ("es", "base"): _agg(0.2, 0.3),
                          ("es", "small"): _agg(0.25, 0.6)}, SIZES)
    assert picks["es"][0] == "base"                        # speed plays no part


def test_fast_falls_back_to_the_smallest_measured_model():
    picks = bm.recommend({("ja", "large-v3"): _agg(0.1, 2.0),
                          ("ja", "medium"): _agg(0.2, 1.4)}, SIZES)
    assert picks["ja"] == ("medium", "large-v3")


def test_a_model_of_unknown_size_is_never_the_fast_pick():
    picks = bm.recommend({("ja", "custom"): _agg(0.0, 0.1), ("ja", "base"): _agg(0.5, 0.2)},
                         SIZES)
    assert picks["ja"] == ("base", "custom")


def test_ties_go_to_the_faster_model():
    picks = bm.recommend({("tr", "large-v3"): _agg(0.1, 2.0),
                          ("tr", "large-v3-turbo"): _agg(0.1, 1.0),
                          ("tr", "tiny"): _agg(0.4, 0.3), ("tr", "base"): _agg(0.4, 0.2)},
                         SIZES)
    assert picks["tr"] == ("base", "large-v3-turbo")


def test_registry_sizes_feed_the_default_rule():
    sizes = bm.download_sizes()
    assert [m for m in bm.MODELS if sizes[m] <= bm.FAST_MAX_DOWNLOAD_GB] == ["tiny", "base", "small"]


def test_report_orders_languages_and_models_and_formats_cells():
    rows = [_row("zh", "large-v3", "a", errors=3, ref_len=40, audio="12.00", decode="24.00"),
            _row("zh", "tiny", "a", errors=20, ref_len=40, audio="12.00", decode="3.00"),
            _row("fa", "base", "a", errors=5, ref_len=10, audio="10.00", decode="3.00")]
    text = bm.report(rows)
    assert text.index("### fa") < text.index("### zh") < text.index("### Recommended")
    zh = text[text.index("### zh"):text.index("### Recommended")]
    assert zh.index("| tiny |") < zh.index("| large-v3 |")
    assert "| CER |" in zh
    assert "| large-v3 | 0.075 | 3 / 40 | 1 | 12.0 s | 24.0 s | 2.00 |" in zh
    assert "| zh | tiny | large-v3 |" in text


def test_main_report_and_flags(tmp_path, capsys):
    out = tmp_path / "r.csv"
    _write(out, [_row("es", "tiny", "a")])
    assert bm.main(["--report", "--out", str(out)]) == 0
    assert "| es | tiny | tiny |" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        bm.main(["--resume", "--force", "--out", str(out)])
    with pytest.raises(SystemExit, match="--resume"):
        bm.main(["--out", str(out), "--cache", str(tmp_path / "cache")])
    with pytest.raises(SystemExit, match="at least 1"):
        bm.main(["-n", "0", "--resume", "--out", str(out), "--cache", str(tmp_path / "c")])
