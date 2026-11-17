"""CPU-only Kokoro -> Whisper recall; opt in with existing local model paths.

Set WHISPER_SMOKE_KOKORO_MODEL to the unpacked Kokoro directory and
WHISPER_SMOKE_KOKORO_ASR to a faster-whisper model directory, then run
``python -m pytest tests/smoke/test_kokoro_word_recall.py -q -s``.
No models are downloaded. JSON lines contain the transcript and recall counts.
Use the same model directories and corpus for before/after measurements.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path

import pytest

from core import tts_kokoro as k


# Reference text is the spoken form, rather than the written digits.
ENGLISH = [
    ('One term you hear a lot is "token". It is not the number of questions you ask.',
     'One term you hear a lot is token. It is not the number of questions you ask.'),
    ("OpenAI's ChatGPT or Gemini may be one word or part of a word.",
     "OpenAI's ChatGPT or Gemini may be one word or part of a word."),
    ('Part 7. Tokens and cost. There are three kinds: input tokens, reasoning tokens and output.',
     'Part seven. Tokens and cost. There are three kinds: input tokens, reasoning tokens and output.'),
    ("The writer's questions include Dr. Smith's examples and the U.S. team's answers.",
     "The writer's questions include doctor Smith's examples and the U S team's answers."),
    ('On November 17, 2026, we counted 42 questions.',
     'On November seventeen year2026 we counted forty two questions.'),
    ('She calls them “tokens,” and asks: “What does API mean?”',
     'She calls them tokens and asks what does A P I mean.'),
]
OTHER_LANGUAGES = [
    ('zf_xiaobei', 'zh', '今天我们学习新的知识，也一起回答大家的问题。'),
    ('ef_dora', 'es', 'Hoy aprendemos palabras nuevas y respondemos las preguntas de nuestros amigos.'),
    ('ff_siwis', 'fr', 'Nous apprenons de nouveaux mots et répondons aux questions de nos amis.'),
    ('hf_alpha', 'hi', 'आज हम नए शब्द सीखते हैं और अपने दोस्तों के सवालों के जवाब देते हैं।'),
    ('if_sara', 'it', 'Oggi impariamo parole nuove e rispondiamo alle domande dei nostri amici.'),
    ('jf_alpha', 'ja', '今日は新しい言葉を学び、友達の質問に答えます。'),
    ('pf_dora', 'pt', 'Hoje aprendemos palavras novas e respondemos às perguntas dos nossos amigos.'),
]


def _units(text: str, language: str) -> list[str]:
    text = text.lower().replace('’', "'")
    # Whisper may format numbers or product names differently from the input.
    for pattern, replacement in (
        (r'\b(?:two thousand (?:and )?twenty[ -]six|twenty twenty[ -]six|2026)\b', 'year2026'),
        (r'\b17(?:th)?\b|\bseventeenth\b', 'seventeen'),
        (r'\b42\b', 'forty two'), (r'\b7\b', 'seven'),
        (r'\bopen\s*ai\b', 'openai'), (r'\bchat\s*g\s*p\s*t\b', 'chatgpt'),
        (r'\bapi\b', 'a p i'), (r'\bdr\b\.?', 'doctor'),
    ):
        text = re.sub(pattern, replacement, text)
    if language in ('zh', 'ja'):
        return [c for c in text if c.isalnum()]
    return re.findall(r"[^\W_]+(?:'[^\W_]+)?", text, re.UNICODE)


def _matched(reference: list[str], heard: list[str]) -> int:
    """Ordered recall using LCS; repeated words cannot reuse one ASR word."""
    row = [0] * (len(heard) + 1)
    for word in reference:
        previous = row[:]
        for i, actual in enumerate(heard, 1):
            row[i] = previous[i - 1] + 1 if word == actual else max(previous[i], row[i - 1])
    return row[-1]


@pytest.mark.parametrize('reference,heard,count', [
    (['tokens', 'tokens'], ['tokens'], 1),
    (['input', 'tokens', 'output'], ['input', 'output'], 2),
    (['one', 'two'], ['two', 'one'], 1),
])
def test_recall_counts_omissions(reference, heard, count):
    assert _matched(reference, heard) == count


@pytest.fixture(scope='module')
def models():
    kokoro = os.environ.get('WHISPER_SMOKE_KOKORO_MODEL')
    whisper = os.environ.get('WHISPER_SMOKE_KOKORO_ASR')
    if not kokoro or not whisper:
        pytest.skip('Set both existing Kokoro and faster-whisper smoke model directories')
    for directory, filename in ((kokoro, 'model.onnx'), (whisper, 'model.bin')):
        assert (Path(directory) / filename).is_file(), f'Missing smoke model: {filename}'
    from faster_whisper import WhisperModel

    return Path(kokoro), WhisperModel(
        whisper, device='cpu', compute_type='int8', cpu_threads=2,
        num_workers=1, local_files_only=True,
    )


@pytest.mark.parametrize('voice', ['af_heart', 'bf_emma'])
def test_english_word_recall(models, monkeypatch, tmp_path, voice):
    _round_trip(models, monkeypatch, tmp_path, voice, 'en', ENGLISH, 0.90)


@pytest.mark.parametrize('voice,language,text', OTHER_LANGUAGES)
def test_other_language_recall(models, monkeypatch, tmp_path, voice, language, text):
    _round_trip(models, monkeypatch, tmp_path, voice, language, [(text, text)], 0.80)


def _round_trip(models, monkeypatch, tmp_path, voice, language, corpus, minimum):
    import sherpa_onnx

    directory, recognizer = models
    monkeypatch.setattr(k, 'model_dir', lambda: directory)
    monkeypatch.setattr(k, '_engines', {})
    matched = total = 0
    missing_targets = []
    for index, (text, reference) in enumerate(corpus):
        path = tmp_path / f'{index}.wav'
        result = k.generate(text, voice, str(path), speed=1.0)
        assert result.audio_seconds > 0
        segments, _ = recognizer.transcribe(
            str(path), language=language, beam_size=5, vad_filter=False,
        )
        heard = ' '.join(segment.text.strip() for segment in segments)
        expected = _units(reference, language)
        actual = _units(heard, language)
        count = _matched(expected, actual)
        if language == 'en':
            expected_counts, actual_counts = Counter(expected), Counter(actual)
            for target in ('token', 'tokens', 'questions', "openai's", 'chatgpt', 'seven'):
                if actual_counts[target] < expected_counts[target]:
                    missing_targets.append((index, target))
        matched += count
        total += len(expected)
        print(json.dumps(dict(version=sherpa_onnx.__version__, voice=voice, text=text,
                              heard=heard, matched=count, total=len(expected)), ensure_ascii=True))
    print(json.dumps(dict(voice=voice, matched=matched, total=total, recall=matched / total)))
    assert not missing_targets, f'Omitted regression targets: {missing_targets}'
    assert matched / total >= minimum
