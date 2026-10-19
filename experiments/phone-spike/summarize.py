"""Build a traceable report from raw benchmark JSON; standard library only."""
import argparse
import json
import random
import statistics

from runtime import write_text


def aggregate_metric(files, edits_key, denominator_key):
    pairs = [(item[edits_key], item[denominator_key]) for item in files
             if edits_key in item and item.get(denominator_key, 0) > 0 and "error" not in item]
    if not pairs:
        return {"edits": 0, "reference": 0, "rate": None, "pairs": []}
    edits = sum(e for e, _ in pairs)
    length = sum(n for _, n in pairs)
    return {"edits": edits, "reference": length, "rate": edits / length, "pairs": pairs}


def _percentile(values, fraction):
    values = sorted(values)
    index = (len(values) - 1) * fraction
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (index - lower)


def _interval(values, point):
    # Conservative finite-resample interval: include the observed point estimate.
    return min(point, _percentile(values, .025)), max(point, _percentile(values, .975))


def bootstrap_ci(data, num_resamples=1000, seed=1234):
    """Resample utterance (edit count, reference length) PAIRS, then take ratios."""
    pairs = list(data)
    if not pairs or num_resamples < 1 or any(e < 0 or n <= 0 for e, n in pairs):
        raise ValueError("Bootstrap needs nonnegative edits, positive lengths and resamples")
    rng = random.Random(seed)
    values = []
    for _ in range(num_resamples):
        sample = [pairs[rng.randrange(len(pairs))] for _ in pairs]
        values.append(sum(e for e, _ in sample) / sum(n for _, n in sample))
    point = sum(e for e, _ in pairs) / sum(n for _, n in pairs)
    return _interval(values, point)


def paired_comparison(first, second, num_resamples=1000, seed=1234):
    """Pair by utterance id, never by insertion order or merely equal lengths."""
    ids = sorted(set(first) & set(second))
    deltas = []
    for key in ids:
        a, b = first[key], second[key]
        if a.get("ref") != b.get("ref"):
            continue
        if a.get("wer_words", 0) <= 0 or a.get("wer_words") != b.get("wer_words"):
            continue
        if "error" in a or "error" in b or "wer_edits" not in a or "wer_edits" not in b:
            continue
        deltas.append(a["wer_edits"] / a["wer_words"] - b["wer_edits"] / b["wer_words"])
    if not deltas:
        return None
    rng = random.Random(seed)
    point = statistics.mean(deltas)
    means = [statistics.mean(deltas[rng.randrange(len(deltas))] for _ in deltas)
             for _ in range(num_resamples)]
    return {"n": len(deltas), "mean_delta": point, "ci": _interval(means, point),
            "wins": sum(d < 0 for d in deltas), "ties": sum(d == 0 for d in deltas),
            "losses": sum(d > 0 for d in deltas)}


def _fmt(value, digits=3):
    return "unknown" if value is None else f"{value:.{digits}f}"


def _cell(value):
    return str(value if value is not None else "unknown").replace("|", "\\|").replace("\n", " ")


def _normal_files(run):
    return {key: value for key, value in run.get("files", {}).items()
            if key != "long_form" and "error" not in value}


def _successful(run):
    # The historical `failed` flag records any error; PARTIAL retains usable rows.
    if run.get("status") == "PARTIAL":
        return True
    return not run.get("failed", False) and run.get("status", "OK") not in ("FAILED", "UNAVAILABLE")


def _short_counts(run):
    files = [value for key, value in run.get("files", {}).items() if key != "long_form"]
    bad = sum("error" in item for item in files)
    return len(files) - bad, bad


def _median_metric(metric):
    return statistics.median(e / n for e, n in metric["pairs"]) if metric["pairs"] else None


def _rtf(run):
    if not run or not _successful(run):
        return None
    values = [item["rtf"] for item in _normal_files(run).values() if "rtf" in item]
    return statistics.median(values) if values else None


