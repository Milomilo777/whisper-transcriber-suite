import json
import subprocess
import sys
from pathlib import Path

import pytest
from summarize import aggregate_metric, bootstrap_ci, build_summary, paired_comparison

SPIKE = Path(__file__).resolve().parent.parent

def test_summarize(tmp_path):
    data = {
        "env": {"nproc": 4},
        "fake1": {
            "1": {
                "failed": False,
                "info": {"model_size_mb": 1, "runtime_license": "MIT", "model_license": "MIT"},
                "files": {
                    "0001": {"wer_edits": 1, "wer_words": 10, "cer_edits": 2, "cer_chars": 50, "wer_zwnj_edits": 1, "wer_zwnj_words": 10, "rtf": 0.1, "peak_rss_mb": 10, "ref": "من"},
                    "0002": {"wer_edits": 2, "wer_words": 10, "cer_edits": 4, "cer_chars": 50, "wer_zwnj_edits": 2, "wer_zwnj_words": 10, "rtf": 0.2, "peak_rss_mb": 15, "ref": "من"},
                    "long_form": {"wer_edits": 1, "wer_words": 10, "repeated_ngrams": 5, "ref": "من", "hyp": "من من من من من من"}
                }
            }
        },
        "fake2": {
            "1": {
                "failed": False,
                "info": {"model_size_mb": 2, "runtime_license": "MIT", "model_license": "MIT"},
                "files": {
                    "0001": {"wer_edits": 0, "wer_words": 10, "cer_edits": 0, "cer_chars": 50, "wer_zwnj_edits": 0, "wer_zwnj_words": 10, "rtf": 0.3, "peak_rss_mb": 20, "ref": "من"},
                    "0002": {"wer_edits": 1, "wer_words": 10, "cer_edits": 2, "cer_chars": 50, "wer_zwnj_edits": 1, "wer_zwnj_words": 10, "rtf": 0.4, "peak_rss_mb": 25, "ref": "من"},
                    "long_form": {"wer_edits": 1, "wer_words": 10, "repeated_ngrams": 0, "ref": "من", "hyp": "من"}
                }
            }
        }
    }
    jpath = tmp_path / "test.json"
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(data, f)
        
    outpath = tmp_path / "SUMMARY.md"
    subprocess.run([sys.executable, "-S", str(SPIKE / "summarize.py"), "--json", str(jpath), "--out", str(outpath)], check=True)
    
    with open(outpath, encoding="utf-8") as f:
        md = f.read()
    
    assert "fake1" in md
    assert "fake2" in md
    assert "Paired per-utterance comparison" in md


def test_aggregate_is_ratio_of_sums_not_mean_of_ratios():
    metric = aggregate_metric([{"e": 1, "n": 2}, {"e": 1, "n": 8}], "e", "n")
    assert metric["edits"] == 2
    assert metric["reference"] == 10
    assert metric["rate"] == .2
    assert metric["rate"] != (1/2 + 1/8) / 2
    assert aggregate_metric([{}], "e", "n")["rate"] is None


def test_bootstrap_resamples_edit_length_pairs_reproducibly():
    pairs = [(0, 1), (2, 100), (8, 10), (1, 3)]
    first = bootstrap_ci(pairs, 1000, 1234)
    assert first == bootstrap_ci(pairs, 1000, 1234)
    assert first != bootstrap_ci(pairs, 1000, 4321)
    point = 11/114
    assert first[0] <= point <= first[1]
    # Independent, literal reference implementation protects the ratio statistic.
    import random
    rng = random.Random(1234)
    ratios = []
    for _ in range(1000):
        indices = [rng.randrange(4) for _ in range(4)]
        ratios.append(sum(pairs[i][0] for i in indices) / sum(pairs[i][1] for i in indices))
    ratios.sort()
    def percentile(p):
        index = 999 * p
        lo = int(index)
        return ratios[lo] + (ratios[lo + 1] - ratios[lo]) * (index - lo)
    assert first == pytest.approx((min(point, percentile(.025)), max(point, percentile(.975))))
    assert bootstrap_ci([(1, 4)], 10) == (.25, .25)
    assert bootstrap_ci([(0, 3), (0, 100)]) == (0, 0)


