"""Frozen acceptance criteria and hostile-input checks for the timing gate."""
import copy

import pytest

from tools import word_timing_gate as gate


def fixture(*, bad=False):
    rows = [{'type': 'manifest', 'id': 'fixture', 'files': [{'path': 'reader.wav'}],
             'options': {'pairs': 2}}]
    for pair in range(2):
        for setting in ((False, True) if pair % 2 == 0 else (True, False)):
            rows.append({'type': 'run', 'manifest_id': 'fixture', 'file': 'reader.wav',
                         'pair': pair, 'setting': setting, 'kwargs': [{'word_timestamps': setting}],
                         'wall_seconds': 11 if setting else 10,
                         'peak_memory_bytes': (120 if setting else 100) * 2**20,
                         'segments': [{'start': 0, 'end': 5 if setting else 10,
                                       'text': 'one two' if bad and setting else 'one two three',
                                       'words': []}]})
    rows.append({'type': 'end', 'manifest_id': 'fixture', 'complete': True, 'expected_runs': 4})
    return rows


def test_known_good_passes():
    result = gate.score_records(fixture(), {'reader.wav': 'One, TWO three!'})
    assert result['verdict'] == 'PASS'
    assert result['clips']['reader.wav']['accuracy']['on']['deletions'] == 0
    assert result['clips']['reader.wav']['median_time_ratio'] == pytest.approx(1.1)


def test_known_bad_must_fail_and_name_missing_span():
    result = gate.score_records(fixture(bad=True), {'reader.wav': 'one two three'})
    assert result['verdict'] == 'FAIL'
    assert any('deletion' in reason for reason in result['reasons'])
    assert any('three' in span['text'] for span in result['clips']['reader.wav']['spans'])


@pytest.mark.parametrize('field,value,reason', [('wall_seconds', 13, 'time'),
    ('peak_memory_bytes', 400*2**20, 'memory'), ('end', 31, 'cue')])
def test_each_resource_or_cue_failure_fails(field, value, reason):
    rows = fixture()
    for row in rows:
        if row.get('setting') is True:
            (row['segments'][0] if field == 'end' else row)[field] = value
    result = gate.score_records(rows, {'reader.wav': 'one two three'})
    assert result['verdict'] == 'FAIL'
    assert any(reason in r for r in result['reasons'])


def test_missing_reference_and_incomplete_measurement_cannot_pass():
    assert gate.score_records(fixture())['verdict'] == 'FAIL'
    assert gate.score_records(fixture()[:-1], {'reader.wav': 'one two three'})['verdict'] == 'FAIL'


def test_duplicate_pair_cannot_pass():
    rows = fixture()
    rows.insert(2, copy.deepcopy(rows[1]))
    assert gate.score_records(rows, {'reader.wav': 'one two three'})['verdict'] == 'FAIL'


def test_normalisation_and_cer():
    assert gate.normalise('CAFÉ, Ａ!') == ['café', 'a']
    assert gate.normalise('\u4f60\u597d\uff0c\u4e16\u754c') == list('\u4f60\u597d\u4e16\u754c')
    assert gate.edit_counts(list('abcd'), list('axd')) == {
        'substitutions': 1, 'deletions': 1, 'insertions': 0, 'reference': 4}


def test_edit_distance_matches_small_exhaustive_oracle():
    import itertools
    strings = [''.join(x) for n in range(4) for x in itertools.product('ab', repeat=n)]
    for a in strings:
        for b in strings:
            matrix = [[0]*(len(b)+1) for _ in range(len(a)+1)]
            for i in range(len(a)+1):
                matrix[i][0] = i
            for j in range(len(b)+1):
                matrix[0][j] = j
            for i in range(1, len(a)+1):
                for j in range(1, len(b)+1):
                    matrix[i][j] = min(matrix[i-1][j]+1, matrix[i][j-1]+1,
                                       matrix[i-1][j-1]+(a[i-1] != b[j-1]))
            counts = gate.edit_counts(list(a), list(b))
            assert sum(counts[k] for k in ('substitutions', 'deletions', 'insertions')) == matrix[-1][-1]


