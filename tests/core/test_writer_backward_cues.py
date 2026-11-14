"""Conversion must preserve clocks when zero-length cues precede earlier cues."""
from __future__ import annotations

import json
import pytest

from core.convert import convert_file, parse_to_segments
from core.writers import bilingual_srt


@pytest.mark.parametrize('fmt', ['srt', 'vtt'])
@pytest.mark.parametrize('earlier', [10.0, 3599.999])
def test_conversion_does_not_merge_a_later_zero_cue_backwards(tmp_path, fmt, earlier):
    source = tmp_path / 'transcript.json'
    segments = [
        {'start': 3600.0, 'end': 3600.0, 'text': 'late'},
        {'start': earlier, 'end': earlier + 2, 'text': 'early'},
    ]
    original = json.dumps(segments).encode('utf-8')
    source.write_bytes(original)

    output = convert_file(str(source), fmt)

    assert parse_to_segments(output) == [
        {'start': 3600.0, 'end': 3601.0, 'text': 'late'},
        {'start': earlier, 'end': earlier + 2, 'text': 'early'},
    ]
    assert source.read_bytes() == original


@pytest.mark.parametrize('fmt', ['srt', 'vtt'])
def test_forward_merge_chain_stops_before_an_earlier_cue(tmp_path, fmt):
    source = tmp_path / 'transcript.json'
    source.write_text(json.dumps([
        {'start': 3600.0, 'end': 3600.0, 'text': 'late'},
        {'start': 3600.05, 'end': 3600.05, 'text': 'nearby'},
        {'start': 10.0, 'end': 12.0, 'text': 'early'},
    ]), encoding='utf-8')

    output = convert_file(str(source), fmt)

    assert parse_to_segments(output) == [
        {'start': 3600.0, 'end': 3601.0, 'text': 'late nearby'},
        {'start': 10.0, 'end': 12.0, 'text': 'early'},
    ]


@pytest.mark.parametrize('fmt', ['srt', 'vtt'])
@pytest.mark.parametrize('next_start,expected', [
    (2.099, [(2.0, 3.0, 'first second')]),
    (2.1, [(2.0, 2.1, 'first'), (2.1, 3.0, 'second')]),
])
def test_forward_repair_keeps_the_hundred_millisecond_boundary(tmp_path, fmt, next_start, expected):
    source = tmp_path / 'transcript.json'
    source.write_text(json.dumps([
        {'start': 2.0, 'end': 2.0, 'text': 'first'},
        {'start': next_start, 'end': 3.0, 'text': 'second'},
    ]), encoding='utf-8')

    output = convert_file(str(source), fmt)

    assert [(s['start'], s['end'], s['text']) for s in parse_to_segments(output)] == expected


def test_bilingual_backward_zero_cue_keeps_language_rows_and_clocks():
    segments = [
        {'start': 3600.0, 'end': 3600.0, 'text': 'late original'},
        {'start': 10.0, 'end': 12.0, 'text': 'early original'},
    ]
    translations = ['late translation', 'early translation']
    original = json.dumps([segments, translations])

    assert bilingual_srt.write(segments, translations) == (
        '1\n01:00:00,000 --> 01:00:01,000\n'
        'late original\nlate translation\n\n'
        '2\n00:00:10,000 --> 00:00:12,000\n'
        'early original\nearly translation\n'
    )
    assert json.dumps([segments, translations]) == original
