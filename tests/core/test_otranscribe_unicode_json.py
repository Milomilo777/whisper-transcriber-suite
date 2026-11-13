"""Unicode JSON files use the same encoding support in OTR and conversion."""
from __future__ import annotations

import codecs
import json

import pytest

from core import convert
from core.integrations import otranscribe as otr


ENCODINGS = [
    ("utf-8", b""), ("utf-8-sig", b""),
    ("utf-16", b""), ("utf-16-le", b""), ("utf-16-be", b""),
    ("utf-16-be", codecs.BOM_UTF16_BE),
    ("utf-32", b""), ("utf-32-le", b""), ("utf-32-be", b""),
    ("utf-32-be", codecs.BOM_UTF32_BE),
]
TEXT = "Unicode transcript: سلام 世界 😀"
SEGMENTS = [{"start": 1.0, "end": 3.0, "text": TEXT}]


@pytest.mark.parametrize("encoding,bom", ENCODINGS)
def test_unicode_otr_import_keeps_text_and_existing_files(tmp_path, encoding, bom):
    source = tmp_path / "captions.otr"
    original = bom + otr.segments_to_otr(SEGMENTS, "clip.wav").encode(encoding)
    source.write_bytes(original)
    previous = source.with_suffix(".json")
    previous.write_bytes(b"previous edited transcript")
    assert TEXT in otr.otr_to_srt(str(source))
    output = convert.convert_file(str(source), "json")
    assert [segment["text"] for segment in convert.parse_to_segments(output)] == [TEXT]
    assert source.read_bytes() == original
    assert previous.read_bytes() == b"previous edited transcript"


@pytest.mark.parametrize("encoding,bom", ENCODINGS)
def test_unicode_whisper_json_exports_as_utf8_otr(tmp_path, encoding, bom):
    source = tmp_path / "whisper.json"
    original = bom + json.dumps(SEGMENTS, ensure_ascii=False).encode(encoding)
    source.write_bytes(original)
    exported = otr.whisper_json_to_otr(str(source), "clip.wav")
    target = tmp_path / "export.otr"
    target.write_bytes(exported.encode("utf-8"))
    assert [segment["text"] for segment in convert.parse_to_segments(str(target))] == [TEXT]
    assert json.loads(exported)["media"] == "clip.wav"
    assert source.read_bytes() == original


@pytest.mark.parametrize("payload", [b"\xff\xff", b'{"text":'])
@pytest.mark.parametrize("reader", ["otr", "whisper"])
def test_invalid_json_still_fails_without_changing_source(tmp_path, payload, reader):
    source = tmp_path / "broken.otr"
    source.write_bytes(payload)
    read = otr.otr_to_srt if reader == "otr" else otr.whisper_json_to_otr
    with pytest.raises(ValueError):
        read(str(source))
    assert source.read_bytes() == payload
    if reader == "otr":
        previous = source.with_suffix(".json")
        previous.write_bytes(b"previous completed result")
        with pytest.raises(convert.ConvertError):
            convert.convert_file(str(source), "json", out_path=str(previous))
        assert previous.read_bytes() == b"previous completed result"
