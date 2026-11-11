"""Decoded endpoints respect known media bounds without losing decoded text."""
from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
import json
from pathlib import Path
import re
from types import SimpleNamespace
from typing import NamedTuple
import wave

import pytest

from core import _checkpoint as cp, transcriber as tr
from core.task import TranscriptionTask


class Word(NamedTuple):
    start: float
    end: float
    word: str = "last"
    probability: float = 0.9


class Segment(NamedTuple):
    start: float
    end: float
    text: str = "last words"
    words: object = None


@pytest.fixture
def endpoint_case(monkeypatch, tmp_path):
    audio = tmp_path / "input.wav"
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\0\0" * 39808)
    with wave.open(str(audio), "rb") as source:
        duration = source.getnframes() / source.getframerate()
    assert duration == 2.488
    cfg = {**tr.config, "transcribe_backend": "faster_whisper",
           "model_path": "fake-model", "model_size": "small", "batch_size": 1,
           "word_timestamps": True, "demucs_enabled": False,
           "denoise_enabled": False, "loop_guard_repeats": 0,
           "output_filename_template": "{base}.{ext}"}
    monkeypatch.setattr(tr, "config", cfg)
    monkeypatch.setattr(tr, "_runtime_overrides_scope", lambda task: nullcontext(cfg))
    monkeypatch.setattr(cp, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(tr, "get_duration", lambda path: duration)
    monkeypatch.setattr(tr, "require_audio_stream", lambda path: None)
    monkeypatch.setattr(tr, "MODEL_READY", True)
    monkeypatch.setattr(tr, "MODEL_ERROR", None)
    monkeypatch.setattr(tr, "PIPELINE", None)
    monkeypatch.setattr(tr, "device", "cpu")
    monkeypatch.setattr(tr, "_EFFECTIVE_DEVICE", "cpu")
    monkeypatch.setattr(tr, "_apply_language_prior", lambda *a, **kw: None)
    monkeypatch.setattr(tr, "_rescue_collapsed", lambda task, data, *a, **kw: data)
    monkeypatch.setattr(tr, "_run_post_pipeline", lambda *a, **kw: 0)
    chapter_writer = tr._write_chapter_sidecar
    monkeypatch.setattr(tr, "_write_chapter_sidecar", lambda *a, **kw: None)
    writes = []
    write_outputs = tr._write_outputs

    def write(base, segments, *args, **kwargs):
        writes.append(deepcopy(segments))
        return write_outputs(base, segments, *args, **kwargs)

    monkeypatch.setattr(tr, "_write_outputs", write)

    def slice_audio(source, start, directory, **kwargs):
        tail = tmp_path / "tail.wav"
        tail.write_bytes(audio.read_bytes())
        return str(tail)

    monkeypatch.setattr(tr, "_slice_audio_from", slice_audio)
    return SimpleNamespace(audio=audio, duration=duration, writes=writes, chapter_writer=chapter_writer)


def install_model(monkeypatch, segments, *, duration=2.488):
    class Model:
        def transcribe(self, audio, **kwargs):
            return iter(segments), SimpleNamespace(
                language="en", language_probability=0.9, duration=duration,
                duration_after_vad=0.1,
            )

    monkeypatch.setattr(tr, "MODEL", Model())


def output_task(case):
    task = TranscriptionTask(str(case.audio))
    task.output_formats = ["srt", "json", "txt"]
    return task


def assert_written_bound(case, task, start, end):
    assert len(case.writes[-1]) == 1
    segment = case.writes[-1][0]
    assert segment["text"] == "last words"
    assert segment["start"] == pytest.approx(start)
    assert segment["end"] == pytest.approx(end)
    assert 0 <= segment["start"] < segment["end"] <= end
    words = segment["words"]
    assert [word["word"] for word in words] == ["last"]
    assert all(start <= word["start"] <= word["end"] <= end for word in words)
    json_path = next(Path(path) for path in task.output_paths if path.endswith(".json"))
    assert json.loads(json_path.read_text(encoding="utf-8"))[0]["end"] == pytest.approx(end)
    srt_path = next(Path(path) for path in task.output_paths if path.endswith(".srt"))
    assert "last words" in srt_path.read_text(encoding="utf-8")
    txt_path = next(Path(path) for path in task.output_paths if path.endswith(".txt"))
    assert "last words" in txt_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("clip", [None, (0.5, 1.488), (0.5, None), (0.5, 99.0)])
def test_saved_segment_and_words_stop_at_selected_audio_end(endpoint_case, monkeypatch, clip):
    case = endpoint_case
    task = output_task(case)
    offset = clip[0] if clip else 0.0
    end = min(clip[1], case.duration) if clip and clip[1] else case.duration
    start = end - 0.348
    install_model(monkeypatch, [Segment(start - offset, end - offset + 0.632,
                                       words=[Word(start - offset + 0.1,
                                                   end - offset + 0.632)])], duration=end - offset)
    if clip:
        task.clip_start, task.clip_end = clip
    tr.transcribe(task)
    assert_written_bound(case, task, start, end)


def test_periodic_and_completed_checkpoints_keep_bounded_end(endpoint_case, monkeypatch):
    case = endpoint_case
    install_model(monkeypatch, [Segment(2.14, 3.12, words=[Word(2.3, 3.12)])])
    monkeypatch.setattr(tr, "_CHECKPOINT_EVERY_N_SEGMENTS", 1)
    recorded = []
    original = tr._write_periodic_checkpoint

    def checkpoint(task, segments, cursor, *args, **kwargs):
        recorded.append((deepcopy(segments), cursor))
        return original(task, segments, cursor, *args, **kwargs)

    monkeypatch.setattr(tr, "_write_periodic_checkpoint", checkpoint)
    tr.transcribe(output_task(case))
    assert len(recorded) >= 2
    assert all(segments[-1]["end"] <= case.duration and cursor <= case.duration
               for segments, cursor in recorded)
    assert all(segments[-1]["text"] == "last words" for segments, _ in recorded)


def test_resume_tail_caps_after_offset_on_original_timeline(endpoint_case, monkeypatch):
    case = endpoint_case
    task = output_task(case)
    tr._write_periodic_checkpoint(task, [{"start": 0, "end": 1, "text": "prior"}],
                                  1, "en", 0.9, None)
    install_model(monkeypatch, [Segment(1.14, 2.12, words=[Word(1.3, 2.12)])],
                  duration=case.duration - 1)
    assert tr.resume_transcription(task)
    assert [seg["text"] for seg in case.writes[-1]] == ["prior", "last words"]
    assert case.writes[-1][0] == {"start": 0, "end": 1, "text": "prior"}
    last = case.writes[-1][-1]
    assert last["start"] == pytest.approx(2.14)
    assert last["end"] == pytest.approx(case.duration)
    assert last["words"][0]["end"] == pytest.approx(case.duration)


def test_post_alignment_cannot_reintroduce_out_of_media_end(endpoint_case, monkeypatch):
    case = endpoint_case
    task = output_task(case)
    install_model(monkeypatch, [Segment(2.14, 2.4, words=[Word(2.3, 2.4)])])

    def align(task, segments, *args):
        segments[-1]["end"] = 3.12
        segments[-1]["words"][0]["end"] = 3.12
        return 0

    monkeypatch.setattr(tr, "_run_post_pipeline", align)
    tr.transcribe(task)
    assert_written_bound(case, task, 2.14, case.duration)


def test_completed_resume_checkpoint_is_bounded_before_output(endpoint_case, monkeypatch):
    case = endpoint_case
    task = output_task(case)
    segments = [{"start": 2.14, "end": 3.12, "text": "last words",
                 "words": [{"start": 2.3, "end": 3.12, "word": "last", "probability": 0.9}]}]
    tr._write_periodic_checkpoint(task, segments, 3.12, "en", 0.9, None,
                                  transcription_completed=True)
    monkeypatch.setattr(tr, "_slice_audio_from", lambda *a, **kw: pytest.fail("no decode needed"))
    assert tr.resume_transcription(task)
    assert_written_bound(case, task, 2.14, case.duration)


@pytest.mark.parametrize("duration,end", [(0.0, 3.12), (2.488, 1.4)])
def test_valid_or_unknown_duration_retains_original_times(endpoint_case, monkeypatch, duration, end):
    case = endpoint_case
    monkeypatch.setattr(tr, "get_duration", lambda path: duration)
    if duration == 0:
        # The PCM header alone is not trusted: remove the final frames so
        # neither the container estimate nor verified samples know the end.
        case.audio.write_bytes(case.audio.read_bytes()[:-32000])
    install_model(monkeypatch, [Segment(0.2, end, words=[Word(0.3, end)])], duration=duration)
    task = output_task(case)
    tr.transcribe(task)
    assert_written_bound(case, task, 0.2, end)


def test_endpoint_does_not_prove_iterator_completion(endpoint_case, monkeypatch):
    case = endpoint_case

    def segments():
        yield Segment(2.14, 3.12, words=[Word(2.3, 3.12)])
        raise RuntimeError("decoder failed after the final timestamp")

    install_model(monkeypatch, segments())
    task = output_task(case)
    with pytest.raises(RuntimeError, match="decoder failed after the final timestamp"):
        tr.transcribe(task)
    assert not case.writes
    checkpoint = cp.load_checkpoint(str(case.audio))
    assert checkpoint["segments"][0]["text"] == "last words"


@pytest.mark.parametrize("probe", [0.0, 1.0, 8.0])
def test_actual_decoder_duration_wins_over_container_estimate(endpoint_case, monkeypatch, probe):
    case = endpoint_case
    monkeypatch.setattr(tr, "get_duration", lambda path: probe)
    install_model(monkeypatch, [Segment(2.14, 3.12, words=[Word(2.3, 3.12)])],
                  duration=case.duration)
    task = output_task(case)
    tr.transcribe(task)
    assert_written_bound(case, task, 2.14, case.duration)


@pytest.mark.parametrize("fmt", tr.supported_formats())
@pytest.mark.parametrize("duration", [2.488, 39817 / 16000, 47993 / 16000])
@pytest.mark.parametrize("near_end", [False, True])
def test_every_real_writer_keeps_serialized_timestamps_inside_audio(
    endpoint_case, monkeypatch, fmt, duration, near_end,
):
    case = endpoint_case
    with wave.open(str(case.audio), "wb") as source:
        source.setnchannels(1)
        source.setsampwidth(2)
        source.setframerate(16000)
        source.writeframes(b"\0\0" * round(duration * 16000))
    monkeypatch.setattr(tr, "get_duration", lambda path: duration)
    interval_formats = {"srt", "vtt", "ass", "tsv", "elan"}
    start = (duration - (0.018 if fmt in interval_formats else 0.00001)) if near_end else 2.14
    install_model(monkeypatch, [Segment(start, duration + 0.632,
                                       words=[Word(start, duration + 0.632, "last words")])], duration=duration)
    task = output_task(case)
    task.output_formats = [fmt]
    if fmt == "pdf":
        from reportlab import rl_config

        monkeypatch.setattr(rl_config, "pageCompression", 0)
    tr.transcribe(task)
    assert len(task.output_paths) == 1
    path = Path(task.output_paths[0])
    assert path.is_file() and path.stat().st_size
    assert case.writes[-1][0]["text"] == "last words"
    assert case.writes[-1][0]["end"] <= duration
    if fmt in {"json", "srt", "vtt", "ass", "tsv", "elan"}:
        from core.convert import parse_to_segments

        parsed = parse_to_segments(str(path))
        assert parsed and "last" in parsed[0]["text"]
        assert all(0 <= item["start"] < item["end"] <= duration for item in parsed)
        assert all(word["end"] <= duration for item in parsed for word in item.get("words", []))
        if fmt == "vtt":
            inline = re.findall(r"<(\d+:\d\d:\d\d\.\d+)>", path.read_text(encoding="utf-8"))
            assert inline and all(_clock_seconds(value) <= duration for value in inline)
    elif fmt in {"docx", "smtv_docx"}:
        from docx import Document

        document = Document(path)
        text = "\n".join([paragraph.text for paragraph in document.paragraphs] +
                         [cell.text for table in document.tables for row in table.rows for cell in row.cells])
        assert "last words" in text
        assert all(_clock_seconds(value) <= duration for value in re.findall(r"\d+:\d\d:\d\d(?:\.\d+)?", text))
    elif fmt == "pdf":
        content = path.read_bytes()
        assert content.startswith(b"%PDF-")
        strings = re.findall(rb"\(([^()]*)\)\s*Tj", content)
        assert b"last words" in b" ".join(strings)
        assert all(_clock_seconds(clock.decode("ascii")) <= duration
                   for item in strings for clock in re.findall(rb"\d+:\d\d:\d\d", item))
    elif fmt == "otr":
        body = json.loads(path.read_text(encoding="utf-8"))
        timestamps = re.findall(r'data-timestamp="([\d.]+)"', body["text"])
        assert timestamps and all(float(value) <= duration for value in timestamps)
        assert "last words" in body["text"]
    else:
        text = path.read_text(encoding="utf-8")
        assert "last" in text
        # These formats emit starts only, so inferred import durations are
        # not an emitted media endpoint (oTranscribe assumes a five-second tail).
        clocks = re.findall(r"\d+:\d\d(?::\d\d)?(?:\.\d+)?", text)
        assert all(_clock_seconds(value) <= duration for value in clocks)


def _clock_seconds(clock):
    seconds = 0.0
    for part in clock.split(":"):
        seconds = seconds * 60 + float(part)
    return seconds


@pytest.mark.parametrize("fmt,start", [("srt", 2.4879), ("vtt", 2.4879), ("ass", 2.479)])
def test_short_final_cue_keeps_a_representable_positive_interval(endpoint_case, monkeypatch, fmt, start):
    duration = 39817 / 16000
    with wave.open(str(endpoint_case.audio), "wb") as source:
        source.setnchannels(1)
        source.setsampwidth(2)
        source.setframerate(16000)
        source.writeframes(b"\0\0" * 39817)
    install_model(monkeypatch, [Segment(start, duration, words=[])], duration=duration)
    task = output_task(endpoint_case)
    task.output_formats = [fmt]
    tr.transcribe(task)
    from core.convert import parse_to_segments

    result = parse_to_segments(task.output_paths[0])
    assert result[0]["text"] == "last words"
    assert 0 <= result[0]["start"] < result[0]["end"] <= duration


@pytest.mark.parametrize("kind", ["segment", "word", "unrepresentable"])
def test_unusable_timing_keeps_all_decoded_text_before_error(endpoint_case, monkeypatch, kind):
    case = endpoint_case
    invalid = (Segment(2.6, 3.12, words=[Word(2.7, 3.12)]) if kind == "segment" else
               Segment(2.14, 3.12, words=[Word(2.6, 3.12)]) if kind == "word" else
               Segment(2.4884, 39817 / 16000, words=[]))
    duration = 39817 / 16000 if kind == "unrepresentable" else case.duration
    if kind == "unrepresentable":
        with wave.open(str(case.audio), "wb") as source:
            source.setnchannels(1)
            source.setsampwidth(2)
            source.setframerate(16000)
            source.writeframes(b"\0\0" * 39817)
    install_model(monkeypatch, [invalid], duration=duration)
    task = output_task(case)
    task.output_formats = ["srt"]
    with pytest.raises(RuntimeError):
        tr.transcribe(task)
    saved = []
    for path in cp.partials_dir().rglob("*"):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeError, ValueError):
            continue
        saved.extend(data.get("segments", []))
    assert any(item.get("text") == "last words" for item in saved)
    if kind == "word":
        assert any(any(word.get("word") == "last" for word in item.get("words", [])) for item in saved)
    assert not task.output_paths


