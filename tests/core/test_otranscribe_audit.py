import pytest
import json
pytest.importorskip("hypothesis")
from hypothesis import given, settings, strategies as st
from core.integrations import otranscribe

def test_fmt_otr_time():
    assert otranscribe.fmt_otr_time(0.0) == "0:00"
    assert otranscribe.fmt_otr_time(59.9) == "0:59"
    assert otranscribe.fmt_otr_time(60.1) == "1:00"
    assert otranscribe.fmt_otr_time(3599.9) == "59:59"
    assert otranscribe.fmt_otr_time(3600.0) == "1:00:00"
    assert otranscribe.fmt_otr_time(-10.0) == "0:00"

def test_srt_to_otr(tmp_path):
    srt_file = tmp_path / "test.srt"
    srt_file.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n\n2\n00:00:02,000 --> 00:00:03,000\nWorld", encoding="utf-8")
    otr_json = otranscribe.srt_to_otr(str(srt_file), "media.mp4")
    data = json.loads(otr_json)
    assert data["media"] == "media.mp4"
    assert "Hello" in data["text"]
    assert "World" in data["text"]

def test_whisper_json_to_otr(tmp_path):
    json_file = tmp_path / "test.json"
    json_file.write_text(json.dumps([{"start": 1.0, "end": 2.0, "text": "Hello"}, {"start": 2.0, "end": 3.0, "text": "World"}]))
    otr_json = otranscribe.whisper_json_to_otr(str(json_file))
    data = json.loads(otr_json)
    assert "Hello" in data["text"]
    assert "World" in data["text"]

def test_segments_to_otr():
    segments = [{"start": 1.0, "end": 2.0, "text": "Hello"}, {"start": 2.0, "end": 3.0, "text": "World"}]
    otr_json = otranscribe.segments_to_otr(segments, "media.mp4")
    data = json.loads(otr_json)
    assert data["media"] == "media.mp4"

def test_otr_to_srt(tmp_path):
    otr_file = tmp_path / "test.otr"
    otr_file.write_text(json.dumps({
        "text": '<p><span class="timestamp" data-timestamp="1.000">0:01</span> Hello</p><p><span class="timestamp" data-timestamp="2.000">0:02</span> World</p>'
    }))
    srt_text = otranscribe.otr_to_srt(str(otr_file))
    assert "00:00:01,000" in srt_text
    assert "00:00:02,000" in srt_text
    assert "Hello" in srt_text
    assert "World" in srt_text

def test_otr_to_srt_untimed(tmp_path):
    otr_file = tmp_path / "test.otr"
    otr_file.write_text(json.dumps({
        "text": '<p><span class="timestamp" data-timestamp="1.000">0:01</span> Hello</p><p>World</p>'
    }))
    srt_text = otranscribe.otr_to_srt(str(otr_file))
    # 'World' should be appended to the first cue
    assert "Hello\nWorld" in srt_text


@settings(derandomize=True, deadline=None, database=None)
@given(st.lists(st.dictionaries(st.sampled_from(["start", "end", "text"]), st.one_of(st.floats(allow_nan=False, allow_infinity=False), st.text()))))
def test_segments_to_otr_robustness(segments):
    # Just to check it doesn't crash on weird valid data
    json_out = otranscribe.segments_to_otr(segments)
    assert isinstance(json_out, str)

def test_newlines_become_spaces_and_tabs_are_kept():
    # We test that the newline replacement works, and that tabs and lone surrogates are kept intact.
    segments = [{"start": 1.0, "end": 2.0, "text": "Hello\ud800World\nNew\rLine\tTab"}]
    otr_json = otranscribe.segments_to_otr(segments)
    data = json.loads(otr_json)
    assert data["text"] == '<p><span class="timestamp" contenteditable="false" data-timestamp="1.000">0:01</span>\xa0Hello\ud800World New Line\tTab</p>'

