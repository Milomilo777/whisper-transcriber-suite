"""Invalid AI action replies must not be reported as a valid empty task list."""
from types import SimpleNamespace
import pytest
from core import llm


@pytest.mark.parametrize("runner_type", [llm.LLMRunner, llm.RemoteLLMRunner])
@pytest.mark.parametrize("raw", ["Send the report tomorrow.", '["Send the report",',
                                  '{"message":"could not finish"}', '[{"task":"Send the report"}]',
                                  '["Send the report", null]', ""])
def test_runner_refuses_to_classify_invalid_reply_as_no_actions(runner_type, raw):
    calls = []
    runner = SimpleNamespace(_chat=lambda messages, **kwargs: calls.append(messages) or raw)
    with pytest.raises(ValueError) as caught:
        runner_type.action_items(runner, "synthetic transcript")
    assert caught.value.reply == raw
    assert len(calls) == 1


@pytest.mark.parametrize("runner_type", [llm.LLMRunner, llm.RemoteLLMRunner])
def test_explicit_empty_array_is_valid_no_actions(runner_type):
    runner = SimpleNamespace(_chat=lambda *args, **kwargs: "[]")
    assert runner_type.action_items(runner, "synthetic transcript") == []



@pytest.mark.parametrize("raw", ['[1, "valid text"]', '[true]', '["   "]', '[[]]',
                                  '[' * 1100 + '0' + ']' * 1100])
def test_unsupported_or_overdeep_items_preserve_entire_reply(raw):
    runner = SimpleNamespace(_chat=lambda *args, **kwargs: raw)
    with pytest.raises(llm.ActionItemsFormatError) as caught:
        llm.RemoteLLMRunner.action_items(runner, "synthetic transcript")
    assert caught.value.reply == raw


@pytest.mark.parametrize("raw,expected", [('```json\n["call Alice"]\n```', ["call Alice"]),
    ('Here are the tasks: ["send report"] trailing commentary', ["send report"]),
    ('["first"] and also ["second"]', ["first"]), ('```json\n[]\n```', [])])
def test_valid_wrappers_and_first_array_contract_are_preserved(raw, expected):
    runner = SimpleNamespace(_chat=lambda *args, **kwargs: raw)
    assert llm.LLMRunner.action_items(runner, "synthetic transcript") == expected


def test_legacy_best_effort_helper_keeps_previous_coercion_contract():
    assert llm._parse_json_list('[1, "two", 3.5]') == ["1", "two", "3.5"]
    assert llm._parse_json_list("not a JSON reply") == []