def test_long_pcm_input_bounds_the_last_cue_and_checkpoint(endpoint_case, monkeypatch):
    case = endpoint_case
    with wave.open(str(case.audio), "wb") as source:
        source.setnchannels(1)
        source.setsampwidth(2)
        source.setframerate(16000)
        for _ in range(2619):
            source.writeframesraw(b"\0\0" * 16000)
        source.writeframesraw(b"\0\0" * 7808)
    with wave.open(str(case.audio), "rb") as source:
        duration = source.getnframes() / source.getframerate()
    assert duration == 2619.488
    monkeypatch.setattr(tr, "get_duration", lambda path: duration)
    install_model(monkeypatch, [Segment(0, 0.5, "first", []),
                               Segment(2590.14, 2620.12, words=[Word(2600.2, 2620.12)])],
                  duration=duration)
    monkeypatch.setattr(tr, "_CHECKPOINT_EVERY_N_SEGMENTS", 1)
    captured = []
    checkpoint = tr._write_periodic_checkpoint

    def record(task, segments, cursor, *args, **kwargs):
        captured.append((deepcopy(segments), cursor))
        return checkpoint(task, segments, cursor, *args, **kwargs)

    monkeypatch.setattr(tr, "_write_periodic_checkpoint", record)
    task = output_task(case)
    tr.transcribe(task)
    assert [item["text"] for item in case.writes[-1]] == ["first", "last words"]
    assert case.writes[-1][-1]["end"] == pytest.approx(duration)
    assert all(segments[-1]["end"] <= duration and cursor <= duration for segments, cursor in captured)


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -1, "2.488", True, 9999])
def test_invalid_saved_audio_bound_keeps_original_checkpoint(endpoint_case, monkeypatch, invalid):
    case = endpoint_case
    task = output_task(case)
    prior = [{"start": 0, "end": 1, "text": "saved text", "words": []}]
    tr._write_periodic_checkpoint(task, prior, 1, "en", 0.9, None,
                                  transcription_completed=True)
    path = cp.checkpoint_path(str(case.audio))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["audio_end"] = invalid
    original = json.dumps(payload).encode("utf-8")
    path.write_bytes(original)
    assert tr.resume_transcription(task) is False
    assert not case.writes
    assert any(item.is_file() and item.read_bytes() == original for item in path.parent.rglob("*"))


