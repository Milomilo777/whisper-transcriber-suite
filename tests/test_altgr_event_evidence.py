"""Native callback evidence controls, with no Tk or Windows API execution."""
import ast
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


HELPERS = Path(__file__).resolve().parents[1] / "tools/qa"


def loader():
    spec = importlib.util.spec_from_file_location("event_loader", HELPERS / "hosted_altgr_loader.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def event(key=65, result=None):
    return {"keycode": key, "state": 0x20004, "keysym": "a" if key == 65 else "Alt_R", "result": result}


def row(records):
    return {"vk": 65, "phase": "actual_app_hook", "text": "a", "expected_altgr": "a",
            "virtual_actions": [], "handler_results": records}


@pytest.mark.parametrize("records", [[event(0xA5)], [event(65, "break")], [event(), event(0xA5, "break")]])
def test_modifier_only_or_consumed_event_is_not_target_coverage(records):
    assert loader().covered_keys([row(records)]) == []


def test_target_callback_with_state_and_keysym_is_coverage():
    assert loader().covered_keys([row([event(0xA5), event()])]) == [65]


def native_tree():
    return ast.parse((HELPERS / "test_altgr_acceptance.py").read_text(encoding="utf-8"))


def test_actual_wrapper_retains_one_complete_record_per_event():
    wrapped = next(n for n in ast.walk(native_tree()) if isinstance(n, ast.FunctionDef) and n.name == "wrapped")
    records = []
    namespace = {"handler_results": records, "handler": lambda e: None}
    exec(compile(ast.Module(body=[wrapped], type_ignores=[]), "<actual-wrapper>", "exec"), namespace)
    for key in (0xA5, 65):
        observed = event(key)
        assert namespace["wrapped"](SimpleNamespace(**{k: v for k, v in observed.items() if k != "result"})) is None
    assert records == [event(0xA5), event()]


def test_case_receipt_retains_callback_records_before_post_input_guards():
    tree = native_tree()
    assignment = next(n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "row" for t in n.targets))
    records, generic = [], []
    namespace = {"phase": "actual_app_hook", "vk": 65, "expected": "a", "proofs": [],
                 "handler_results": records, "events": generic, "virtual_actions": []}
    exec(compile(ast.Module(body=[assignment], type_ignores=[]), "<actual-case-receipt>", "exec"), namespace)
    records.append(event())
    generic.append({"keycode": 65, "state": 0, "keysym": "a", "char": "a"})
    # A focus guard may fail before row.update(); finally must retain both facts.
    assert namespace["row"]["handler_results"] == [event()]
    assert namespace["row"]["events"] == generic


@pytest.mark.parametrize("records", [[], [event(0xA5)], [event(65, "break")]])
def test_actual_native_assert_requires_the_target_callback(records):
    branch = next(n for n in ast.walk(native_tree()) if isinstance(n, ast.If) and n.orelse
                  and any(isinstance(x, ast.Constant) and x.value == "plain_entry_baseline" for x in ast.walk(n.test)))
    namespace = {"entry": SimpleNamespace(get=lambda: "a"), "baselines": {65: "a"}, "vk": 65,
                 "virtual_actions": [], "handler_results": records, "row": row(records)}
    with pytest.raises(AssertionError):
        exec(compile(ast.Module(body=branch.orelse, type_ignores=[]), "<actual-native-assert>", "exec"), namespace)


def test_actual_native_assert_accepts_observed_target_callback():
    branches = [n for n in ast.walk(native_tree()) if isinstance(n, ast.If) and n.orelse
                and any(isinstance(x, ast.Constant) and x.value == "plain_entry_baseline" for x in ast.walk(n.test))]
    assert len(branches) == 1
    records = [event(0xA5), event()]
    observed = row(records)
    namespace = {"entry": SimpleNamespace(get=lambda: "a"), "baselines": {65: "a"}, "vk": 65,
                 "virtual_actions": [], "handler_results": records, "row": observed}
    exec(compile(ast.Module(body=branches[0].orelse, type_ignores=[]), "<actual-positive-native-assert>", "exec"), namespace)
    assert observed["target_callback_observed"] is True
    assert observed["character_delivered"] is True
    assert observed["hook_body_observation"] == "OBSERVED"


def test_non_ascii_fatal_cause_survives_cp1252_stdout(tmp_path):
    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="cp1252", errors="strict")
    reason = "Fatal AltGr character: \u202f\u263a"
    summary = tmp_path / "summary.md"
    with redirect_stdout(stream):
        loader().report_verdict({"status": "FAIL", "message": reason}, summary)
    stream.flush()
    annotation = buffer.getvalue().decode("cp1252")
    assert "::error title=AltGr acceptance FAIL::Fatal AltGr character: \\u202f\\u263a" in annotation
    assert "\u263a" in summary.read_text(encoding="utf-8")
    assert "\\u263a" not in summary.read_text(encoding="utf-8")


@pytest.mark.parametrize("status,extra,wanted", [
    ("FAIL", {"message": "Owned focus/layout changed after chord"}, "Owned focus/layout changed after chord"),
    ("FAIL", {"reason": "baseline text unavailable"}, "baseline text unavailable"),
    ("FAIL-CLEANUP", {"cleanup_errors": ["right Alt key release incomplete"]}, "right Alt key release incomplete"),
])
def test_raw_fatal_receipt_cause_reaches_annotation(tmp_path, capsys, status, extra, wanted):
    raw = tmp_path / "raw.json"
    raw.write_text(json.dumps({"status": status, "observations": [], **extra}), encoding="utf-8")
    module = loader()
    identity = {"status": status}
    module.apply_probe_evidence(identity, json.loads(raw.read_text(encoding="utf-8")))
    module.report_verdict(identity, None)
    assert wanted in capsys.readouterr().out


def test_missing_coverage_and_loader_cleanup_causes_are_visible(capsys):
    module = loader()
    module.report_verdict({"status": "INCOMPLETE-KEY-COVERAGE", "missing_keys": [65, 67]}, None)
    assert "65, 67" in capsys.readouterr().out
    module.report_verdict({"status": "FAIL-CLEANUP", "cleanup_errors": ["original layout restoration failed"]}, None)
    assert "original layout restoration failed" in capsys.readouterr().out


def test_nonpass_without_summary_path_still_emits_annotation(capsys):
    loader().report_verdict({"status": "FAIL", "message": "real failure"}, None)
    assert "::error title=AltGr acceptance FAIL::real failure" in capsys.readouterr().out


def test_pass_emits_no_annotation_and_writes_no_summary(tmp_path, capsys):
    path = tmp_path / "summary.md"
    loader().report_verdict({"status": "PASS"}, path)
    assert not path.exists()
    assert "::" not in capsys.readouterr().out


def test_summary_write_failure_keeps_the_native_verdict_visible(tmp_path, capsys):
    loader().report_verdict({"status": "FAIL", "message": "original fatal cause"}, tmp_path / "missing/summary.md")
    output = capsys.readouterr().out
    assert "::error title=AltGr acceptance FAIL::original fatal cause" in output
    assert "::warning" in output


def test_summary_keeps_multiline_markdown_and_html_reason_inert(tmp_path):
    path = tmp_path / "summary.md"
    loader().report_verdict({"status": "FAIL", "message": "first\nsecond `<script>` **bold** & tail"}, path)
    summary = path.read_text(encoding="utf-8")
    assert "<pre>first second `&lt;script&gt;` **bold** &amp; tail</pre>" in summary
    assert "first\nsecond" not in summary
    assert "<script>" not in summary
