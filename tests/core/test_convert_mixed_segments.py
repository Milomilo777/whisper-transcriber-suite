"""Supported JSON readers discard junk segments before TSV/ELAN export."""
import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from core import convert


@pytest.mark.parametrize("target", ["tsv", "elan"])
@pytest.mark.parametrize("wrapped", [False, True], ids=["segment-list", "verbose-json"])
def test_convert_file_keeps_valid_segments_among_nondict_entries(tmp_path, target, wrapped):
    expected = [
        {"start": 0.125, "end": 1.25, "text": "First valid cue"},
        {"start": 2.5, "end": 4.75, "text": "Last valid cue"},
    ]
    mixed = [None, expected[0], "junk segment", 42, expected[1], None]
    payload = {"text": "ignored wrapper text", "segments": mixed} if wrapped else mixed
    source = tmp_path / "mixed.json"
    original = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    source.write_bytes(original)

    output = Path(convert.convert_file(str(source), target))

    assert output != source
    assert source.read_bytes() == original
    actual = convert.parse_to_segments(str(output))
    assert [{key: segment[key] for key in ("start", "end", "text")} for segment in actual] == expected
    # Verify the actual output has exactly the valid cues, including the cue
    # after junk, rather than merely accepting a readable partial export.
    if target == "tsv":
        assert output.read_text(encoding="utf-8").splitlines() == [
            "start\tend\ttext", "125\t1250\tFirst valid cue", "2500\t4750\tLast valid cue",
        ]
    else:
        root = ET.parse(output).getroot()
        assert [node.text for node in root.iter("ANNOTATION_VALUE")] == [cue["text"] for cue in expected]
        assert len(list(root.iter("ALIGNABLE_ANNOTATION"))) == 2