def test_invalid_clip_saves_raw_words_without_replacing_whole_file_checkpoint(endpoint_case, monkeypatch):
    case = endpoint_case
    whole = output_task(case)
    tr._write_periodic_checkpoint(whole, [{"start": 0, "end": 0.5, "text": "old whole-file text"}],
                                  0.5, "en", 0.9, None)
    path = cp.checkpoint_path(str(case.audio))
    old_bytes = path.read_bytes()
    original = Segment(1.1, 1.5, words=[Word(1.2, 1.5)])
    install_model(monkeypatch, [original], duration=0.988)
    task = output_task(case)
    task.clip_start, task.clip_end = 0.5, 1.488
    with pytest.raises(RuntimeError):
        tr.transcribe(task)
    assert path.read_bytes() == old_bytes
    assert original.words[0] == Word(1.2, 1.5)
    raw = [json.loads(item.read_text(encoding="utf-8"))
           for item in path.parent.glob("*.timing-recovery.json")]
    assert raw[-1]["segments"][0]["text"] == "last words"
    assert raw[-1]["segments"][0]["words"][0]["word"] == "last"
    assert raw[-1]["segments"][0]["end"] == 2.0


def test_completed_checkpoint_reuses_saved_sample_end_without_container_guess(endpoint_case, monkeypatch):
    case = endpoint_case
    task = output_task(case)
    task._audio_end = case.duration
    segments = [{"start": 2.14, "end": 3.12, "text": "last words",
                 "words": [{"start": 2.3, "end": 3.12, "word": "last", "probability": 0.9}]}]
    tr._write_periodic_checkpoint(task, segments, 3.12, "en", 0.9, None,
                                  transcription_completed=True)
    monkeypatch.setattr(tr, "get_duration", lambda path: 0.1)
    assert tr.resume_transcription(output_task(case))
    assert case.writes[-1][0]["end"] == pytest.approx(case.duration)