@pytest.mark.parametrize("pairs,count", [([], 10), ([(0, 0)], 10), ([(-1, 5)], 10), ([(1, 2)], 0)])
def test_bootstrap_rejects_invalid_data(pairs, count):
    with pytest.raises(ValueError):
        bootstrap_ci(pairs, count)


def test_paired_comparison_joins_ids_and_equal_references():
    a = {"first": {"ref": "a", "wer_edits": 0, "wer_words": 1},
         "second": {"ref": "b", "wer_edits": 1, "wer_words": 1},
         "only-a": {"ref": "c", "wer_edits": 9, "wer_words": 1}}
    b = {"second": {"ref": "b", "wer_edits": 0, "wer_words": 1},
         "first": {"ref": "a", "wer_edits": 1, "wer_words": 1},
         "only-b": {"ref": "d", "wer_edits": 0, "wer_words": 1}}
    result = paired_comparison(a, b)
    assert result["n"] == 2
    assert result["mean_delta"] == 0
    assert (result["wins"], result["ties"], result["losses"]) == (1, 0, 1)
    assert result["ci"] == (-1, 1)
    assert result == paired_comparison(a, b)
    b["first"]["ref"] = "different"
    assert paired_comparison(a, b)["n"] == 1


def small_fixture():
    import copy
    first = {"ref": "aa‌bb cc dd ee", "hyp": "aabb cc dd xx", "wer_edits": 1, "wer_words": 4,
             "cer_edits": 2, "cer_chars": 10, "wer_zwnj_edits": 3, "wer_zwnj_words": 5,
             "rtf": .1, "peak_rss_mb": 20}
    second = {"ref": "f", "hyp": "x", "wer_edits": 1, "wer_words": 1,
              "cer_edits": 1, "cer_chars": 1, "wer_zwnj_edits": 1, "wer_zwnj_words": 1,
              "rtf": .3, "peak_rss_mb": 30}
    run = {"failed": False, "load_s": .125,
           "info": {"model_size_mb": 12.5, "runtime_license": "runtime-A", "model_license": "model-A",
                    "android_binding": "[binding](https://example.invalid/binding)", "integration_notes": "fixture notes"},
           "files": {"one": first, "two": second,
                     "long_form": {"wer_edits": 3, "wer_words": 6, "rtf": 9, "peak_rss_mb": 50,
                                   "repeated_ngrams": 2, "ref_repeated_ngrams": 0,
                                   "word_deletions": 1, "audio_s": 100}}}
    four = copy.deepcopy(run)
    four["files"]["one"].update(rtf=.04, peak_rss_mb=40)
    four["files"]["two"].update(rtf=.08, peak_rss_mb=40)
    better = copy.deepcopy(four)
    better["files"]["two"].update(hyp="f", wer_edits=0, cer_edits=0, wer_zwnj_edits=0)
    better["files"] = dict(reversed(list(better["files"].items())))
    return {"env": {"cpu_model": "fixture CPU", "nproc": 4, "governor": "fixture governor",
                    "statistics": {"seed": 1234, "bootstrap_resamples": 1000}},
            "engine-a": {"1": run, "4": four}, "engine-b": {"4": better},
            "broken": {"1": {"failed": True, "error": "fixture engine error", "info": None,
                              "files": {"one": {"wer_edits": 0, "wer_words": 100}}}}}


