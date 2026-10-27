"""The JSON writer must write every free-text field as a string.

``text``, ``speaker`` and ``suspect_reason`` are str-coerced (a
hand-edited JSON can carry a number or null in any of them);
``words[].word`` was left raw, so a numeric label came out as the JSON
number ``5`` and a null one as ``null`` — a schema the downstream
karaoke tools (the reason the words are preserved at all) do not
expect.
"""
import json

from core.writers import json_writer


def test_json_writer_coerces_word_to_str():
    segs = [{"start": 0.0, "end": 1.0, "text": "hi",
             "words": [{"start": 0.0, "end": 0.5, "word": 5},
                       {"start": 0.5, "end": 1.0, "word": None}]}]
    parsed = json.loads(json_writer.write(segs))
    assert parsed[0]["words"][0]["word"] == "5"
    assert parsed[0]["words"][1]["word"] == ""