@pytest.mark.parametrize("fmt", ["srt", "vtt", "ass"])
@pytest.mark.parametrize("case_name", ["tiny-segment", "zero-segment", "zero-word"])
def test_existing_small_timing_repairs_stay_compatible_away_from_eof(
    endpoint_case, monkeypatch, fmt, case_name,
):
    from core.writers import get_writer

    if case_name == "tiny-segment":
        decoded = Segment(0.2001, 0.2002, words=[])
    elif case_name == "zero-segment":
        decoded = Segment(0.2, 0.2, words=[])
    else:
        decoded = Segment(0.2, 1.0, words=[Word(0.5, 0.5)])
    expected = get_writer(fmt)([tr._segment_to_dict(decoded, True)], str(endpoint_case.audio))
    install_model(monkeypatch, [decoded])
    task = output_task(endpoint_case)
    task.output_formats = [fmt]
    tr.transcribe(task)
    assert Path(task.output_paths[0]).read_text(encoding="utf-8") == expected


def test_rejected_later_segment_preserves_the_entire_original_record(endpoint_case):
    task = output_task(endpoint_case)
    task._audio_end = 2.0
    raw = [{"start": 0, "end": 3, "text": "first raw words", "words": []},
           {"start": 3, "end": 4, "text": "second raw words", "words": []}]
    original = deepcopy(raw)
    with pytest.raises(RuntimeError):
        tr._enforce_audio_end(task, raw)
    assert raw == original
    records = [json.loads(path.read_text(encoding="utf-8"))
               for path in cp.partials_dir().glob("*.timing-recovery.json")]
    assert records[-1]["segments"] == original


