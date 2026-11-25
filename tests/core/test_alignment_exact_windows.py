"""Exercise fallback bounds through installed sequential and batched callers."""
from collections import namedtuple
from types import SimpleNamespace

import faster_whisper.transcribe as fw
import numpy as np
import pytest

from core import vad_window
from core.backends import faster_whisper_be as be
from tests.core.test_word_timing_safety import model_for_loop


def test_late_tokens_do_not_decode_the_emitted_tail_again(monkeypatch):
    model, tokenizer, options = model_for_loop(be.WhisperModel, monkeypatch, windows=2)
    seeks = []
    tokenizer.decode = lambda tokens: "".join({1: " first", 2: " late", 3: " next"}[t] for t in tokens)

    def split(**kw):
        seeks.append(kw["seek"])
        start = kw["time_offset"]
        rows = ([dict(start=0., end=.5, tokens=[1], seek=0),
                 dict(start=1.1, end=1.2, tokens=[2], seek=0)] if start == 0 else
                [dict(start=start, end=start + 1, tokens=[3], seek=kw["seek"])])
        return rows, kw["seek"] + 100, False

    monkeypatch.setattr(model, "_split_segments_by_timestamps", split)
    monkeypatch.setattr(model, "find_alignment", lambda *a: [])
    result = list(model.generate_segments(np.zeros((80, 201)), tokenizer, options, False))
    assert seeks == [0, 100]
    assert [(s.start, s.end, s.text) for s in result] == [
        (0., 1., " first late"), (1., 2., " next")]
    assert all(not s.words for s in result)


def batched(monkeypatch, metadata, *, valid_first=False):
    model, tokenizer, options = model_for_loop(be.WhisperModel, monkeypatch)
    options.temperatures = [0.]
    pipeline = be.BatchedInferencePipeline(model)
    monkeypatch.setattr(pipeline, "generate_segment_batched", lambda *a: (
        None, [dict(tokens=[1, 2], avg_logprob=-.1, no_speech_prob=0.) for _ in metadata]))
    tokenizer.decode = lambda tokens: "".join({1: " first", 2: " late"}[t] for t in tokens)

    def split(**kw):
        start = kw["time_offset"]
        return [dict(start=start + .1, end=start + .5, tokens=[1]),
                dict(start=start + 1.34, end=start + 2., tokens=[2])], 0, False

    monkeypatch.setattr(model, "_split_segments_by_timestamps", split)

    def align(self, groups, *args):
        for i, group in enumerate(groups):
            if i == 0 and valid_first:
                for row in group:
                    row["words"] = [dict(start=row["start"], end=row["end"], word=" kept", probability=.9)]
            else:
                for row in group:
                    row.update(end=row["start"], words=[])
        return 0.

    monkeypatch.setattr(be._WhisperModel, "add_word_timestamps", align)
    return pipeline, tokenizer, options


def test_batched_fallback_uses_unrounded_chunk_end(monkeypatch):
    metadata = [dict(offset=598.96, duration=1.04)]
    pipeline, tokenizer, options = batched(monkeypatch, metadata)
    group = pipeline.forward(None, tokenizer, metadata, options)[0]
    assert len(group) == 1 and group[0]["tokens"] == [1, 2]
    assert (group[0]["start"], group[0]["end"]) == pytest.approx((599.06, 600.))
    from core import transcriber
    # The normal completion guard still rejects timings beyond physical EOF.
    from types import SimpleNamespace
    rows = [dict(group[0])]
    transcriber._enforce_audio_end(SimpleNamespace(_audio_end=600.), rows)
    assert rows[0]["end"] == 600.


def test_all_late_batched_tokens_start_at_exact_offset(monkeypatch):
    metadata = [dict(offset=12.345, duration=.104)]
    pipeline, tokenizer, options = batched(monkeypatch, metadata)
    monkeypatch.setattr(pipeline.model, "_split_segments_by_timestamps", lambda **kw:
        ([dict(start=14., end=15., tokens=[1, 2])], 0, False))
    row = pipeline.forward(None, tokenizer, metadata, options)[0][0]
    assert (row["start"], row["end"]) == pytest.approx((12.345, 12.449))
    assert row["tokens"] == [1, 2]


