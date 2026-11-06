"""Run the installed faster-whisper 1.2.1 generator with controlled seams."""
import numpy as np
import pytest

from core.backends import faster_whisper_be as be
from tests.core.test_word_timing_safety import model_for_loop


def test_partial_collapse_never_decodes_emitted_audio_twice(monkeypatch):
    model, tokenizer, options = model_for_loop(be.WhisperModel, monkeypatch, windows=2)
    seeks = []
    def split(**kw):
        seeks.append(kw['seek'])
        t = kw['time_offset']
        if t == 0:
            return ([dict(start=0., end=.5, tokens=[1], seek=0),
                     dict(start=.5, end=1., tokens=[2], seek=0)], 100, False)
        return ([dict(start=t, end=t+1, tokens=[3], seek=kw['seek'])], kw['seek']+100, True)
    monkeypatch.setattr(model, '_split_segments_by_timestamps', split)
    tokenizer.decode = lambda tokens: {1: ' first', 2: ' second', 3: ' third'}[tokens[0]]
    def alignment(*args):
        return [[dict(word=' first', tokens=[1], start=.1, end=.4, probability=.9),
                 dict(word=' second', tokens=[2], start=.4, end=.4, probability=.9)]]
    monkeypatch.setattr(model, 'find_alignment', alignment)
    result = list(model.generate_segments(np.zeros((80, 201)), tokenizer, options, False))
    assert seeks == [0, 100]
    assert [s.text for s in result] == [' first', ' second', ' third']
    assert result[0].end <= result[1].start
    assert not result[1].words


def test_mixed_collapse_restores_consistent_group(monkeypatch):
    model, tokenizer, _ = model_for_loop(be.WhisperModel, monkeypatch)
    group = [dict(start=0., end=2., tokens=[1], seek=0),
             dict(start=2., end=4., tokens=[2], seek=0)]
    monkeypatch.setattr(model, 'find_alignment', lambda *args: [[
        dict(word='first', tokens=[1], start=3., end=3.5, probability=.9),
        dict(word='second', tokens=[2], start=3.5, end=3.5, probability=.9)]])
    model.add_word_timestamps([group], tokenizer, None, 400, '', '', 0.)
    assert group[0]['end'] <= group[1]['start']
    assert all(s['end'] > s['start'] for s in group)
    assert all(not s['words'] for s in group)


def test_zero_raw_cue_is_merged_without_losing_tokens(monkeypatch):
    model, tokenizer, options = model_for_loop(be.WhisperModel, monkeypatch)
    monkeypatch.setattr(model, '_split_segments_by_timestamps', lambda **kw: ([
        dict(start=0., end=0., tokens=[1], seek=0),
        dict(start=0., end=1., tokens=[2], seek=0)], 100, True))
    tokenizer.decode = lambda tokens: ''.join({1: ' first', 2: ' second'}[i] for i in tokens)
    monkeypatch.setattr(model, 'find_alignment', lambda *args: [[
        dict(word='first', tokens=[1], start=.3, end=.3, probability=.9),
        dict(word='second', tokens=[2], start=.3, end=.3, probability=.9)]])
    result = list(model.generate_segments(np.zeros((80, 101)), tokenizer, options, False))
    assert ''.join(s.text for s in result) == ' first second'
    assert all(s.end > s.start for s in result)
    assert all(not s.words for s in result)


def test_no_positive_raw_bounds_raises_instead_of_discarding_text(monkeypatch):
    model, tokenizer, options = model_for_loop(be.WhisperModel, monkeypatch)
    monkeypatch.setattr(model, '_split_segments_by_timestamps', lambda **kw:
        ([dict(start=0., end=0., tokens=[1], seek=0)], 100, True))
    with pytest.raises(RuntimeError, match='segment bounds'):
        list(model.generate_segments(np.zeros((80, 101)), tokenizer, options, False))


def test_batched_zero_raw_merge_preserves_predecoded_text(monkeypatch):
    from faster_whisper import BatchedInferencePipeline
    model, tokenizer, options = model_for_loop(be.WhisperModel, monkeypatch)
    monkeypatch.setattr(model, '_split_segments_by_timestamps', lambda **kw: ([
        dict(start=0., end=0., tokens=[1], seek=0),
        dict(start=0., end=1., tokens=[2], seek=0)], 100, True))
    tokenizer.decode = lambda tokens: ''.join({1: ' first', 2: ' second'}[i] for i in tokens)
    monkeypatch.setattr(model, 'find_alignment', lambda *args: [[
        dict(word='first', tokens=[1], start=.3, end=.3, probability=.9),
        dict(word='second', tokens=[2], start=.3, end=.3, probability=.9)]])
    pipeline = BatchedInferencePipeline(model)
    monkeypatch.setattr(pipeline, 'generate_segment_batched', lambda *args: (
        None, [dict(tokens=[1, 2], avg_logprob=-.1, no_speech_prob=0.)]))
    groups = pipeline.forward(None, tokenizer, [dict(offset=0., duration=1.)], options)
    assert ''.join(s['text'] for s in groups[0]) == ' first second'
    assert all(s['end'] > s['start'] and not s['words'] for s in groups[0])
