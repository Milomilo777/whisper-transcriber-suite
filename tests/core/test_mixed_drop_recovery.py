"""Count-only field regression and window-level language auditing (no model)."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import collapse_rescue as cr
from core import transcriber as t
from core.task import TranscriptionTask
from core.writers import json_writer


BAD_STARTS = [233.4, 277.8, 297.1, 312.2, 349.5, 1874.3, 2098.1, 2793.3, 2823.0]


def test_saved_window_counts_detect_partial_drops():
    rows = json.loads((Path(__file__).parents[1] / 'fixtures/mixed_window_counts.json').read_text())
    segments = [dict(start=r['start'], end=r['end'],
                     text='中' * r['cjk'] + ' word' * (r['units'] - r['cjk'])) for r in rows]
    flagged = [s.start for s in cr.find_suspect_spans(segments, rows[-1]['end']) if s.kind == 'collapsed']
    hits = sum(any(abs(start - bad) < .15 for start in flagged) for bad in BAD_STARTS)
    false_positives = sum(not any(abs(start - bad) < .15 for bad in BAD_STARTS) for start in flagged)
    assert hits >= 7, (hits, flagged)
    assert false_positives <= int((len(rows) - 9) * .05), false_positives


def test_mixed_short_windows_leave_single_language_unchanged():
    task = TranscriptionTask('a.wav')
    assert 'chunk_length' not in t._build_transcribe_kwargs(task)
    task.languages = ('zh', 'en')
    assert t._build_transcribe_kwargs(task)['chunk_length'] == 15


def test_decoded_language_survives_shift_and_json():
    segment = SimpleNamespace(start=1., end=3., text='hello', words=[])
    tagged = t._DecodedLanguageSegment(segment, 'en')
    shifted = list(t._shift_segments([tagged], 20.))[0]
    payload = t._segment_to_dict(shifted, False)
    assert json.loads(json_writer.write([payload])) == [dict(start=21., end=23., text='hello', language='en')]
    assert 'language' not in t._segment_to_dict(segment, False)


@pytest.mark.parametrize('cjk', [False, True])
def test_relative_rate_does_not_compare_scripts(cjk):
    text = ('中' * 100) if cjk else ('word ' * 50)
    normal = [dict(start=i * 25., end=(i+1) * 25., text=text) for i in range(12)]
    normal.append(dict(start=300., end=325., text=('word ' * 30) if cjk else ('中' * 60)))
    assert cr.find_suspect_spans(normal, 325.) == []

class Detector:
    is_multilingual = True

    def detect_language(self, features):
        return [[(f'<|{code}|>', .97), ('<|zh|>', .03)] for code in features]

    def generate(self, features, *args, **kwargs):
        return features


class Sequential:
    def __init__(self):
        self.model = Detector()
        self.feature_extractor = SimpleNamespace(nb_max_frames=3000)

    def transcribe(self, audio, **kwargs):
        self.feature_extractor.nb_max_frames = kwargs.get('chunk_length', 30) * 100

        def segments():
            for index, language in enumerate(audio):
                features = [language]
                if kwargs.get('multilingual'):
                    self.model.detect_language(features)
                self.model.generate(features)
                yield SimpleNamespace(start=index*15., end=(index+1)*15., text='word ' * 50,
                                      words=[], seek=index*1500)
        return segments(), SimpleNamespace(language='zh')


class Pipeline:
    def __init__(self):
        self.model = Sequential()

    def forward(self, features, tokenizer, metadata, options):
        if options.get('multilingual'):
            self.model.model.detect_language(features)
        self.model.model.generate(features)
        return [[] if language == 'silent' else [dict(start=i*15., end=(i+1)*15.,
                                                     text='hello', words=[], seek=i*1500)]
                for i, language in enumerate(features)]

    def transcribe(self, audio, **kwargs):
        def segments():
            for group in self.forward(audio, None, None, kwargs):
                for segment in group:
                    yield SimpleNamespace(**segment)
        return segments(), SimpleNamespace(language='zh')


@pytest.mark.parametrize('batched', [False, True])
def test_language_labels_follow_actual_decisions_and_empty_chunks(batched):
    shared = Pipeline() if batched else Sequential()
    audio = ['zh', 'silent', 'en'] if batched else ['zh', 'en']
    runner = t._two_language_runner(shared, ('zh', 'en'))
    segments, _ = runner.transcribe(audio, multilingual=True, chunk_length=15)
    output = list(segments)
    assert [s.decoded_language for s in output] == ['zh', 'en']
    assert isinstance((shared.model.model if batched else shared.model), Detector)
    assert (shared.model if batched else shared).feature_extractor.nb_max_frames == 3000


@pytest.mark.parametrize('batched', [False, True])
def test_forced_language_warns_without_changing_text_or_prompts(batched, caplog):
    logs = []
    shared = Pipeline() if batched else Sequential()
    runner = t._language_audited_runner(shared, forced='zh', log_cb=logs.append)
    segments, _ = runner.transcribe(['zh', 'en'], language='zh')
    output = list(segments)
    assert len(output) == 2
    assert not any(hasattr(s, 'decoded_language') for s in output)
    assert len(logs) == 1 and '15.00-30.00s' in logs[0] and 'en (97%)' in logs[0]
    assert len([r for r in caplog.records if r.levelname == 'WARNING']) == 1


def test_forced_audit_failure_preserves_decoding():
    class NoDetection(Detector):
        def detect_language(self, features):
            raise RuntimeError('unsupported detection')
    shared = Sequential()
    shared.model = NoDetection()
    runner = t._language_audited_runner(shared, forced='zh')
    segments, _ = runner.transcribe(['en'], language='zh')
    assert len(list(segments)) == 1


@pytest.mark.parametrize('model_kind', ['absent', 'opaque', 'detection_only'])
def test_forced_audit_preserves_runners_without_decode_hooks(model_kind):
    class Runner:
        def __init__(self):
            self.calls = 0
            if model_kind == 'opaque':
                self.model = object()
            elif model_kind == 'detection_only':
                self.model = SimpleNamespace(detect_language=lambda features: [])

        def __copy__(self):
            raise AssertionError('Unsupported audit runners must stay untouched')

        def transcribe(self, audio, **kwargs):
            self.calls += 1
            assert audio == 'audio' and kwargs == {'language': 'zh'}
            return iter(['saved text']), SimpleNamespace(language='zh')

    shared = Runner()
    runner = t._language_audited_runner(shared, forced='zh')
    assert runner is shared
    segments, info = runner.transcribe('audio', language='zh')
    assert list(segments) == ['saved text'] and info.language == 'zh'
    assert shared.calls == 1


def test_partial_window_reaches_nonbatched_rescue_with_piece_languages(monkeypatch):
    import sys
    from types import ModuleType
    import numpy as np
    from core.backends import nvidia_asr

    vad = ModuleType('faster_whisper.vad')
    vad.VadOptions = lambda **kwargs: SimpleNamespace(**kwargs)
    vad.get_speech_timestamps = lambda audio, options: [dict(start=0, end=len(audio))]
    monkeypatch.setitem(sys.modules, 'faster_whisper.vad', vad)
    monkeypatch.setattr(t, 'MODEL', Sequential())
    monkeypatch.setattr(t, 'PIPELINE', None)
    monkeypatch.setattr(t, '_LM_RUNNER', SimpleNamespace(slot=None))
    monkeypatch.setattr(nvidia_asr, '_decode_window', lambda path, start, end: np.zeros(int((end-start)*16000)))
    calls = []
    actual_runner = t._whisper_runner

    def runner(task, **options):
        assert not options.get('batched')
        real = actual_runner(task, **options)

        def decode(audio, **kwargs):
            calls.append(kwargs)
            return real.transcribe(['en' if len(calls) % 2 else 'zh'], **kwargs)
        return SimpleNamespace(transcribe=decode)

    monkeypatch.setattr(t, '_whisper_runner', runner)
    task = TranscriptionTask('a.wav')
    task.languages = ('zh', 'en')
    original = [dict(start=i*30., end=(i+1)*30., text='中' * (12 if i == 2 else 120)) for i in range(6)]
    output = t._rescue_collapsed(task, original, 'a.wav', t._build_transcribe_kwargs(task), False,
                                  'zh', 180., None)
    assert len(calls) == 2
    assert all(c['multilingual'] and 'language' not in c and c['chunk_length'] == 15 for c in calls)
    assert [s['language'] for s in output if 60 <= s['start'] < 90] == ['en', 'zh']
    assert output[0] is original[0] and original[2]['text'] == '中' * 12

@pytest.mark.parametrize('source_offset', [0., 3600., 7200.])
def test_forced_warning_uses_job_source_offset(monkeypatch, source_offset):
    monkeypatch.setattr(t, 'MODEL', Sequential())
    monkeypatch.setattr(t, 'PIPELINE', None)
    monkeypatch.setattr(t, '_LM_RUNNER', SimpleNamespace(slot=None))
    monkeypatch.setattr(t, 'device', 'cpu')
    task = TranscriptionTask('a.wav')
    task.language = 'zh'
    task.clip_start = source_offset
    logs = []
    runner = t._whisper_runner(task, log_cb=logs.append)
    segments, _ = runner.transcribe(['en'], language='zh')
    list(segments)
    assert len(logs) == 1
    assert f'{source_offset:.2f}-{source_offset+15:.2f}s' in logs[0]
    # Resume and rescue set the origin to their own source-audio cut point.
    runner.language_offset = source_offset + 60
    segments, _ = runner.transcribe(['en'], language='zh')
    list(segments)
    assert f'{source_offset+60:.2f}-{source_offset+75:.2f}s' in logs[-1]


def test_forced_warning_uses_cuda_retry_cursor(monkeypatch):
    from core.backends.faster_whisper_be import WhisperDecode
    calls = []
    logs = []

    class Failing(Sequential):
        def transcribe(self, audio, **kwargs):
            calls.append(audio)
            good, info = super().transcribe(['zh'] if len(calls) == 1 else ['en'], **kwargs)

            def result():
                yield from good
                if len(calls) == 1:
                    raise RuntimeError('CUDA out of memory')
            return result(), info

    shared = Failing()
    decoder = WhisperDecode(
        lambda options: t._language_audited_runner(shared, forced='zh', log_cb=logs.append,
                                                    time_offset=3600+decoder.audio_offset),
        lambda: True, lambda options, oom: None, 0,
    )
    monkeypatch.setattr(t, '_slice_audio_from', lambda *a: 'tail.wav')
    segments, _ = decoder.transcribe('audio.wav', language='zh')
    assert [(s.start, s.end) for s in segments] == [(0., 15.), (15., 30.)]
    assert len(logs) == 1 and '3615.00-3630.00s' in logs[0]