def test_batched_groups_keep_valid_alignment_and_their_own_window(monkeypatch):
    metadata = [dict(offset=0., duration=2.), dict(offset=3.456, duration=1.04)]
    pipeline, tokenizer, options = batched(monkeypatch, metadata, valid_first=True)
    groups = pipeline.forward(None, tokenizer, metadata, options)
    assert [row["tokens"] for row in groups[0]] == [[1], [2]]
    assert all(row["words"] for row in groups[0])
    assert len(groups[1]) == 1 and groups[1][0]["tokens"] == [1, 2]
    assert groups[1][0]["end"] == pytest.approx(4.496)
    assert not groups[1][0]["words"]


@pytest.mark.parametrize("frames,rate,seek", [
    (True, 100, 0), (0, 100, 0), (-1, 100, 0), (float("nan"), 100, 0),
    (100, False, 0), (100, 0, 0), (100, 100, True), (100, 100, -1),
])
def test_invalid_frame_metadata_does_not_invent_bounds(frames, rate, seek):
    original = [(dict(seek=seek), 2., 4.)]
    assert be._alignment_window(original, frames, rate) is None


def test_mixed_seek_metadata_is_rejected():
    assert be._alignment_window([(dict(seek=0), 0., 1.), (dict(seek=100), 1., 2.)], 200, 100) is None


def test_vad_merged_chunk_restores_original_timeline_after_fallback(monkeypatch):
    from faster_whisper.vad import collect_chunks
    from faster_whisper.transcribe import restore_speech_timestamps

    chunks = [dict(start=16000, end=24000), dict(start=48000, end=56640)]
    _, metadata = collect_chunks(np.zeros(56640, dtype=np.float32), chunks, 16000, 30.)
    assert metadata[0]["offset"] == 0. and metadata[0]["duration"] == 1.04
    pipeline, tokenizer, options = batched(monkeypatch, metadata)
    decoded = pipeline._batched_segments_generator([None], tokenizer, metadata, 1, options, False)
    rows = list(restore_speech_timestamps(decoded, chunks, 16000))
    assert len(rows) == 1 and rows[0].text == " first late"
    assert (rows[0].start, rows[0].end) == pytest.approx((1.1, 3.54))
    assert not rows[0].words


def _vad_cue(start, end, words=None):
    return fw.Segment(id=1, seek=0, start=start, end=end, text=" text", tokens=[1],
                      avg_logprob=-.1, compression_ratio=1., no_speech_prob=0.,
                      words=words, temperature=0.)


def _decode_vad_cue(cue, chunks, pad_ms, *, vad_filter=True):
    def transcribe(_audio, **_options):
        # Upstream captures its VAD map before returning lazy cues.
        return fw.restore_speech_timestamps(iter([cue]), chunks, 16000), None

    runner = SimpleNamespace(transcribe=transcribe)
    decode = be.WhisperDecode(lambda _: runner, lambda: False, lambda *_: None, 0.)
    rows, _ = decode.transcribe(None, vad_filter=vad_filter, vad_parameters={"speech_pad_ms": pad_ms})
    return rows


@pytest.mark.parametrize(
    "pad_ms,raw_end,next_start,aligned,expected_end",
    [
        (400, 1.08, 1020., False, 2.),
        (40, 1.032, 1020., False, 2.),
        (40, 1.08, 1020., False, 1020.08),
        (0, 1.08, 1020., False, 1020.08),
        (400, 1.24, 1020., False, 1020.24),
        (400, 1.08, 2., False, 2.08),
        (400, 1.08, 1020., True, 1020.08),
    ],
)
def test_vad_cue_end_does_not_jump_across_removed_silence(
    pad_ms, raw_end, next_start, aligned, expected_end,
):
    rate = 16000
    chunks = [dict(start=rate, end=2 * rate),
              dict(start=round(next_start * rate), end=round((next_start + 1) * rate))]
    words = [fw.Word(1.04, raw_end, " next", .9)] if aligned else []
    result, = _decode_vad_cue(_vad_cue(.2, raw_end, words), chunks, pad_ms)
    assert result.text == " text"
    assert result.start == pytest.approx(next_start + .04 if aligned else 1.2)
    assert result.end == pytest.approx(expected_end)