def test_jsonl_crlf_unicode_and_torn_tail(tmp_path):
    import json
    path = tmp_path / 'audio records.jsonl'
    body = '\r\n'.join(json.dumps(r, ensure_ascii=False) for r in fixture()) + '\r\n'
    path.write_bytes(body.encode('utf-8') + b'{"type":')
    with pytest.raises(ValueError, match='incomplete'):
        gate.read_records(path)
    rows = gate.read_records(path, repair_tail=True)
    assert len(rows) == 6
    assert path.read_bytes().endswith(b'\n')


def test_run_order_is_ab_ba():
    assert gate.run_order(4) == [(0, False), (0, True), (1, True), (1, False),
                                  (2, False), (2, True), (3, True), (3, False)]


def test_wrong_effective_setting_cannot_pass():
    rows = fixture()
    rows[2]['kwargs'][0]['word_timestamps'] = False
    assert gate.score_records(rows, {'reader.wav': 'one two three'})['verdict'] == 'FAIL'


def test_empty_manifest_cannot_pass():
    rows = [dict(type='manifest', id='empty', files=[], options={'pairs': 1}),
            dict(type='end', manifest_id='empty', complete=True, expected_runs=0)]
    assert gate.score_records(rows)['verdict'] == 'FAIL'


def test_exact_frozen_limits_pass():
    rows = fixture()
    for row in rows:
        if row.get('type') == 'run':
            row['segments'][0]['end'] = 6.5 if row['setting'] else 8.125
            row['wall_seconds'] = 12 if row['setting'] else 10
            row['peak_memory_bytes'] = (356 if row['setting'] else 100) * 2**20
    assert gate.score_records(rows, {'reader.wav': 'one two three'})['verdict'] == 'PASS'


def test_child_uses_real_app_backend_adapter(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from core.backends.faster_whisper_be import FasterWhisperBackend
    calls = []
    class Model:
        def transcribe(self, audio, word_timestamps=False, **kwargs):
            calls.append((audio, word_timestamps))
            word = SimpleNamespace(start=0., end=1., word='hello', probability=.9)
            return iter([SimpleNamespace(start=0., end=1., text='hello', words=[word])]), SimpleNamespace(language='en')
    def load(self, path, status):
        self._model = Model()
    monkeypatch.setattr(FasterWhisperBackend, '_load_self_healing', load)
    result = gate._one(dict(file='a.wav', pair=0, setting=True, manifest_id='test',
        profile=str(tmp_path), options=dict(device='cpu', compute_type='int8', model_dir='model',
        batch_size=1, language='en', no_vad=False, warmup=True)))
    assert calls == [('a.wav', True), ('a.wav', True)]
    assert result['segments'][0]['words'][0]['word'] == 'hello'
    assert result['kwargs'][0]['word_timestamps'] is True
    assert result['peak_memory_bytes'] > 0


def test_run_resume_does_not_repeat_finished_pairs(monkeypatch, tmp_path):
    from argparse import Namespace
    from types import SimpleNamespace
    import json
    model = tmp_path / 'model'
    model.mkdir()
    (model / 'model.bin').write_bytes(b'weights')
    audio = tmp_path / 'file with spaces.wav'
    audio.write_bytes(b'audio')
    args = Namespace(audio=[str(audio)], model_dir=str(model), output=str(tmp_path/'runs.jsonl'),
                     device='cpu', compute_type='int8', language='en', batch_size=1,
                     no_vad=False, pairs=2, cold=False)
    calls = []
    def child(command, **kwargs):
        spec = json.loads(kwargs['input'])
        calls.append((spec['pair'], spec['setting']))
        row = dict(type='run', manifest_id=spec['manifest_id'], file=spec['file'], pair=spec['pair'],
                   setting=spec['setting'], wall_seconds=1, peak_memory_bytes=100,
                   kwargs=[{'word_timestamps': spec['setting']}], segments=[dict(start=0, end=1, text='hello')])
        return SimpleNamespace(returncode=0, stdout=json.dumps(row), stderr='')
    monkeypatch.setattr(gate.subprocess, 'run', child)
    assert gate.run(args) == 0
    assert calls == gate.run_order(2)
    assert gate.run(args) == 0
    assert calls == gate.run_order(2)
    rows = gate.read_records(tmp_path/'runs.jsonl')
    assert rows[-1]['type'] == 'end' and len(rows) == 6
    # A damaged log with an early end marker must not claim completion.
    broken = rows[:2] + [rows[-1]]
    (tmp_path/'runs.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in broken), encoding='utf-8')
    with pytest.raises(ValueError, match='end marker'):
        gate.run(args)
