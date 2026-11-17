"""Word timestamps in a capped enclosing segment keep decoded tail text."""
from copy import deepcopy
import json
from pathlib import Path
import re

import pytest

from core import transcriber as tr
from tests.core.test_transcription_endpoint_bounds import (
    Segment, Word, endpoint_case, install_model, output_task,
)


def test_transcribe_bounds_word_inside_capped_segment_tail_and_saves_outputs(
    endpoint_case, monkeypatch,
):
    case = endpoint_case
    # The media end is verified from the real PCM WAV, not the returned times.
    install_model(monkeypatch, [Segment(2.14, 3.12, words=[
        Word(2.14, 2.3, 'last'), Word(case.duration + 0.02, 3.12, ' words'),
    ])])
    task = output_task(case)
    task.output_formats = ['srt', 'vtt', 'ass', 'json', 'txt']
    tr.transcribe(task)
    assert len(task.output_paths) == 5
    for path in task.output_paths:
        assert 'last words' not in Path(path).read_text(encoding='utf-8')
        assert 'last' in Path(path).read_text(encoding='utf-8')
    path = next(Path(p) for p in task.output_paths if p.endswith('.json'))
    saved = json.loads(path.read_text(encoding='utf-8'))
    assert saved[0]['end'] == case.duration
    # The decoder conversion strips token padding; writers preserve these labels.
    assert [word['word'] for word in saved[0]['words']] == ['last']
    assert saved[0]['words'][-1]['end'] == 2.3
    vtt = next(Path(p) for p in task.output_paths if p.endswith('.vtt')).read_text(encoding='utf-8')
    assert re.findall(r'<c>(.*?)</c>', vtt) == ['last']
    ass = next(Path(p) for p in task.output_paths if p.endswith('.ass')).read_text(encoding='utf-8')
    dialogue = next(line for line in ass.splitlines() if line.startswith('Dialogue:'))
    assert 'last' in dialogue and 'words' not in dialogue


def test_transcribe_lone_word_inside_segment_overshoot_survives(endpoint_case, monkeypatch):
    case = endpoint_case
    install_model(monkeypatch, [Segment(2.14, 3.12, text='last', words=[Word(2.6, 3.12)])])
    task = output_task(case)
    tr.transcribe(task)
    path = next(Path(p) for p in task.output_paths if p.endswith('.json'))
    saved = json.loads(path.read_text(encoding='utf-8'))
    assert saved == []
    records = list(tr._checkpoint.partials_dir().glob("*.timing-recovery.json"))
    assert any(json.loads(p.read_text(encoding="utf-8"))["segments"][0]["text"] == "last" for p in records)
    assert len(task.output_paths) == 3


def test_word_outside_its_raw_segment_is_still_rejected():
    row = {'start': 9.2, 'end': 10.4, 'text': 'bad',
           'words': [{'start': 10.02, 'end': 10.5, 'word': 'bad'}]}
    original = deepcopy(row)
    assert tr._cap_segment(row, 10.0) is None
    assert row == original


def test_capped_segment_tail_is_idempotent_and_does_not_mutate_raw_input():
    row = {'start': 9.2, 'end': 10.4, 'text': 'ok bye', 'words': [
        {'start': 9.2, 'end': 9.6, 'word': 'ok'},
        {'start': 10.02, 'end': 10.4, 'word': ' bye'},
    ]}
    original = deepcopy(row)
    bounded = tr._cap_segment(row, 10.0)
    assert row == original
    assert bounded['words'] == [row['words'][0]]
    assert bounded['text'] == 'ok'
    assert tr._cap_segment(bounded, 10.0) == bounded


def test_completed_checkpoint_with_contained_word_tail_needs_no_redecode(endpoint_case, monkeypatch):
    case = endpoint_case
    task = output_task(case)
    rows = [{'start': 2.14, 'end': 3.12, 'text': 'last words', 'words': [
        {'start': 2.14, 'end': 2.3, 'word': 'last'},
        {'start': case.duration + 0.02, 'end': 3.12, 'word': ' words'},
    ]}]
    tr._write_periodic_checkpoint(task, rows, 3.12, 'en', 0.9, None,
                                  transcription_completed=True)
    monkeypatch.setattr(tr, '_slice_audio_from', lambda *args, **kwargs: pytest.fail('completed decode must not restart'))
    assert tr.resume_transcription(task)
    path = next(Path(p) for p in task.output_paths if p.endswith('.json'))
    saved = json.loads(path.read_text(encoding='utf-8'))
    assert saved[0]['words'] == [dict(rows[0]['words'][0], probability=0.0)]
    assert 'last' == saved[0]['text']
    assert len(task.output_paths) == 3
    records = list(tr._checkpoint.partials_dir().glob('*.timing-recovery.json'))
    assert json.loads(records[-1].read_text(encoding='utf-8'))['segments'] == rows
