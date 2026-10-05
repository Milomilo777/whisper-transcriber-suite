"""docs/evaluations/benchmark-v1: the committed CSV is complete, the published tables are
recomputed from it, and core.language_defaults matches the published picks."""
import csv
import importlib.util
import sys
from pathlib import Path

import pytest

from core import language_defaults as ld
from core.model_manager import DEFAULT_MODEL_SLUG, MODEL_REGISTRY

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "docs" / "evaluations" / "benchmark-v1"
CSV_PATH = BENCH / "results.csv"
README = BENCH / "README.md"

_spec = importlib.util.spec_from_file_location(
    "benchmark_multilingual_results", ROOT / "tools" / "benchmark_multilingual.py")
assert _spec is not None and _spec.loader is not None
bm = importlib.util.module_from_spec(_spec)
sys.modules["benchmark_multilingual_results"] = bm  # dataclasses looks the module up by name
_spec.loader.exec_module(bm)


def _rows():
    return bm.read_results(CSV_PATH)


def _block():
    text = README.read_text(encoding="utf-8")
    start = text.index("<!-- results:start -->") + len("<!-- results:start -->")
    return text[start:text.index("<!-- results:end -->")].strip()


def _cell(lang, model, column):
    section = _block().split(f"### {lang}\n", 1)[1].split("###", 1)[0]
    lines = section.splitlines()
    header = next(line for line in lines if line.startswith("| Model |"))
    columns = [c.strip() for c in header.strip("|").split("|")]
    row = next(line for line in lines if line.startswith(f"| {model} |"))
    return [c.strip() for c in row.strip("|").split("|")][columns.index(column)]


# ------------------------------------------------------------------- the CSV

def test_csv_is_complete_for_every_language_and_model():
    by_pair: dict[tuple[str, str], list[str]] = {}
    for r in _rows():
        by_pair.setdefault((r["language"], r["model"]), []).append(r["utterance_id"])
    assert set(by_pair) == {(lang, m) for lang in bm.LANGUAGES for m in bm.MODELS}
    counts = {len(ids) for ids in by_pair.values()}
    assert len(counts) == 1 and min(counts) >= 5
    for lang in bm.LANGUAGES:
        lists = {tuple(by_pair[(lang, m)]) for m in bm.MODELS}
        assert len(lists) == 1, f"{lang}: models heard different utterances"
        (ids,) = lists
        assert len(set(ids)) == len(ids)


def test_csv_rows_are_internally_consistent():
    for r in _rows():
        errors, ref_len = int(r["errors"]), int(r["ref_len"])
        assert ref_len > 0 and errors >= 0
        assert float(r["score"]) == pytest.approx(errors / ref_len, abs=5e-5)
        assert float(r["rtf"]) == pytest.approx(
            float(r["decode_s"]) / float(r["audio_s"]), abs=2e-3)
        assert r["metric"] == bm.LANGUAGES[r["language"]][1]


# ------------------------------------------------------------ published page

def test_published_tables_are_the_report_of_the_csv():
    assert _block() == bm.report(_rows())


def test_two_cells_recomputed_from_the_csv_without_the_tool():
    with CSV_PATH.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    fa = [r for r in rows if r["language"] == "fa" and r["model"] == "large-v3"]
    wer = sum(int(r["errors"]) for r in fa) / sum(int(r["ref_len"]) for r in fa)
    assert _cell("fa", "large-v3", "WER") == f"{wer:.3f}"
    zh = [r for r in rows if r["language"] == "zh" and r["model"] == "small"]
    rtf = sum(float(r["decode_s"]) for r in zh) / sum(float(r["audio_s"]) for r in zh)
    assert _cell("zh", "small", "RTF") == f"{rtf:.2f}"


def test_page_is_linked_from_comparison_and_llms_txt():
    assert "evaluations/benchmark-v1/README.md" in (ROOT / "docs" / "COMPARISON.md").read_text(
        encoding="utf-8")
    assert "docs/evaluations/benchmark-v1/README.md" in (ROOT / "site" / "llms.txt").read_text(
        encoding="utf-8")


# --------------------------------------------------------- core defaults table

def test_core_defaults_are_the_published_picks():
    picks = bm.recommend(bm.aggregate(_rows()))
    table = {lang: (row["fast"], row["best"]) for lang, row in ld.MODEL_BY_LANGUAGE.items()}
    assert table == picks
    recommended = _block().split("### Recommended models", 1)[1]
    for lang, (fast, best) in picks.items():
        assert f"| {lang} | {fast} | {best} |" in recommended


def test_every_row_names_a_registry_model():
    for lang, row in ld.MODEL_BY_LANGUAGE.items():
        assert set(row) == {"fast", "best"}, lang
        for slug in row.values():
            assert slug in MODEL_REGISTRY, (lang, slug)


@pytest.mark.parametrize("mode", ["fast", "best"])
def test_measured_languages_use_the_table(mode):
    for lang, row in ld.MODEL_BY_LANGUAGE.items():
        assert ld.recommended_model(lang, mode) == row[mode]
        assert ld.recommended_model(lang.upper(), mode) == row[mode]


@pytest.mark.parametrize("language", ["en", "de", "ko", "", None, "auto"])
@pytest.mark.parametrize("mode", ["fast", "best"])
def test_unmeasured_languages_keep_todays_default(language, mode):
    assert ld.recommended_model(language, mode) == DEFAULT_MODEL_SLUG


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        ld.recommended_model("fa", "balanced")