def test_resampler_rounding_does_not_extend_the_original_pcm(endpoint_case, monkeypatch):
    from faster_whisper.audio import decode_audio

    case = endpoint_case
    with wave.open(str(case.audio), "wb") as source:
        source.setnchannels(1)
        source.setsampwidth(2)
        source.setframerate(44100)
        source.writeframes(b"\0\0" * 109747)
    source_end = 109747 / 44100
    decoded_end = len(decode_audio(str(case.audio))) / 16000
    assert decoded_end > source_end
    monkeypatch.setattr(tr, "get_duration", lambda path: 8.0)
    install_model(monkeypatch, [Segment(2.14, 3.12, words=[Word(2.3, 3.12)])],
                  duration=decoded_end)
    task = output_task(case)
    tr.transcribe(task)
    assert case.writes[-1][0]["end"] <= source_end + 1e-9


@pytest.mark.parametrize("duration", [2.488, 39817 / 16000])
def test_cloud_failure_partial_srt_uses_the_same_audio_endpoint(endpoint_case, monkeypatch, duration):
    from core.backends.base import PartialResultError
    from core.convert import parse_to_segments

    case = endpoint_case
    with wave.open(str(case.audio), "wb") as source:
        source.setnchannels(1)
        source.setsampwidth(2)
        source.setframerate(16000)
        source.writeframes(b"\0\0" * round(duration * 16000))
    error = PartialResultError("original provider failure", [{"start": 2.14, "end": 3.12,
                                                              "text": "paid words", "words": []}])

    class Backend:
        def transcribe_to_segments(self, *args, **kwargs):
            raise error

    with pytest.raises(PartialResultError) as caught:
        tr._transcribe_via_alt_backend("test", output_task(case), None, None, None, backend=Backend())
    assert caught.value is error
    parsed = parse_to_segments(str(case.audio.with_suffix(".partial.srt")))
    assert parsed[0]["text"] == "paid words"
    assert parsed[0]["end"] <= duration