def test_summary_every_table_number_is_traceable(tmp_path):
    data = small_fixture()
    source, output = tmp_path / "fixture.json", tmp_path / "nested/SUMMARY.md"
    source.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    subprocess.run([sys.executable, "-S", str(SPIKE / "summarize.py"), "--json", str(source),
                    "--out", str(output)], check=True, capture_output=True)
    text = output.read_text(encoding="utf-8")
    table = [line for line in text.splitlines() if line.startswith("| ")]
    headings = [part.strip() for part in table[0].strip("|").split("|")]
    rows = {line.split("|")[1].strip(): dict(zip(headings, [p.strip() for p in line.strip("|").split("|")]))
            for line in table[1:4]}
    row = rows["engine-a"]
    expected = {"Status": "OK", "Metric threads": "4", "Model MB": "12.500", "Agg WER": "0.400",
                "WER 95% CI": "[0.250, 1.000]", "Median WER": "0.625", "Agg CER": "0.273",
                "CER 95% CI": "[0.200, 1.000]", "Median CER": "0.600", "WER ZWNJ space": "0.667",
                "Median RTF 1": "0.200", "Median RTF 4": "0.060", "Peak RSS MB": "50.000",
                "Runtime licence": "runtime-A", "Model licence": "model-A",
                "Android binding (link)": "[binding](https://example.invalid/binding)", "Integration notes": "fixture notes"}
    for key, value in expected.items():
        assert row[key] == value, key
    assert rows["engine-b"]["Agg WER"] == "0.200"
    assert rows["engine-b"]["Median RTF 1"] == "unknown"
    assert rows["broken"]["Status"] == "FAILED"
    assert rows["broken"]["Agg WER"] == "unknown"
    assert "fixture engine error" in text
    assert "WER edits/words: 2/5; CER edits/characters: 3/11; ZWNJ-space edits/words: 4/6" in text
    assert "| engine-a | 4 | 0.500 | 2/0 | 1 | 100.000 |" in text
    assert "engine-b vs engine-a at 4 threads; matched utterances 2" in text
    assert "wins/ties/losses 1/1/0" in text
    assert "WER delta (first minus second) -0.500" in text
    assert "ref: aa‌bb cc dd ee; hyp: aabb cc dd xx" in text
    assert "ref: f; hyp: x" in text
    assert "fixture CPU" in text and "fixture governor" in text
    assert text == build_summary(data)


def test_missing_references_and_failed_runs_are_not_perfect_scores():
    data = {"env": {}, "private": {"1": {"files": {"one": {"hyp": "private", "rtf": .4}}, "info": None}},
            "unavailable": {"4": {"failed": True, "error": "missing runtime", "info": None, "files": {}}}}
    text = build_summary(data)
    private = next(line for line in text.splitlines() if line.startswith("| private |"))
    assert "| unknown | unknown | unknown | unknown |" in private
    assert "missing runtime" in text
    assert "Two reference/hypothesis pairs unavailable" in text
    assert "No engine runs found" in build_summary({"env": {}})


def main_table_row(text, name):
    lines = [line for line in text.splitlines() if line.startswith("| ")]
    headings = [part.strip() for part in lines[0].strip("|").split("|")]
    row = next(line for line in lines if line.startswith(f"| {name} |"))
    return dict(zip(headings, [part.strip() for part in row.strip("|").split("|")]))


def test_summary_partial_status_counts_and_metrics_use_good_rows_only():
    data = small_fixture()
    run = data["engine-a"]["4"]
    run.update(status="PARTIAL", failed=True, error="one bad reference",
               counts={"good": 2, "bad": 1, "total": 3},
               short_counts={"good": 1, "bad": 1, "total": 2})
    run["files"]["two"].update(error="one bad reference", rtf=999)
    text = build_summary(data)
    row = main_table_row(text, "engine-a")
    assert row["Status"] == "PARTIAL"
    assert row["Metric threads"] == "4"
    assert row["Good short files"] == "1" and row["Bad short files"] == "1"
    assert row["Agg WER"] == row["Median WER"] == "0.250"
    assert row["Agg CER"] == row["Median CER"] == "0.200"
    assert row["WER ZWNJ space"] == "0.600"
    assert row["Median RTF 4"] == "0.040"
    assert row["Median RTF 1"] == "0.200"
    assert "good rows only" in text
    assert "Threads 4: PARTIAL; good/bad short files 1/1" in text
    assert "one bad reference" in text
    assert "| engine-a | 4 | 0.500 |" in text  # Good long form survives a short-file failure.


@pytest.mark.parametrize("statuses,expected", [
    (["UNAVAILABLE"], "UNAVAILABLE"), (["UNAVAILABLE", "UNAVAILABLE"], "UNAVAILABLE"),
    (["FAILED", "UNAVAILABLE"], "FAILED"), (["OK", "UNAVAILABLE"], "PARTIAL"),
])
def test_summary_distinguishes_unavailable_from_failed_in_main_table(statuses, expected):
    runs = {str(i + 1): {"status": status, "failed": status != "OK", "files": {},
                         "error": "missing runtime" if status == "UNAVAILABLE" else "failed job"}
            for i, status in enumerate(statuses)}
    text = build_summary({"unavailable-fixture": runs})
    assert main_table_row(text, "unavailable-fixture")["Status"] == expected
    for i, status in enumerate(statuses):
        assert f"Threads {i + 1}: {status}" in text