def test_vad_cue_guard_preserves_positive_duration_after_restoration_rounding():
    chunks = [dict(start=16000, end=33024), dict(start=16320000, end=16336000)]
    result, = _decode_vad_cue(_vad_cue(1.06, 1.08), chunks, 400)
    assert (result.start, result.end) == pytest.approx((2.06, 1020.02))


@pytest.mark.parametrize("end", [1.375, 1.37501])
def test_vad_cue_end_already_mapped_to_preceding_chunk_keeps_its_time(end):
    chunks = [dict(start=0, end=22000), dict(start=160000, end=176000)]
    cue = _vad_cue(.2, end)
    cue._decode_window_end = 1.375
    result, = _decode_vad_cue(cue, chunks, 343)
    assert (result.start, result.end) == pytest.approx((.2, 1.38))
    assert be.segment_decode_end(result, result.end) == pytest.approx(1.375)


def test_vad_cue_guard_corrects_exact_end_with_legacy_timestamp_map():
    chunks = [dict(start=0, end=22000), dict(start=160000, end=176000)]

    class LegacyTimestampsMap(fw.SpeechTimestampsMap):
        def get_original_time(self, time, chunk_index=None):
            return super().get_original_time(time, chunk_index)

    timestamps = LegacyTimestampsMap(chunks, 16000)
    result, = vad_window._clamp_cue_bounds([_vad_cue(.2, 1.375)], chunks, timestamps, 343)
    assert timestamps.get_original_time(result.end) == pytest.approx(1.37)


def test_vad_cue_start_stays_with_following_chunk_on_catalina_fixture():
    chunks = [
        dict(start=76032, end=147712),
        dict(start=16315648, end=16392448),
        dict(start=32635648, end=32713984),
        dict(start=48955648, end=49029888),
        dict(start=57454848, end=57526528),
    ]
    result, = _decode_vad_cue(_vad_cue(18.72, 23.2), chunks, 400)
    assert (result.start, result.end) == pytest.approx((3590.93, 3595.31))


@pytest.mark.parametrize(
    "pad_ms,raw_start,raw_end,next_start,aligned,expected",
    [
        (400, .904, 1.7, 1020., False, (1020., 1020.7)),
        (40, .904, 1.7, 1020., False, (1.90, 1020.7)),
        (0, .904, 1.7, 1020., False, (1.90, 1020.7)),
        (400, .8, 1.7, 1020., False, (1.8, 1020.7)),
        (400, .904, 1.7, 2., False, (1.90, 2.7)),
        (400, .904, 1.08, 1020., False, (1.90, 2.)),
        (400, .904, 1.2, 1020., False, (1.90, 1020.2)),
        (400, .904, 1.7, 1020., True, (1020.04, 1020.7)),
        (400, .904, 2., 1020., False, (1.90, 1021.)),
        (400, .904, 2.08, 1020., False, (1020., 1021.)),
        (400, .904, 2.7, 1020., False, (1.90, 2040.7)),
    ],
)
def test_vad_cue_start_guard_only_moves_unaligned_cues_into_the_next_chunk(
    pad_ms, raw_start, raw_end, next_start, aligned, expected,
):
    rate = 16000
    chunks = [dict(start=rate, end=2 * rate),
              dict(start=round(next_start * rate), end=round((next_start + 1) * rate)),
              dict(start=2040 * rate, end=2041 * rate)]
    words = [fw.Word(1.04, raw_end, " next", .9)] if aligned else []
    result, = _decode_vad_cue(_vad_cue(raw_start, raw_end, words), chunks, pad_ms)
    assert result.text == " text"
    assert (result.start, result.end) == pytest.approx(expected)


def test_vad_cue_start_guard_uses_sample_precision_for_an_exact_end():
    chunks = [dict(start=16000, end=514688), dict(start=16320000, end=16335872)]
    # The compressed end is sample 514560, but multiplication rounds below it.
    result, = _decode_vad_cue(_vad_cue(31.08, 32.16), chunks, 400)
    assert (result.start, result.end) == pytest.approx((32.08, 1020.99))