def test_invalid_paid_partial_keeps_original_error_and_previous_file(endpoint_case):
    from core.backends.base import PartialResultError

    case = endpoint_case
    partial = case.audio.with_suffix(".partial.srt")
    partial.write_text("previous partial sentinel", encoding="utf-8")
    old = partial.read_bytes()
    segments = [{"start": 2.6, "end": 3.12, "text": "paid words",
                 "words": [{"start": 2.7, "end": 3.12, "word": "paid", "probability": 0.9}]}]
    error = PartialResultError("original provider failure", segments)

    class Backend:
        def transcribe_to_segments(self, *args, **kwargs):
            raise error

    with pytest.raises(PartialResultError) as caught:
        tr._transcribe_via_alt_backend("test", output_task(case), None, None, None, backend=Backend())
    assert caught.value is error and partial.read_bytes() == old
    records = [json.loads(path.read_text(encoding="utf-8"))
               for path in cp.partials_dir().glob("*.timing-recovery.json")]
    assert records[-1]["segments"] == segments


@pytest.mark.parametrize("chapter_start", [0.0, 2.6])
def test_chapter_sidecar_never_exports_an_out_of_audio_extent(endpoint_case, monkeypatch, chapter_start):
    case = endpoint_case
    install_model(monkeypatch, [Segment(2.14, 2.4, words=[Word(2.3, 2.4)])])
    monkeypatch.setattr(tr, "_write_chapter_sidecar", case.chapter_writer)

    def post(task, segments, *args):
        task._chapters_for_writer = [{"start": chapter_start, "end": 3.12, "title": "kept chapter"}]
        return 0

    monkeypatch.setattr(tr, "_run_post_pipeline", post)
    task = output_task(case)
    tr.transcribe(task)
    sidecars = [path for path in task.output_paths if path.endswith(".chapters.json")]
    if chapter_start == 0:
        assert len(sidecars) == 1
        chapters = json.loads(Path(sidecars[0]).read_text(encoding="utf-8"))
        assert chapters[0]["title"] == "kept chapter" and chapters[0]["end"] <= case.duration
    else:
        assert not sidecars
        records = [json.loads(path.read_text(encoding="utf-8"))
                   for path in cp.partials_dir().glob("*.timing-recovery.json")]
        assert records[-1]["segments"][0]["title"] == "kept chapter"


