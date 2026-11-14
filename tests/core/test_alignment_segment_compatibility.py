"""Refinement cue compatibility through transcription and persisted writers."""
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace as NS

import pytest

from core import transcriber as tr
from tests.core.test_transcription_endpoint_bounds import (
    Segment, Word, endpoint_case, install_model, output_task,
)

_REAL_POST_PIPELINE = tr._run_post_pipeline


@pytest.mark.parametrize('returned', ['swapped', 'repeated', 'disjoint-in-order'])
def test_transcribe_rejects_refined_words_from_another_identical_cue(
    endpoint_case, monkeypatch, returned,
):
    from core import alignment

    case = endpoint_case
    original = [
        Segment(0.0, 0.8, 'yes', [Word(0.1, 0.7, 'yes')]),
        Segment(1.6, 2.4, 'yes', [Word(1.7, 2.3, 'yes')]),
    ]
    install_model(monkeypatch, original)
    refined = [NS(words=[NS(word='yes', start=0.2, end=0.6, probability=1.0)]),
               NS(words=[NS(word='yes', start=1.8, end=2.2, probability=1.0)])]
    if returned == 'swapped':
        refined.reverse()
    elif returned == 'repeated':
        refined[1] = refined[0]
    else:
        refined[0].words[0].start, refined[0].words[0].end = 1.0, 1.1
    stable = ModuleType('stable_whisper')
    stable.WhisperResult = lambda payload: NS(language='en')
    stable.load_model = lambda _: NS(align=lambda *args, **kwargs: NS(segments=refined))
    monkeypatch.setitem(sys.modules, 'stable_whisper', stable)
    monkeypatch.setattr(alignment, 'is_available', lambda: True)
    monkeypatch.setattr(tr, '_run_post_pipeline', _REAL_POST_PIPELINE)
    monkeypatch.setitem(tr.config, 'alignment', 'stable_ts')
    for name in ('diarization_enabled', 'hallucination_detect_enabled', 'auto_chapters_enabled'):
        monkeypatch.setitem(tr.config, name, False)
    task = output_task(case)
    messages = []
    tr.transcribe(task, log_cb=messages.append)
    path = next(Path(p) for p in task.output_paths if p.endswith('.json'))
    saved = json.loads(path.read_text(encoding='utf-8'))
    assert [row['words'][0]['start'] for row in saved] == [0.1, 1.7]
    assert not any(message.endswith('Word alignment refined.') for message in messages)
    assert any('Keeping original' in message for message in messages)


def test_transcribe_keeps_refinement_overlapping_its_cue(endpoint_case, monkeypatch):
    from core import alignment

    case = endpoint_case
    install_model(monkeypatch, [Segment(1.6, 2.4, 'yes', [Word(1.7, 2.3, 'yes')])])
    stable = ModuleType('stable_whisper')
    stable.WhisperResult = lambda payload: NS(language='en')
    stable.load_model = lambda _: NS(align=lambda *args, **kwargs: NS(segments=[
        NS(words=[NS(word='yes', start=1.55, end=1.85, probability=1.0)]),
    ]))
    monkeypatch.setitem(sys.modules, 'stable_whisper', stable)
    monkeypatch.setattr(alignment, 'is_available', lambda: True)
    monkeypatch.setattr(tr, '_run_post_pipeline', _REAL_POST_PIPELINE)
    monkeypatch.setitem(tr.config, 'alignment', 'stable_ts')
    for name in ('diarization_enabled', 'hallucination_detect_enabled', 'auto_chapters_enabled'):
        monkeypatch.setitem(tr.config, name, False)
    task = output_task(case)
    messages = []
    tr.transcribe(task, log_cb=messages.append)
    path = next(Path(p) for p in task.output_paths if p.endswith('.json'))
    saved = json.loads(path.read_text(encoding='utf-8'))
    assert saved[0]['words'][0]['end'] == 1.85
    assert any(message.endswith('Word alignment refined.') for message in messages)


@pytest.mark.parametrize('bounds', [{}, {'start': float('nan'), 'end': 1.0},
                                   {'start': 0.0, 'end': float('inf')}, {'start': 0.0, 'end': 0.0}])
def test_unknown_source_cue_bounds_do_not_invent_refinement_limits(tmp_path, monkeypatch, bounds):
    from core import alignment

    stable = ModuleType('stable_whisper')
    stable.WhisperResult = lambda payload: NS(language='en')
    stable.load_model = lambda _: NS(align=lambda *args, **kwargs: NS(segments=[
        NS(words=[NS(word='yes', start=5.0, end=5.2, probability=1.0)]),
    ]))
    monkeypatch.setitem(sys.modules, 'stable_whisper', stable)
    monkeypatch.setattr(alignment, 'is_available', lambda: True)
    audio = tmp_path / 'source.wav'; audio.write_bytes(b'fixture; no decoder')
    rows = [dict(bounds, text='yes')]
    assert alignment.refine_word_timestamps_in_place(str(audio), rows) is True
    assert rows[0]['words'][0]['start'] == 5.0


def test_repeated_spelling_with_compatible_word_times_remains_valid(tmp_path, monkeypatch):
    from core import alignment

    stable = ModuleType('stable_whisper')
    stable.WhisperResult = lambda payload: NS(language='en')
    stable.load_model = lambda _: NS(align=lambda *args, **kwargs: NS(segments=[
        NS(words=[NS(word='yes', start=0.2, end=0.6, probability=1.0)]),
        NS(words=[NS(word='yes', start=1.8, end=2.2, probability=1.0)]),
    ]))
    monkeypatch.setitem(sys.modules, 'stable_whisper', stable)
    monkeypatch.setattr(alignment, 'is_available', lambda: True)
    audio = tmp_path / 'source.wav'; audio.write_bytes(b'fixture; no decoder')
    rows = [{'start': 0.0, 'end': 0.8, 'text': 'yes'}, {'start': 1.6, 'end': 2.4, 'text': 'yes'}]
    assert alignment.refine_word_timestamps_in_place(str(audio), rows) is True
    assert [row['words'][0]['start'] for row in rows] == [0.2, 1.8]