def test_vad_cue_guard_isolates_lazy_decodes():
    chunks = [dict(start=16000, end=32000), dict(start=16320000, end=16336000)]
    padded = _decode_vad_cue(_vad_cue(.2, 1.08), chunks, 400)
    disabled = _decode_vad_cue(_vad_cue(.2, 1.08), chunks, 400, vad_filter=False)
    assert next(disabled).end == pytest.approx(1020.08)
    assert next(padded).end == pytest.approx(2.)
    outside = fw.restore_speech_timestamps(iter([_vad_cue(.2, 1.08)]), chunks, 16000)
    assert next(outside).end == pytest.approx(1020.08)


@pytest.mark.parametrize("edges,expected", [
    ((.2, 1.08), (1.2, 2.)),
    ((.904, 1.7), (1020., 1020.7)),
])
def test_vad_cue_guard_supports_immutable_legacy_segments(edges, expected):
    cue_type = namedtuple("LegacyCue", "start end text words")
    cue = cue_type(*edges, " text", None)
    chunks = [dict(start=16000, end=32000), dict(start=16320000, end=16336000)]
    timestamps = fw.SpeechTimestampsMap(chunks, 16000)
    result, = vad_window._clamp_cue_bounds(iter([cue]), chunks, timestamps, 100.)
    assert (cue.start, cue.end) == edges
    assert result.text == cue.text
    restored = (timestamps.get_original_time(result.start), timestamps.get_original_time(result.end))
    assert restored == pytest.approx(expected)


@pytest.mark.parametrize("error", [False, True])
def test_batch_context_is_restored_after_return_or_error(monkeypatch, error):
    metadata = [dict(offset=12.345, duration=.104)]
    pipeline, tokenizer, options = batched(monkeypatch, metadata)
    if error:
        monkeypatch.setattr(pipeline, "generate_segment_batched", lambda *a: (_ for _ in ()).throw(RuntimeError("decode failed")))
        with pytest.raises(RuntimeError, match="decode failed"):
            pipeline.forward(None, tokenizer, metadata, options)
    else:
        pipeline.forward(None, tokenizer, metadata, options)
    group = [dict(seek=0, start=.1, end=.5, tokens=[1]),
             dict(seek=0, start=1.34, end=2., tokens=[2])]
    pipeline.model.add_word_timestamps([group], tokenizer, None, 200, "", "", 0.)
    assert [(r["start"], r["end"]) for r in group] == [(.1, .5), (1.34, 2.)]


def test_concurrent_models_use_their_own_exact_chunk_bounds(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    short_meta = [dict(offset=12.345, duration=.104)]
    long_meta = [dict(offset=23.456, duration=1.04)]
    short, tokenizer, options = batched(monkeypatch, short_meta)
    long, _, _ = batched(monkeypatch, long_meta)
    barrier = Barrier(2, timeout=5)

    def unusable(self, groups, *a):
        barrier.wait()
        for group in groups:
            for row in group:
                row.update(end=row["start"], words=[])
        return 0.

    monkeypatch.setattr(be._WhisperModel, "add_word_timestamps", unusable)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(short.forward, None, tokenizer, short_meta, options)
        b = pool.submit(long.forward, None, tokenizer, long_meta, options)
        first, second = a.result()[0], b.result()[0]
    assert len(first) == len(second) == 1
    assert (first[0]["start"], first[0]["end"]) == pytest.approx((12.445, 12.449))
    assert (second[0]["start"], second[0]["end"]) == pytest.approx((23.556, 24.496))
    assert first[0]["tokens"] == second[0]["tokens"] == [1, 2]


@pytest.mark.parametrize("chunk", [dict(offset=True, duration=1), dict(offset=0, duration=0),
                                  dict(offset=0, duration=float("nan")), dict(offset=-1, duration=2)])
def test_invalid_exact_chunk_metadata_is_rejected(chunk):
    assert be._chunk_window(chunk) is None


def test_older_wheel_without_batched_pipeline_still_imports(monkeypatch):
    import builtins
    import importlib.util

    original = builtins.__import__

    def legacy_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "faster_whisper" and "BatchedInferencePipeline" in fromlist:
            raise ImportError("older wheel has no batched pipeline")
        return original(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", legacy_import)
    spec = importlib.util.spec_from_file_location("core.backends._legacy_alignment", be.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.BatchedInferencePipeline is None
    assert issubclass(module.WhisperModel, be._WhisperModel)
