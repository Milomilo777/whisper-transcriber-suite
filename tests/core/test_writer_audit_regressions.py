"""Causal regressions and supported-input counterexamples for the writer audit."""
import json
import re

import pytest

from core import convert
from core.writers import bilingual_srt, json_writer, md, srt, vtt
from core.writers.base import prepare_cues


@pytest.mark.parametrize('end', [None, -1, 1, 1.0001], ids=['none','earlier','equal','rounding'])
def test_bilingual_cue_has_positive_written_duration(end):
    body = bilingual_srt.write([{'start':1,'end':end,'text':'Original'}], ['Translation'])
    start, end = re.search(r'(\d+:\d+:\d+,\d+) --> (\d+:\d+:\d+,\d+)', body).groups()
    assert start < end
    assert 'Original' in body and 'Translation' in body


@pytest.mark.parametrize('writer', [srt, vtt, md], ids=['srt','vtt','md'])
def test_speaker_control_characters_do_not_corrupt_export(writer):
    body = writer.write([{'start':0,'end':1,'speaker':'Speaker\x001','text':'Hello'}])
    assert '\x00' not in body
    assert 'Speaker1' in body and 'Hello' in body


def test_out_of_order_invalid_cues_do_not_inherit_an_unusable_end():
    cues = prepare_cues([
        {'start':5.,'end':5.,'text':'First'},
        {'start':.5,'end':.5,'text':'Second'},
        {'start':.7,'end':1.2,'text':'Third'}], lambda seg:seg['text'])
    # Keep the later point at its own time instead of merging it backwards.
    assert cues == [(5000,6000,'First'),(500,700,'Second'),(700,1200,'Third')]


def test_json_keeps_word_clocks_when_segment_end_is_missing():
    body = json.loads(json_writer.write([{'start':10,'text':'hello world','words':[
        {'word':'hello','start':10,'end':10.5}, {'word':'world','start':10.5,'end':11}]}]))
    assert body[0]['end'] == 11
    assert body[0]['words'][1]['start'] == 10.5
    assert body[0]['words'][1]['end'] == 11


def test_json_missing_word_end_does_not_swallow_the_rest_of_the_segment():
    body = json.loads(json_writer.write([{'start':10,'end':20,'text':'hello world','words':[
        {'word':'hello','start':10}, {'word':'world','start':15,'end':16}]}]))
    assert body[0]['words'][0]['end'] == 10


@pytest.mark.parametrize('format', ['srt','json','docx','pdf','md','tsv'])
def test_public_json_conversion_filters_non_segment_entries(tmp_path, format):
    path = tmp_path / 'input.json'
    path.write_text(json.dumps([None,7,'invalid',{'start':0,'end':1,'text':'Retained words'}]), encoding='utf-8')
    segments=convert.parse_to_segments(str(path))
    assert len(segments)==1 and segments[0]['text']=='Retained words'
    # Binary document writers are called after parsing; they deliberately do
    # not join the converter's text-writer registry.
    if format=='docx':
        from core.writers import docx_writer
        assert docx_writer.write_bytes(segments).startswith(b'PK')
    elif format=='pdf':
        from core.writers import pdf_writer
        assert pdf_writer.write_bytes(segments).startswith(b'%PDF')
    else:
        output = convert.convert_file(str(path),format)
        assert __import__('pathlib').Path(output).stat().st_size


def test_bilingual_merge_retains_distinct_translations():
    body = bilingual_srt.write([{'start':0,'end':0,'text':'Original'},
                                {'start':0,'end':1,'text':'Original'}], ['First','Second'])
    assert 'First' in body and 'Second' in body


def test_extreme_inferred_word_time_still_converts_to_subtitles(tmp_path):
    path=tmp_path/'extreme.json'
    path.write_text(json_writer.write([{'start':2,'text':'retained word','words':[
        {'start':2,'end':1e308,'word':'retained word'}]}]),encoding='utf-8')
    output=convert.convert_file(str(path),'srt')
    body=__import__('pathlib').Path(output).read_text(encoding='utf-8')
    assert 'retained word' in body
    assert convert.parse_to_segments(output)[0]['end'] > 2
