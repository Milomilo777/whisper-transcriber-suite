"""False PASS fixtures and actual recovery with non-Latin filenames."""
import copy
from argparse import Namespace
from types import SimpleNamespace

import pytest

from app.services.download_service import DownloadService, _name_key
from tests.core.test_word_timing_gate import fixture
from tools import word_timing_gate as gate


def valid_rows():
    rows = fixture()
    rows[0]['options'].update(device='cpu', compute_type='int8')
    for row in rows:
        if row.get('type') == 'run':
            row.update(device='cpu', compute_type='int8')
            if row['setting']:
                row['segments'][0]['words'] = [dict(word='one two three', start=0, end=5)]
    return rows


@pytest.mark.parametrize('case', ['deletion', 'empty_words', 'overlap', 'device', 'error'])
def test_gate_refuses_false_pass(case):
    rows = valid_rows()
    ref = 'one two three'
    if case == 'deletion':
        ref = 'alpha beta ' + ' '.join('w'+str(i) for i in range(98))
        for row in rows:
            if row.get('type') == 'run':
                row['segments'][0]['text'] = ('beta z ' if row['setting'] else 'x y ') + ref.split(' ', 2)[2]
    elif case == 'error':
        rows.insert(1, dict(type='error', manifest_id='fixture'))
    else:
        for row in rows:
            if row.get('type') != 'run':
                continue
            if case == 'device':
                row['device'] = 'cuda'
            elif row['setting']:
                if case == 'empty_words':
                    row['segments'][0]['words'] = []
                else:
                    row['segments'] = [dict(start=1, end=4, text='one two',
                        words=[dict(start=1, end=4, word='one two')]),
                        dict(start=2, end=5, text='three', words=[dict(start=2, end=5, word='three')])]
    result = gate.score_records(rows, {'reader.wav': ref})
    assert result['verdict'] == 'FAIL', result


def test_gate_code_hashes_do_not_depend_on_working_directory(tmp_path, monkeypatch):
    model = tmp_path / 'model'
    model.mkdir()
    (model / 'model.bin').write_bytes(b'local test weights')
    audio = tmp_path / 'audio.wav'
    audio.write_bytes(b'audio')
    output = tmp_path / 'run.jsonl'
    args = Namespace(audio=[str(audio)], model_dir=str(model), output=str(output),
        pairs=1, device='cpu', compute_type='int8', language='en', batch_size=1,
        no_vad=False, cold=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(gate.subprocess, 'run', lambda *a, **kw:
        SimpleNamespace(returncode=1, stdout='', stderr='controlled stop after manifest'))
    assert gate.run(args) == 1
    assert len(gate.read_records(output)[0]['code']) == 6


@pytest.mark.parametrize('announced,foreign', [
    ('\u06a9\u062a\u0627\u0628\u0650', '\u06a9\u062a\u0627\u0628'),
    ('\u0915\u093f\u0924\u093e\u092c', '\u0915\u0924\u093e\u092c'),
    ('\u0e01\u0e48\u0e32', '\u0e01\u0e32'), ('$$$', '+++')])
def test_recovery_does_not_claim_distinct_marked_title(tmp_path, announced, foreign):
    (tmp_path / (foreign+'.mp4')).write_bytes(b'other download')
    service = DownloadService(SimpleNamespace())
    task = SimpleNamespace(folder=str(tmp_path), title=announced, start_time=0)
    assert service._find_recovered_path(task, None) == (None, True)
    saved = tmp_path / (announced+'.mp4')
    saved.write_bytes(b'correct download')
    assert service._find_recovered_path(task, None) == (str(saved), False)


def test_greek_canonical_caseless_equivalence():
    assert _name_key('\u03aa\u0301') == _name_key('\u0390')