def test_derived_audio_cannot_extend_original_pcm_media(endpoint_case, monkeypatch, tmp_path):
    case = endpoint_case
    derived = tmp_path / "derived.wav"
    with wave.open(str(derived), "wb") as source:
        source.setnchannels(1)
        source.setsampwidth(2)
        source.setframerate(16000)
        source.writeframes(b"\0\0" * 48000)
    monkeypatch.setattr(tr, "_maybe_denoise", lambda *a, **kw: (str(derived), ""))
    install_model(monkeypatch, [Segment(2.14, 3.12, words=[Word(2.3, 3.12)])], duration=3.0)
    task = output_task(case)
    tr.transcribe(task)
    assert case.writes[-1][0]["end"] == pytest.approx(case.duration)


@pytest.mark.parametrize("outside", [False, True])
def test_alternative_backend_cancel_bounds_checkpoint_or_preserves_raw(endpoint_case, outside):
    from core.backends.base import LanguageInfo

    case = endpoint_case
    task = output_task(case)
    start = 2.6 if outside else 2.14
    segments = [{"start": start, "end": 3.12, "text": "cancelled words",
                 "words": [{"start": start + 0.1, "end": 3.12,
                            "word": "cancelled", "probability": 0.9}]}]
    original = deepcopy(segments)

    class Backend:
        def transcribe_to_segments(self, *args, **kwargs):
            task.cancelled = True
            return segments, LanguageInfo("en", 0.9)

    if outside:
        with pytest.raises(RuntimeError):
            tr._transcribe_via_alt_backend("test", task, None, None, None, backend=Backend())
        assert not cp.checkpoint_path(str(case.audio)).exists()
        records = [json.loads(path.read_text(encoding="utf-8"))
                   for path in cp.partials_dir().glob("*.timing-recovery.json")]
        assert records[-1]["segments"] == original
    else:
        tr._transcribe_via_alt_backend("test", task, None, None, None, backend=Backend())
        checkpoint = cp.load_checkpoint(str(case.audio))
        assert checkpoint["segments"][0]["text"] == "cancelled words"
        assert checkpoint["segments"][0]["end"] <= case.duration
        assert checkpoint["segments"][0]["words"][0]["end"] <= case.duration
        assert checkpoint["last_end_time"] <= case.duration
    assert not case.writes


