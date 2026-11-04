"""Export and dispatch contracts for word-enabled and raw-bound fallback segments."""
import html
from io import BytesIO
import json
import re
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('text', ['Hello & welcome.', '\u4f60\u597d\u4e16\u754c', '\u0633\u0644\u0627\u0645 \u062f\u0646\u06cc\u0627'])
@pytest.mark.parametrize('has_words', [False, True])
def test_five_writers_preserve_text_and_speaker(text, has_words):
    from core.writers import srt, vtt, txt, json_writer, docx_writer
    from docx import Document
    words = [dict(word=text, start=.3, end=.6, probability=.9)] if has_words else []
    segments = [dict(start=0., end=1., text=text, words=words, speaker='Speaker 01')]
    assert text in srt.write(segments)
    assert text in txt.write(segments)
    body = vtt.write(segments)
    assert text in html.unescape(re.sub('<[^>]+>', '', body))
    encoded = json.loads(json_writer.write(segments))
    assert encoded[0]['text'] == text
    assert bool(encoded[0].get('words')) is has_words
    paragraphs = '\n'.join(p.text for p in Document(BytesIO(docx_writer.write_bytes(segments))).paragraphs)
    assert text in paragraphs
    assert 'Speaker 01' in paragraphs


def test_live_explicitly_disables_words_even_for_enabled_profile(monkeypatch):
    from core import transcriber as tr
    calls = []
    def transcribe(audio, **kwargs):
        calls.append(kwargs)
        return iter([SimpleNamespace(start=0, end=1, text='hello')]), SimpleNamespace(language='en')
    monkeypatch.setattr(tr, 'MODEL', SimpleNamespace(transcribe=transcribe))
    monkeypatch.setattr(tr, 'MODEL_READY', True)
    monkeypatch.setattr(tr, 'PIPELINE', None)
    monkeypatch.setattr(tr, 'MODEL_ERROR', None)
    monkeypatch.setitem(tr.config, 'word_timestamps', True)
    assert tr.transcribe_chunk_to_text('audio.wav')['text'] == 'hello'
    assert calls[0]['word_timestamps'] is False


def test_translation_keeps_requested_words():
    from core import transcriber as tr
    from core.task import TranscriptionTask
    task = TranscriptionTask('audio.wav')
    task.whisper_task = 'translate'
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(tr.config, 'word_timestamps', True)
        kwargs = tr._build_transcribe_kwargs(task)
    assert kwargs['task'] == 'translate'
    assert kwargs['word_timestamps'] is True


def test_diarization_preserves_words_and_segment_text():
    from core.diarization import DiarSegment, assign_speakers_to_segments
    words = [dict(word='hello', start=0., end=.6, probability=.9)]
    segments = [dict(start=0., end=1., text='hello', words=words)]
    assign_speakers_to_segments(segments, [DiarSegment(start=0., end=1., speaker='Speaker 01')])
    assert segments[0]['words'] == words
    assert segments[0]['text'] == 'hello'
    assert segments[0]['speaker'] == 'Speaker 01'


def test_api_explicit_false_is_not_replaced_by_default():
    from core.server.httpd import normalize_options
    assert normalize_options({'word_timestamps': False})['word_timestamps'] is False
    assert normalize_options({'word_timestamps': True})['word_timestamps'] is True
    assert 'word_timestamps' not in normalize_options({})
