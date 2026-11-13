"""Exercise real decode callers without model weights, GPU allocation or UI."""
import inspect
import logging
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from core.backends import faster_whisper_be as be


def check_positive_unaligned_tail(mode='mixed'):
    # Same weight-free setup as tests/core/test_word_timing_safety.py.
    model = object.__new__(be.WhisperModel)
    model.feature_extractor = SimpleNamespace(time_per_frame=.01, nb_max_frames=100)
    model.frames_per_second = 100
    model.logger = logging.getLogger('word-timing-test')
    model.encode = lambda features: features
    model.get_prompt = lambda *a, **k: []
    model.generate_with_fallback = lambda *a: (
        SimpleNamespace(sequences_ids=[[1]], no_speech_prob=0), -.1, 0., 1.)
    defaults = inspect.signature(be._WhisperModel.transcribe).parameters
    options = SimpleNamespace(**{k: v.default for k, v in defaults.items()})
    options.word_timestamps = True
    options.clip_timestamps = [0, 2]
    tokenizer = SimpleNamespace(eot=10)
    seeks = []
    tokenizer.decode = lambda tokens: ''.join({1: ' first', 2: ' tail', 3: ' next', 8: '  ', 12: ''}[t] for t in tokens)

    def split(**kw):
        start = kw['time_offset']
        seeks.append(kw['seek'])
        if start == 0:
            rows = [dict(start=0., end=.4, tokens=[1], seek=0),
                    dict(start=.6, end=.9, tokens=[2], seek=0)]
            if mode == 'middle':
                rows = [dict(start=0., end=.2, tokens=[1], seek=0),
                        dict(start=.3, end=.4, tokens=[2], seek=0),
                        dict(start=.6, end=.9, tokens=[3], seek=0)]
            if mode.startswith('blank-'):
                rows[-1]['tokens'] = {'blank-empty': [], 'blank-space': [8], 'blank-special': [12]}[mode]
            if mode == 'mixed-blank-suffix':
                rows.append(dict(start=1., end=1.1, tokens=[8], seek=0))
        else:
            rows = [dict(start=start, end=min(start + 1., 2.), tokens=[3], seek=kw['seek'])]
        return rows, kw['seek'] + 100, False

    def partial_alignment(self, groups, *args, **kwargs):
        for group in groups:
            for index, row in enumerate(group):
                missing = (mode == 'empty' or (len(group) > 1 and
                           ((mode in ('mixed', 'middle') and index == 1)
                            or (mode == 'mixed-blank-suffix' and index >= 1)
                            or (mode.startswith('blank-') and index == 1)
                            or (mode == 'head' and index == 0))))
                row['words'] = ([] if missing else
                                [dict(start=row['start'], end=row['end'], word=' aligned', probability=.9)])
        return 0.

    model._split_segments_by_timestamps = split
    with patch.object(be._WhisperModel, 'add_word_timestamps', partial_alignment):
        result = list(model.generate_segments(np.zeros((80, 201)), tokenizer, options, False))
    if mode.startswith('blank-'):
        assert seeks[1] == 40, f'Blank tail must not advance seek beyond emitted speech: {seeks[1]}'
        assert result[0].words and result[0].text.strip() == 'first'
        assert result[1].text.strip() == 'next'
        return
    assert seeks[1] == 90, f'Already emitted through .9 s, but next seek is {seeks[1] / 100} s'
    assert [s.start for s in result] == sorted(s.start for s in result)
    assert result[0].text.strip() == 'first' and result[1].text.strip() == 'tail'
    counts = [len(s.words or []) for s in result[:3 if mode == 'middle' else 2]]
    if mode in ('mixed', 'mixed-blank-suffix'):
        assert counts == [0, 0], 'Partial-tail fallback must not retain earlier word-based seek'
    elif mode == 'complete':
        assert counts == [1, 1], 'Keep complete alignment unchanged'
    elif mode == 'head':
        assert counts == [0, 1], 'A missing head must not discard usable trailing alignment'
    elif mode == 'middle':
        assert counts == [1, 0, 1], 'A missing middle must not discard usable trailing alignment'


class Regression(unittest.TestCase):
    def test_positive_unaligned_tail_cannot_rewind_emitted_audio(self):
        check_positive_unaligned_tail()

    def test_complete_alignment_control(self):
        check_positive_unaligned_tail('complete')

    def test_all_unaligned_control(self):
        check_positive_unaligned_tail('empty')

    def test_missing_head_keeps_usable_tail(self):
        check_positive_unaligned_tail('head')

    def test_missing_middle_keeps_usable_tail(self):
        check_positive_unaligned_tail('middle')

    def test_empty_token_tail_keeps_alignment_and_seek(self):
        check_positive_unaligned_tail('blank-empty')

    def test_whitespace_tail_keeps_alignment_and_seek(self):
        check_positive_unaligned_tail('blank-space')

    def test_special_token_tail_keeps_alignment_and_seek(self):
        check_positive_unaligned_tail('blank-special')

    def test_blank_suffix_after_real_unaligned_tail_does_not_advance_seek(self):
        check_positive_unaligned_tail('mixed-blank-suffix')

    def test_real_batched_caller_is_unchanged_by_sequential_fix(self):
        model = object.__new__(be.WhisperModel)
        model.frames_per_second = 100
        model._split_segments_by_timestamps = lambda **kw: (
            [dict(start=0., end=.4, tokens=[1]), dict(start=.6, end=.9, tokens=[2])], 0, False)
        tokenizer = SimpleNamespace(decode=lambda tokens: ''.join({1: ' first', 2: ' tail'}[t] for t in tokens))
        pipeline = be.BatchedInferencePipeline(model)
        pipeline.generate_segment_batched = lambda *args: (
            None, [dict(tokens=[1, 2], avg_logprob=-.1, no_speech_prob=0.)])
        options = SimpleNamespace(word_timestamps=True, prepend_punctuations='', append_punctuations='')

        def align(self, groups, *args):
            groups[0][0]['words'] = [dict(start=0., end=.4, word=' first', probability=.9)]
            groups[0][1]['words'] = []
            return .4

        with patch.object(be._WhisperModel, 'add_word_timestamps', align):
            rows = pipeline.forward(None, tokenizer, [dict(offset=0., duration=1.)], options)[0]
        self.assertEqual([len(s['words']) for s in rows], [1, 0])
        self.assertEqual([s['text'] for s in rows], [' first', ' tail'])
        self.assertEqual(pipeline.last_speech_timestamp, .4)


if __name__ == '__main__':
    unittest.main()