def test_otranscribe_numeric_timestamp_rounding_stays_inside_audio(endpoint_case, monkeypatch):
    case = endpoint_case
    duration = 39817 / 16000
    with wave.open(str(case.audio), "wb") as source:
        source.setnchannels(1)
        source.setsampwidth(2)
        source.setframerate(16000)
        source.writeframes(b"\0\0" * 39817)
    install_model(monkeypatch, [Segment(2.48855, duration, "late word", [])], duration=duration)
    task = output_task(case)
    task.output_formats = ["otr"]
    tr.transcribe(task)
    body = json.loads(Path(task.output_paths[0]).read_text(encoding="utf-8"))
    timestamps = re.findall(r'data-timestamp="([\d.]+)"', body["text"])
    assert timestamps and all(float(value) <= duration for value in timestamps)
    assert "late word" in body["text"]


@pytest.mark.parametrize("bound", ["missing", None, 2.488])
def test_partial_save_accepts_legacy_task_without_optional_bound(tmp_path, monkeypatch, bound):
    task = SimpleNamespace(file_path=str(tmp_path / "legacy.mp3"))
    if bound != "missing":
        task._audio_end = bound
    segments = [{"start": 2.14, "end": 3.12, "text": "paid completed words"}]
    events = []
    flush, replace = cp._flush_to_disk, tr.os.replace

    def observed_flush(stream):
        flush(stream)
        events.append("durable")

    def observed_replace(source, target):
        assert events == ["durable"]
        replace(source, target)
        events.append("published")

    monkeypatch.setattr(cp, "_flush_to_disk", observed_flush)
    monkeypatch.setattr(tr.os, "replace", observed_replace)
    tr._save_partial_subtitles(task, segments, None)
    output = (tmp_path / "legacy.partial.srt").read_text(encoding="utf-8")
    assert "paid completed words" in output
    assert events == ["durable", "published"]
    assert segments[0]["end"] == (2.488 if bound == 2.488 else 3.12)


def test_legacy_task_checkpoint_without_optional_bound_retains_text(endpoint_case):
    task = output_task(endpoint_case)
    del task._audio_end
    segments = [{"start": 0.2, "end": 3.12, "text": "saved legacy words"}]
    tr._write_periodic_checkpoint(task, segments, 3.12, "en", 0.9, None)
    saved = cp.load_checkpoint(task.file_path)
    assert saved is not None
    assert saved["segments"] == segments
    assert "audio_end" not in saved
