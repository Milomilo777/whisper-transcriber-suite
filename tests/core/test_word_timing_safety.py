"""Exercise the real upstream decode loop without loading weights or opening UI."""
from __future__ import annotations

import inspect
import logging
from types import SimpleNamespace

import numpy as np
import pytest
from faster_whisper import WhisperModel

from core.backends import faster_whisper_be as be


def model_for_loop(model_type, monkeypatch, *, collapse=True, windows=1):
    model = object.__new__(model_type)
    model.feature_extractor = SimpleNamespace(time_per_frame=.01, nb_max_frames=100)
    model.frames_per_second = 100
    model.logger = logging.getLogger('word-timing-test')
    monkeypatch.setattr(model, 'encode', lambda features: features)
    monkeypatch.setattr(model, 'get_prompt', lambda *a, **k: [])
    monkeypatch.setattr(model, 'generate_with_fallback', lambda *a: (
        SimpleNamespace(sequences_ids=[[1]], no_speech_prob=0), -.1, 0., 1.))
    def split(**kw):
        start = kw['time_offset']
        return ([dict(start=start, end=start+1., tokens=[1], seek=kw['seek'])],
                kw['seek'] + 100, True)
    monkeypatch.setattr(model, '_split_segments_by_timestamps', split)
    def align(*a, **k):
        return [[dict(word=' Yes.', tokens=[1], start=.3, end=.3 if collapse else .6,
                      probability=.9)]]
    monkeypatch.setattr(model, 'find_alignment', align)
    defaults = inspect.signature(WhisperModel.transcribe).parameters
    options = SimpleNamespace(**{k: v.default for k, v in defaults.items()})
    options.word_timestamps = True
    options.clip_timestamps = [0, windows]
    tokenizer = SimpleNamespace(eot=10, decode=lambda tokens: ' Yes.')
    return model, tokenizer, options


def test_real_generate_segments_keeps_collapsed_text(monkeypatch):
    model, tokenizer, options = model_for_loop(be.WhisperModel, monkeypatch)
    result = list(model.generate_segments(np.zeros((80, 101)), tokenizer, options, False))
    assert [s.text for s in result] == [' Yes.']
    assert (result[0].start, result[0].end) == (0., 1.)
    assert not result[0].words  # no invented word times on the raw-bound fallback


def test_batched_alignment_keeps_raw_bounds(monkeypatch):
    model, tokenizer, _ = model_for_loop(be.WhisperModel, monkeypatch)
    groups = [[dict(start=0., end=1., tokens=[1], seek=0)],
              [dict(start=2., end=3., tokens=[1], seek=200)]]
    monkeypatch.setattr(model, 'find_alignment', lambda *a: [
        [dict(word=' Yes.', tokens=[1], start=.3, end=.3, probability=.9)], []])
    model.add_word_timestamps(groups, tokenizer, None, [100, 100], '', '', 0.)
    assert (groups[0][0]['start'], groups[0][0]['end']) == (0., 1.)
    assert (groups[1][0]['start'], groups[1][0]['end']) == (2., 3.)


def test_alignment_index_error_preserves_translation(monkeypatch, caplog):
    model, tokenizer, options = model_for_loop(be.WhisperModel, monkeypatch)
    options.task = 'translate'
    monkeypatch.setattr(model, 'find_alignment', lambda *a: [])
    result = list(model.generate_segments(np.zeros((80, 101)), tokenizer, options, False))
    assert result[0].text == ' Yes.'
    assert (result[0].start, result[0].end) == (0., 1.)
    assert 'alignment' in caplog.text.lower()


def test_valid_alignment_is_retained(monkeypatch):
    model, tokenizer, options = model_for_loop(be.WhisperModel, monkeypatch, collapse=False)
    result = list(model.generate_segments(np.zeros((80, 101)), tokenizer, options, False))
    assert result[0].words[0].word == ' Yes.'
    assert (result[0].start, result[0].end) == (.3, .6)


def test_non_alignment_error_is_explicit(monkeypatch):
    model, tokenizer, options = model_for_loop(be.WhisperModel, monkeypatch)
    def broken(*a):
        raise RuntimeError('alignment device failed')
    monkeypatch.setattr(model, 'find_alignment', broken)
    with pytest.raises(RuntimeError, match='alignment device failed'):
        list(model.generate_segments(np.zeros((80, 101)), tokenizer, options, False))


def test_empty_inner_alignment_is_already_safe(monkeypatch):
    model, tokenizer, options = model_for_loop(be.WhisperModel, monkeypatch)
    monkeypatch.setattr(model, 'find_alignment', lambda *a: [[]])
    result = list(model.generate_segments(np.zeros((80, 101)), tokenizer, options, False))
    assert result[0].text == ' Yes.' and not result[0].words


def test_real_find_alignment_bad_jump_index_keeps_translation(monkeypatch):
    model, tokenizer, options = model_for_loop(be.WhisperModel, monkeypatch)
    monkeypatch.delattr(model, 'find_alignment')
    model.tokens_per_second = 50
    model.model = SimpleNamespace(align=lambda *a, **k: [SimpleNamespace(
        alignments=[(0, 0)], text_token_probs=[.9])])
    tokenizer.sot_sequence = [9]
    tokenizer.split_to_word_tokens = lambda tokens: (['Yes.', '<eot>'], [[1], [10]])
    options.task = 'translate'
    result = list(model.generate_segments(np.zeros((80, 101)), tokenizer, options, False))
    assert result[0].text == ' Yes.' and not result[0].words


def test_real_batched_forward_uses_alignment_guard(monkeypatch):
    from faster_whisper import BatchedInferencePipeline
    model, tokenizer, options = model_for_loop(be.WhisperModel, monkeypatch)
    pipeline = BatchedInferencePipeline(model)
    monkeypatch.setattr(pipeline, 'generate_segment_batched', lambda *a: (
        None, [dict(tokens=[1], avg_logprob=-.1, no_speech_prob=0.)]))
    groups = pipeline.forward(None, tokenizer, [dict(offset=0., duration=1.)], options)
    assert groups[0][0]['text'] == ' Yes.'
    assert (groups[0][0]['start'], groups[0][0]['end']) == (0., 1.)


def test_alignment_still_changes_seek_schedule(monkeypatch):
    model, tokenizer, options = model_for_loop(be.WhisperModel, monkeypatch, collapse=False, windows=2)
    split = model._split_segments_by_timestamps
    def not_single(**kwargs):
        groups, seek, _ = split(**kwargs)
        return groups, seek, False
    monkeypatch.setattr(model, '_split_segments_by_timestamps', not_single)
    features = np.zeros((80, 201))
    aligned = list(model.generate_segments(features, tokenizer, options, False))
    options.word_timestamps = False
    raw = list(model.generate_segments(features, tokenizer, options, False))
    assert [s.seek for s in raw] == [0, 100]
    assert [s.seek for s in aligned] == [0, 60, 120, 180]


def test_vad_restore_keeps_collapsed_fallback_text(monkeypatch):
    from faster_whisper.transcribe import restore_speech_timestamps
    model, tokenizer, options = model_for_loop(be.WhisperModel, monkeypatch)
    segments = model.generate_segments(np.zeros((80, 101)), tokenizer, options, False)
    result = list(restore_speech_timestamps(segments, [dict(start=0, end=8000),
        dict(start=16000, end=24000)], 16000))
    assert result[0].text == ' Yes.'
    assert result[0].end > result[0].start
