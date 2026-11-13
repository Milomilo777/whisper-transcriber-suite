"""Secondary capture failures remain useful without duplicating OS wrappers."""
import errno
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import _checkpoint as cp, transcriber as tr, loop_guard
from core.backends.faster_whisper_be import WhisperDecode
from tests.core.test_transcription_endpoint_bounds import Segment, endpoint_case, output_task


@pytest.mark.parametrize('windows', [False, True])
def test_storage_wrapper_is_rendered_once_and_runner_flag_restored(endpoint_case, monkeypatch, windows):
    task=output_task(endpoint_case);task._audio_end=2.488
    raw=[{'start':2.6,'end':3,'text':'rejected'}]
    source=str(endpoint_case.audio)
    error=OSError(0,'synthetic refusal',source,112) if windows else OSError(errno.ENOSPC,'synthetic refusal',source)
    saved=[];keep=tr._keep_timing_recovery
    def write(*args):
        if saved:raise error
        saved.append(keep(*args))
        return saved[0]
    monkeypatch.setattr(tr,'_keep_timing_recovery',write)
    runner=SimpleNamespace(retry_enabled=True)
    with pytest.raises(OSError) as caught:
        tr._enforce_decoded_audio_end(task,list(raw),recovery=lambda:raw,
                                     remaining=iter([{'text':'later'}]),convert=dict,runner=runner)
    assert caught.value is error and runner.retry_enabled is True
    text=str(error)
    assert text.count('[Errno')+text.count('[WinError')==1
    assert text.count(repr(source))==1
    assert saved[0] in text


@pytest.mark.parametrize('value', [None,b'non-string',{'text':'mapping'}])
def test_consumed_unconvertible_cue_does_not_claim_no_cues(endpoint_case,value):
    task=output_task(endpoint_case);task._audio_end=2.488
    raw=[{'start':2.6,'end':3,'text':'rejected'}]
    consumed=[]
    def decoder():
        consumed.append(True)
        yield SimpleNamespace(text=value)
        pytest.fail('Conversion failure stops capture immediately')
    def convert(segment):raise ValueError('controlled conversion failure')
    with pytest.raises(tr._TimingBoundsError) as caught:
        tr._enforce_decoded_audio_end(task,list(raw),recovery=lambda:raw,remaining=decoder(),convert=convert)
    assert consumed==[True]
    assert 'conversion-error:ValueError' in str(caught.value)
    assert 'no extra cues' not in str(caught.value)
    assert 'no additional text was recovered' in str(caught.value)
    assert len(list(cp.partials_dir().glob('*.timing-recovery.json')))==1


@pytest.mark.parametrize('entry', ['detect_language','transcribe'])
def test_disabled_retry_also_covers_eager_backend_entry_points(entry):
    calls=[]
    def fail(*args,**kwargs):raise RuntimeError('CUDA failed with error out of memory')
    backend=SimpleNamespace(detect_language=fail,transcribe=fail)
    def refuse(*args):
        calls.append('recover')
        pytest.fail('Disabled eager entry must not recover')
    runner=WhisperDecode(lambda options:backend,lambda:True,refuse,None)
    runner.retry_enabled=False
    runner.before_retry=lambda:calls.append('checkpoint')
    with pytest.raises(RuntimeError,match='CUDA'):
        getattr(runner,entry)(*(['unused.wav'] if entry=='transcribe' else []))
    assert calls==[]


def test_decoder_oom_has_a_safe_diagnostic_category(endpoint_case,caplog):
    task=output_task(endpoint_case)
    def decoder():
        raise RuntimeError('CUDA failed with error out of memory for C:/private-folder/private-input.wav')
        yield
    _,stopped=tr._capture_timing_tail(task,[],decoder(),dict,'bad timing')
    assert 'out_of_memory' in stopped
    assert 'out_of_memory' in caplog.text
    assert 'private-folder' not in stopped+caplog.text