def build_summary(data):
    env = data.get("env", {})
    settings = env.get("statistics", {})
    count, seed = settings.get("bootstrap_resamples", 1000), settings.get("seed", 1234)
    md = ["# Phone Spike Summary", "",
          f"Environment: {_cell(env.get('cpu_model'))}; architecture: {_cell(env.get('architecture'))}; "
          f"logical CPUs: {_cell(env.get('nproc'))}; RAM MB: {_fmt(env.get('ram_mb'))}; "
          f"governor: {_cell(env.get('governor'))}.", "",
          "This host is not a phone. Desktop/VM speed rankings are an x86 proxy when run on x86; "
          "the Android ranking is unknown until the same runners run on a physical phone.", "",
          f"Headline WER/CER = sum edits / sum reference lengths. Utterance bootstrap: {count} resamples, "
          f"seed {seed}, percentile 95% CI (conservatively includes the point). MB means 1024 squared bytes. "
          "Short-file metrics exclude long_form. Metrics use 4 threads when successful, otherwise 1 "
          "or the lowest successful thread count, identified below. Missing references are unknown. "
          "PARTIAL jobs aggregate over good rows only. Table good/bad short-file counts refer to the "
          "metric thread; each thread's counts and status appear beside its numbers in the trace.", "",
          "| Engine/model/quant | Status | Metric threads | Good short files | Bad short files | Model MB | Agg WER | WER 95% CI | Median WER | "
          "Agg CER | CER 95% CI | Median CER | WER ZWNJ space | Median RTF 1 | Median RTF 4 | Peak RSS MB | "
          "Runtime licence | Model licence | Android binding (link) | Integration notes |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    rows = []
    for name, runs in sorted(data.items()):
        if name == "env":
            continue
        runs = {key: value for key, value in runs.items() if key.isdigit()}
        good = {key: value for key, value in runs.items() if _successful(value)}
        selected = "4" if "4" in good else "1" if "1" in good else min(good, key=int) if good else None
        anchor = good[selected] if selected else {}
        info = anchor.get("info") or next((r["info"] for r in runs.values() if r.get("info")), {})
        files = _normal_files(anchor)
        w = aggregate_metric(files.values(), "wer_edits", "wer_words")
        c = aggregate_metric(files.values(), "cer_edits", "cer_chars")
        z = aggregate_metric(files.values(), "wer_zwnj_edits", "wer_zwnj_words")
        def interval(metric):
            if not metric["pairs"]:
                return "unknown"
            low, high = bootstrap_ci(metric["pairs"], count, seed)
            return f"[{low:.3f}, {high:.3f}]"
        rss_values = []
        for run in good.values():
            rss_values += [v["peak_rss_mb"] for v in run.get("files", {}).values() if v.get("peak_rss_mb") is not None]
            if run.get("peak_rss_mb") is not None:
                rss_values.append(run["peak_rss_mb"])
        if not good:
            status = "UNAVAILABLE" if runs and all(r.get("status") == "UNAVAILABLE" for r in runs.values()) else "FAILED"
        else:
            status = "PARTIAL" if len(good) != len(runs) or any(r.get("status") == "PARTIAL" for r in good.values()) else "OK"
        good_count, bad_count = _short_counts(anchor) if selected else (None, None)
        values = [name, status, selected, good_count, bad_count,
                  _fmt(info.get("model_size_mb")), _fmt(w["rate"]), interval(w),
                  _fmt(_median_metric(w)), _fmt(c["rate"]), interval(c), _fmt(_median_metric(c)),
                  _fmt(z["rate"]), _fmt(_rtf(good.get("1"))), _fmt(_rtf(good.get("4"))),
                  _fmt(max(rss_values) if rss_values else None), info.get("runtime_license", "unknown"),
                  info.get("model_license", "unknown"), info.get("android_binding", "unknown"),
                  info.get("integration_notes", "unknown")]
        md.append("| " + " | ".join(_cell(v) for v in values) + " |")
        rows.append({"name": name, "runs": runs, "good": good, "selected": selected,
                     "files": files, "w": w, "c": c, "z": z, "info": info})
    if not rows:
        md += ["", "No engine runs found."]
    md += ["", "## Trace and errors", ""]
    for row in rows:
        md += [f"### {_cell(row['name'])}", ""]
        if row["selected"]:
            parts = [f"{label}: {row[key]['edits']}/{row[key]['reference']}"
                     for label, key in (("WER edits/words", "w"), ("CER edits/characters", "c"),
                                        ("ZWNJ-space edits/words", "z")) if row[key]["pairs"]]
            md.append("; ".join(parts) + "." if parts else "Accuracy unknown: no scored references.")
        for threads, run in sorted(row["runs"].items(), key=lambda pair: int(pair[0])):
            status = run.get("status", "FAILED" if run.get("failed") else "OK")
            good_count, bad_count = _short_counts(run)
            prefix = f"- Threads {threads}: {status}; good/bad short files {good_count}/{bad_count}; "
            if not _successful(run):
                md.append(prefix + _cell(run.get("error")))
            else:
                md.append(prefix + f"load seconds {_fmt(run.get('load_s'))}; "
                          f"median short-file RTF {_fmt(_rtf(run))}; RSS source {_cell(run.get('rss_source'))}.")
                if run.get("error"):
                    md.append("Errors: " + _cell(run["error"]))
            if run.get("timeout_s") is not None:
                md.append(f"Timeout seconds {_fmt(run['timeout_s'])} ({_cell(run.get('timeout_source'))}).")
        if row["info"].get("timing_notes"):
            md.append("Timing caveat: " + _cell(row["info"]["timing_notes"]))
        md.append("")
    md += ["## Long form", "",
           "| Engine | Threads | WER | Repeated trigrams hyp/ref | Aligned deletions | Duration seconds |",
           "|---|---|---|---|---|---|"]
    for row in rows:
        for threads, run in sorted(row["runs"].items(), key=lambda pair: int(pair[0])):
            lf = run.get("files", {}).get("long_form")
            if not lf:
                continue
            w = aggregate_metric([lf], "wer_edits", "wer_words") if _successful(run) else {"rate": None}
            md.append("| " + " | ".join(_cell(v) for v in
                (row["name"], threads, _fmt(w["rate"]),
                 f"{lf.get('repeated_ngrams', 'unknown')}/{lf.get('ref_repeated_ngrams', 'unknown')}",
                 lf.get("word_deletions", "unknown"), _fmt(lf.get("audio_s")))) + " |")
    md += ["", "Repeated trigrams and aligned deletions are diagnostics, not proof of hallucination or dropped speech. "
           "Duration is measured; 25 utterances need not total five minutes.", "",
           "## Paired per-utterance comparison", ""]
    comparison = None
    for threads in ("4", "1") + tuple(sorted({key for row in rows for key in row["good"]} - {"1", "4"}, key=int)):
        candidates = []
        for row in rows:
            run = row["good"].get(threads)
            if not run or "large-v3-turbo" in row["name"]:
                continue
            files = _normal_files(run)
            metric = aggregate_metric(files.values(), "wer_edits", "wer_words")
            if metric["rate"] is not None:
                candidates.append((metric["rate"], row["name"], files))
        candidates.sort(key=lambda candidate: (candidate[0], candidate[1]))
        if len(candidates) >= 2:
            first, second = candidates[:2]
            paired = paired_comparison(first[2], second[2], count, seed)
            if paired:
                low, high = paired["ci"]
                comparison = (f"{first[1]} vs {second[1]} at {threads} threads; matched utterances {paired['n']}; "
                              f"first-engine wins/ties/losses {paired['wins']}/{paired['ties']}/{paired['losses']}; "
                              f"mean per-utterance WER delta (first minus second) {paired['mean_delta']:.3f}; "
                              f"paired bootstrap 95% CI [{low:.3f}, {high:.3f}].")
                break
    md.append(comparison or "unknown: fewer than two successful, scored engines with matching references at the same thread count.")
    md += ["", "## Samples", ""]
    for row in rows:
        md += [f"### {_cell(row['name'])}", ""]
        run = row["good"].get(row["selected"], {}) if row["selected"] else next(iter(row["runs"].values()), {})
        samples = sorted((key, value) for key, value in run.get("files", {}).items() if key != "long_form")[:2]
        for key, item in samples:
            md += [f"- ID: {_cell(key)}; ref: {_cell(item.get('ref'))}; hyp: {_cell(item.get('hyp'))}"]
        if len(samples) < 2:
            md.append("Two reference/hypothesis pairs unavailable for this engine.")
        md.append("")
    return "\n".join(md).rstrip() + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    with open(args.json, encoding="utf-8") as source:
        data = json.load(source)
    write_text(args.out, build_summary(data))


if __name__ == "__main__":
    main()