def test_serialization_failure_is_a_programmer_error_not_an_os_error(endpoint_case):
    task=output_task(endpoint_case);task._audio_end=2.488
    raw=[{'start':2.6,'end':3,'text':'rejected'}]
    with pytest.raises(TypeError) as caught:
        tr._enforce_decoded_audio_end(task,list(raw),recovery=lambda:raw,
            remaining=iter([{'text':'later','unsupported':object()}]),convert=dict)
    assert not isinstance(caught.value,OSError)
    assert len(list(cp.partials_dir().glob('*.timing-recovery.json')))==1
    assert not task.output_paths


def test_passthrough_directly_preserves_unread_raw_cues_without_guard_effects():
    flag=SimpleNamespace(value=False);stats=loop_guard.LoopGuardStats();restarts=[]
    raw=[Segment(n*.2,n*.2+.1,'repeat',[]) for n in range(12)]
    guarded=loop_guard.guard_repeats(iter(raw),limit=3,hard=8,ticks=True,stats=stats,
        restart=lambda at:restarts.append(at) or iter([]),passthrough=lambda:flag.value)
    assert next(guarded) is raw[0]
    flag.value=True
    assert list(guarded)==raw[1:]
    assert stats.dropped==stats.marked==stats.restarts==0 and restarts==[]


def test_capture_after_rejection_inside_release_keeps_remaining_copies_and_follower(endpoint_case):
    task=output_task(endpoint_case);task._audio_end=2.488
    runner=SimpleNamespace(retry_enabled=True)
    raw=[Segment(1.9+n*.2,2+n*.2,'repeat',[]) for n in range(6)]
    raw.append(Segment(3.5,3.6,'following cue',[]))
    guarded=loop_guard.guard_repeats(iter(raw),limit=3,hard=8,
                                   passthrough=lambda:not runner.retry_enabled)
    accepted=[]
    def convert(seg):return {'start':seg.start,'end':seg.end,'text':seg.text}
    for segment in guarded:
        row=convert(segment)
        if row['start']>=task._audio_end:
            original=accepted+[row]
            with pytest.raises(tr._TimingBoundsError):
                tr._enforce_decoded_audio_end(task,[row],recovery=lambda:original,
                                             remaining=guarded,convert=convert,runner=runner)
            break
        accepted.append(row)
    records=[json.loads(p.read_text(encoding='utf-8')) for p in cp.partials_dir().glob('*.timing-recovery.json')]
    retained=max(records,key=lambda record:len(record['segments']))['segments']
    assert [row['text'] for row in retained]==[row.text for row in raw]
    assert [row['start'] for row in retained]==[row.start for row in raw]


@pytest.mark.parametrize('diagnostic_failure',['exception-string','logging-handler'])
def test_failed_diagnostics_do_not_replace_initial_recovery(endpoint_case,monkeypatch,diagnostic_failure):
    task=output_task(endpoint_case);task._audio_end=2.488
    raw=[{'start':2.6,'end':3,'text':'rejected'}]
    class Unprintable(RuntimeError):
        def __str__(self):raise ValueError('controlled broken formatter')
    def decoder():
        if diagnostic_failure=='exception-string':raise Unprintable()
        raise RuntimeError('CUDA failed with error out of memory')
        yield
    if diagnostic_failure=='logging-handler':
        def refuse(*args,**kwargs):raise OSError('controlled logging refusal')
        monkeypatch.setattr(tr.logger,'warning',refuse)
    runner=SimpleNamespace(retry_enabled=True)
    with pytest.raises(tr._TimingBoundsError,match='Recovery data:'):
        tr._enforce_decoded_audio_end(task,list(raw),recovery=lambda:raw,remaining=decoder(),convert=dict,runner=runner)
    assert runner.retry_enabled is True
    assert len(list(cp.partials_dir().glob('*.timing-recovery.json')))==1
