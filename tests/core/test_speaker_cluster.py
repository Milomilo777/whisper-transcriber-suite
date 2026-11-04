"""Spectral speaker labels: structural controls, attacks, and worker fallback.

No real models, audio files, large fixtures, or GUI windows are needed.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from core import diarization as diar, speaker_cluster as cluster
from tests.core.test_diarize_crash import fake_worker  # noqa: F401 - fixture


def blobs(counts, *, dim=64, noise=0.15, seed=1):
    rng = np.random.default_rng(seed)
    centers = rng.normal(size=(len(counts), dim))
    vectors = np.vstack([c + noise * rng.normal(size=(n, dim))
                         for c, n in zip(centers, counts)])
    return vectors, np.repeat(np.arange(len(counts)), counts)


def purity(labels, truth):
    return sum(np.bincount(truth[labels == label]).max()
               for label in np.unique(labels)) / len(truth)


@pytest.mark.parametrize("counts", [[60, 60], [90, 60, 30], [60] * 4, [380, 20], [30] * 12])
def test_known_structure_is_found_including_minority_and_twelve_voices(counts):
    vectors, truth = blobs(counts)
    labels, k, _ = cluster.spectral(vectors)
    assert k == len(counts)
    assert len(np.unique(labels)) == k
    assert purity(labels, truth) > 0.99


def test_single_voice_does_not_invent_speakers():
    vectors, _ = blobs([160], noise=0.3)
    labels, k, _ = cluster.spectral(vectors)
    assert k == 1
    assert np.array_equal(labels, np.zeros(160))


@pytest.mark.parametrize("n", [1, 2, 5, 6, 12, 64])
def test_one_two_fewer_than_neighbours_and_identical_vectors(n):
    labels, k, _ = cluster.spectral(np.ones((n, 8)))
    assert k == 1
    assert labels.tolist() == [0] * n


@pytest.mark.parametrize("value", [0.0, np.nan, np.inf])
def test_invalid_embeddings_are_rejected(value):
    with pytest.raises(ValueError):
        cluster.spectral(np.full((16, 8), value))


def test_empty_input_has_no_invented_labels():
    labels, k, _ = cluster.spectral(np.empty((0, 8)))
    assert k == 0 and len(labels) == 0
    assert cluster.cluster_turns([], np.empty((0, 8)), np.empty((0, 2)), np.array([], dtype=int)) == []


def test_window_plan_keeps_boundaries_and_is_independent_of_turn_order():
    turns = [(4.0, 6.1), (0.0, 0.25), (1.0, 1.249), (2.0, 3.5)]
    windows = list(cluster.windows_from_turns(turns))
    assert [(w.turn_id, w.start, w.end) for w in windows] == [
        (1, 0.0, 0.25), (3, 2.0, 3.5), (0, 4.0, 5.5), (0, 4.75, 6.1),
    ]
    assert turns == [(4.0, 6.1), (0.0, 0.25), (1.0, 1.249), (2.0, 3.5)]


def test_vote_uses_duration_then_nearest_labelled_turn_and_time_ties():
    turns = [(0.0, 3.0), (3.0, 3.1), (4.0, 6.0), (3.4, 3.6)]
    ids = np.array([0, 0, 0, 2])
    spans = np.array([(0, 1.5), (0.75, 2.25), (1.5, 2), (4, 5.5)])
    assert cluster.turns_from_windows(turns, ids, spans, np.array([7, 7, 9, 9])) == [7, 7, 9, 7]
    # A short turn cannot borrow a label from another short turn and bridge a gap.
    assert cluster.turns_from_windows(
        [(0, 1), (1.1, 1.2), (1.3, 1.4), (1.5, 2.5)],
        np.array([0, 3]), np.array([(0, 1), (1.5, 2.5)]), np.array([0, 1]),
    ) == [0, 0, 1, 1]


def test_no_turn_with_a_window_is_an_explicit_failure_for_the_worker_to_catch():
    with pytest.raises(ValueError, match="no speech windows"):
        cluster.cluster_turns([(0, 0.1)], np.empty((0, 8)), np.empty((0, 2)), np.array([], dtype=int))


@pytest.mark.parametrize("cap", [64, cluster.MAX_SPECTRAL_WINDOWS])
def test_turn_and_window_shuffling_preserves_exact_time_label_mapping(cap):
    vectors, _ = blobs([30] * 3)
    turns = [(float(i * 2), float(i * 2 + 1.5)) for i in range(len(vectors))]
    spans, ids = np.array(turns), np.arange(len(turns))
    before = cluster.cluster_turns(turns, vectors, spans, ids, max_windows=cap)
    rng = np.random.default_rng(44)
    turn_order, window_order = rng.permutation(len(turns)), rng.permutation(len(vectors))
    inverse = np.argsort(turn_order)
    after = cluster.cluster_turns(
        [turns[i] for i in turn_order], vectors[window_order], spans[window_order],
        inverse[ids[window_order]], max_windows=cap,
    )
    assert {turns[i]: label for i, label in enumerate(before)} == {
        turns[i]: label for i, label in zip(turn_order, after)
    }


def test_dense_solve_is_bounded_at_and_above_cap(monkeypatch):
    vectors, truth = blobs([120, 120])
    calls = []
    original = cluster._dense_spectral

    def record(x, *args):
        calls.append(len(x))
        return original(x, *args)

    monkeypatch.setattr(cluster, "_dense_spectral", record)
    labels, k, _ = cluster.spectral(vectors, max_windows=64)
    cluster.spectral(vectors[:64], max_windows=64)
    assert calls == [64, 64]
    assert k == 2 and purity(labels, truth) == 1.0


def test_clustering_polls_cancellation_after_the_dense_solve(monkeypatch):
    stopped = threading.Event()
    original = np.linalg.eigh

    def finish_then_cancel(x):
        result = original(x)
        stopped.set()
        return result

    monkeypatch.setattr(np.linalg, "eigh", finish_then_cancel)
    with pytest.raises(cluster.ClusteringCancelled):
        cluster.spectral(np.ones((16, 8)), cancelled=stopped.is_set)


@pytest.fixture
def worker(monkeypatch, tmp_path):
    """In-memory sherpa adapter with real production window/vote code."""
    state = SimpleNamespace(
        turns=[(0.0, 2.0, 0), (2.0, 4.0, 1), (4.0, 6.0, 2)],
        pieces=[], computed=0, extractors=0, fail_at=None, failure=RuntimeError,
        vector=np.ones(8, dtype=np.float32), on_compute=lambda: None,
        after_process=lambda: None, native_configs=[],
        samples=np.arange(6 * 16000, dtype=np.float32) / 100000,
    )
    model = tmp_path / "embedding.onnx"
    model.write_bytes(b"fake model")
    state.model = model

    class Stream:
        finished = False

        def accept_waveform(self, sr, samples):
            assert sr == 16000
            state.pieces.append(samples.copy())

        def input_finished(self):
            self.finished = True

    class Extractor:
        def __init__(self, config):
            state.extractors += 1
            assert config.model == str(model)
            assert config.num_threads == diar.WORKER_THREADS

        def create_stream(self):
            return Stream()

        def compute(self, stream):
            assert stream.finished
            state.computed += 1
            state.on_compute()
            if state.computed == state.fail_at:
                raise state.failure("extractor failed at window N")
            return state.vector.copy()

    class Diarizer:
        def __init__(self, config):
            state.native_configs.append(config)

        def process(self, samples, callback):
            for processed in [1, 4, 2]:
                if callback(processed, 4):
                    break
            state.after_process()
            return SimpleNamespace(sort_by_start_time=lambda: [
                SimpleNamespace(start=s, end=e, speaker=lab) for s, e, lab in state.turns
            ])

    fake = SimpleNamespace(
        OfflineSpeakerDiarizationConfig=lambda **kw: SimpleNamespace(validate=lambda: True, **kw),
        OfflineSpeakerSegmentationModelConfig=lambda **kw: SimpleNamespace(**kw),
        OfflineSpeakerSegmentationPyannoteModelConfig=lambda **kw: SimpleNamespace(**kw),
        SpeakerEmbeddingExtractorConfig=lambda **kw: SimpleNamespace(**kw),
        FastClusteringConfig=lambda **kw: SimpleNamespace(**kw),
        OfflineSpeakerDiarization=Diarizer, SpeakerEmbeddingExtractor=Extractor,
    )
    monkeypatch.setitem(sys.modules, "sherpa_onnx", fake)
    monkeypatch.setattr(diar, "availability_reason", lambda: "")
    monkeypatch.setattr(diar, "_model_path", lambda _name: str(model))
    monkeypatch.setattr(diar, "_prepare_audio_16k_mono", lambda _path: (state.samples, 16000))
    state.sherpa = fake
    return state


def today(state):
    return diar.merge_small_speakers([
        diar.DiarSegment(s, e, f"Speaker {lab:02d}") for s, e, lab in state.turns
    ])


def test_unknown_count_uses_new_labels_and_preserves_every_boundary(worker, monkeypatch):
    monkeypatch.setattr(cluster, "cluster_turns", lambda *args, **kwargs: [0, 1, 0])
    result = diar._diarize_impl("in-memory.wav")
    assert [s.speaker for s in result] == ["Speaker 00", "Speaker 01", "Speaker 00"]
    assert [(s.start, s.end) for s in result] == [(s, e) for s, e, _ in worker.turns]
    assert worker.extractors == 1 and worker.computed > 0


def test_explicit_count_keeps_the_exact_native_path(worker, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("explicit speaker count must not recluster")

    monkeypatch.setattr(cluster, "cluster_turns", forbidden)
    result = diar._diarize_impl("in-memory.wav", num_speakers=3, cluster_threshold=0.42)
    assert [s.speaker for s in result] == [f"Speaker {lab:02d}" for _, _, lab in worker.turns]
    assert worker.extractors == 0
    assert worker.native_configs[0].clustering.num_clusters == 3
    assert worker.native_configs[0].clustering.threshold == 0.42


@pytest.mark.parametrize("failure", [RuntimeError, MemoryError])
def test_extractor_raising_at_window_n_keeps_todays_complete_labels(worker, caplog, failure):
    worker.fail_at, worker.failure = 2, failure
    result = diar._diarize_impl("in-memory.wav")
    assert result == today(worker)
    assert worker.computed == 2
    assert "retaining existing speaker labels" in caplog.text


def test_extractor_initialization_failure_falls_back(worker, caplog):
    def fail(config):
        raise OSError("extractor cannot initialize")

    worker.sherpa.SpeakerEmbeddingExtractor = fail
    assert diar._diarize_impl("in-memory.wav") == today(worker)
    assert "retaining existing speaker labels" in caplog.text


@pytest.mark.parametrize("failure", [MemoryError, ValueError, np.linalg.LinAlgError])
def test_clustering_failure_keeps_todays_complete_labels(worker, monkeypatch, caplog, failure):
    def fail(*args, **kwargs):
        raise failure("clustering failed")

    monkeypatch.setattr(cluster, "cluster_turns", fail)
    assert diar._diarize_impl("in-memory.wav") == today(worker)
    assert worker.computed > 0
    assert "retaining existing speaker labels" in caplog.text


@pytest.mark.parametrize("value", [0.0, np.nan])
def test_invalid_extractor_output_keeps_existing_labels(worker, caplog, value):
    worker.vector[:] = value
    assert diar._diarize_impl("in-memory.wav") == today(worker)
    assert "retaining existing speaker labels" in caplog.text


def test_model_disappearing_after_native_diarization_keeps_its_labels(worker, caplog):
    worker.after_process = worker.model.unlink
    assert diar._diarize_impl("in-memory.wav") == today(worker)
    assert worker.extractors == 0
    assert "retaining existing speaker labels" in caplog.text


def test_no_usable_windows_keeps_existing_labels(worker, caplog):
    worker.turns = [(0, 0.1, 0), (1, 1.1, 1)]
    assert diar._diarize_impl("in-memory.wav") == today(worker)
    assert "retaining existing speaker labels" in caplog.text


def test_short_window_uses_circular_padding_and_short_turn_keeps_boundaries(worker):
    worker.turns = [(0, 0.25, 0), (0.25, 0.35, 1), (1, 2, 2)]
    result = diar._diarize_impl("in-memory.wav")
    assert worker.computed == 2
    assert all(len(piece) == 24000 for piece in worker.pieces)
    assert np.array_equal(worker.pieces[0], np.resize(worker.samples[:4000], 24000))
    assert [(s.start, s.end) for s in result] == [(s, e) for s, e, _ in worker.turns]


def test_cancellation_between_windows_stops_extraction_promptly(worker):
    stopped = threading.Event()

    def cancel_after_second():
        if worker.computed == 2:
            stopped.set()

    worker.on_compute = cancel_after_second
    assert diar._diarize_impl("in-memory.wav", cancelled=stopped.is_set) == []
    assert worker.computed == 2


def test_unknown_progress_is_monotonic_and_heartbeat_survives_the_solve(worker, monkeypatch):
    fractions, heartbeat = [], threading.Event()

    def report(fraction):
        fractions.append(fraction)
        if threading.current_thread().name == "speaker-cluster-heartbeat":
            heartbeat.set()

    def slow_cluster(*args, progress_cb, **kwargs):
        assert fractions[-1] < 1.0
        assert heartbeat.wait(2.0)
        progress_cb(0.5)
        return [0, 1, 0]

    monkeypatch.setattr(diar, "SEGMENTATION_HEARTBEAT_S", 0.01)
    monkeypatch.setattr(cluster, "cluster_turns", slow_cluster)
    result = diar._diarize_impl("in-memory.wav", progress_cb=report)
    assert len(result) == 3
    assert fractions == sorted(fractions)
    assert fractions[-1] == 1.0
    assert heartbeat.is_set()
    assert not any(t.name == "speaker-cluster-heartbeat" for t in threading.enumerate())


def test_legacy_result_is_published_before_any_new_extraction(worker):
    published = []

    def check_published():
        assert published == [today(worker)]

    worker.on_compute = check_published
    assert diar._diarize_impl("in-memory.wav", fallback_cb=published.append)
    assert worker.computed > 0


@pytest.mark.parametrize("failure", ["crash", "error", "stall", "timeout"])
def test_new_step_native_failure_keeps_the_legacy_result_in_the_parent(fake_worker, monkeypatch, caplog, failure):
    actions = {
        "crash": ("if os.name == 'nt':\n    import ctypes\n"
                  "    ctypes.windll.kernel32.ExitProcess(0xC0000005)\nos._exit(42)"),
        "error": "emit({'event': 'error', 'error': 'native extractor failed'})\ntime.sleep(30)",
        "stall": "time.sleep(30)",
        "timeout": "while True:\n    emit({'event': 'progress', 'fraction': 0.8})\n    time.sleep(0.05)",
    }
    started = fake_worker(
        "emit({'event': 'fallback', 'segments': [{'start': 0, 'end': 2, 'speaker': 'Speaker 07'}]})\n"
        "emit({'event': 'progress', 'fraction': 0.75})\n" + actions[failure]
    )
    monkeypatch.setattr(diar, "WORKER_STALL_TIMEOUT_S", 0.3)
    monkeypatch.setattr(diar, "WORKER_MIN_TIMEOUT_S", 0.8)
    monkeypatch.setattr("core.transcriber.get_duration", lambda path: 0.01)
    assert diar.diarize("in-memory.wav") == [diar.DiarSegment(0, 2, "Speaker 07")]
    assert started[-1].poll() is not None
    assert "retaining existing speaker labels" in caplog.text


def test_parent_cancellation_after_fallback_does_not_return_labels(fake_worker):
    stopped = threading.Event()
    started = fake_worker("""
        emit({'event': 'fallback', 'segments': [{'start': 0, 'end': 2, 'speaker': 'Speaker 07'}]})
        emit({'event': 'progress', 'fraction': 0.75})
        time.sleep(30)
    """)
    assert diar.diarize(
        "in-memory.wav", progress_cb=lambda fraction: stopped.set(), cancelled=stopped.is_set,
    ) == []
    assert started[-1].poll() is not None


def test_final_new_labels_take_precedence_over_the_published_fallback(fake_worker):
    fake_worker("""
        emit({'event': 'fallback', 'segments': [{'start': 0, 'end': 2, 'speaker': 'Speaker 07'}]})
        emit({'event': 'done', 'segments': [{'start': 0, 'end': 2, 'speaker': 'Speaker 00'}]})
    """)
    assert diar.diarize("in-memory.wav") == [diar.DiarSegment(0, 2, "Speaker 00")]


def test_worker_main_publishes_fallback_before_done(monkeypatch, capsys):
    from core import diarization_worker
    import io
    import json

    def impl(path, *, fallback_cb, **kwargs):
        fallback_cb([diar.DiarSegment(0, 2, "Speaker 07")])
        return [diar.DiarSegment(0, 2, "Speaker 00")]

    monkeypatch.setitem(sys.modules, "sherpa_onnx", object())
    monkeypatch.setattr(diar, "_diarize_impl", impl)
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"audio_path": "in-memory.wav"}\n'))
    assert diarization_worker.main() == 0
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [ev["event"] for ev in events] == ["fallback", "done"]


def test_unresolved_eigengap_is_not_a_one_speaker_decision():
    vectors, _ = blobs([30] * 20)
    for _ in range(2):
        with pytest.raises(ValueError, match="no resolved eigengap"):
            cluster.spectral(vectors)


def test_twenty_voice_extractor_result_falls_back_instead_of_collapsing(worker, caplog):
    vectors, _ = blobs([30] * 20)
    # Coincident turns let this structural fixture reuse a tiny decoded array.
    # The mock extractor, rather than audio content, supplies the 20 voices.
    worker.turns = [(0.0, 1.5, i // 30) for i in range(len(vectors))]

    def next_vector():
        worker.vector = vectors[worker.computed - 1].astype(np.float32)

    worker.on_compute = next_vector
    assert diar._diarize_impl("in-memory.wav") == today(worker)
    assert worker.computed == 600
    assert "no resolved eigengap" in caplog.text


@pytest.mark.parametrize("failure", ["callback", "malformed_result"])
def test_parent_delivery_failure_after_fallback_keeps_legacy_labels(fake_worker, caplog, failure):
    action = ("emit({'event': 'progress', 'fraction': 0.8})" if failure == "callback" else
              "emit({'event': 'done', 'segments': [{'start': 'soon', 'end': 2, 'speaker': 'Speaker 00'}]})")
    started = fake_worker(
        "emit({'event': 'fallback', 'segments': [{'start': 0, 'end': 2, 'speaker': 'Speaker 07'}]})\n"
        + action + "\ntime.sleep(30)"
    )

    def broken_callback(fraction):
        raise RuntimeError("progress delivery failed")

    assert diar.diarize(
        "in-memory.wav", progress_cb=broken_callback if failure == "callback" else None,
    ) == [diar.DiarSegment(0, 2, "Speaker 07")]
    assert started[-1].poll() is not None
    assert "retaining existing speaker labels" in caplog.text


def test_cancellation_wins_over_a_delivery_exception_after_fallback(fake_worker):
    stopped = threading.Event()
    fake_worker("""
        emit({'event': 'fallback', 'segments': [{'start': 0, 'end': 2, 'speaker': 'Speaker 07'}]})
        emit({'event': 'progress', 'fraction': 0.8})
        time.sleep(30)
    """)

    def broken_callback(fraction):
        stopped.set()
        raise RuntimeError("progress delivery failed during cancellation")

    assert diar.diarize("in-memory.wav", progress_cb=broken_callback, cancelled=stopped.is_set) == []


@pytest.mark.parametrize("failure", [None, RuntimeError, MemoryError])
def test_captured_failure_logs_do_not_retain_decoded_audio(worker, monkeypatch, caplog, failure):
    import weakref

    refs = []

    def prepare(path):
        samples = worker.samples.copy()
        refs.append(weakref.ref(samples))
        return samples, 16000

    monkeypatch.setattr(diar, "_prepare_audio_16k_mono", prepare)
    if failure is not None:
        worker.fail_at, worker.failure = 2, failure
    assert diar._diarize_impl("in-memory.wav")
    assert refs[0]() is None


def test_unprintable_extractor_exception_still_retains_labels(worker, caplog):
    class Unprintable(RuntimeError):
        def __str__(self):
            raise ValueError("exception formatting failed")

    worker.fail_at, worker.failure = 2, Unprintable
    assert diar._diarize_impl("in-memory.wav") == today(worker)
    assert "Unprintable" in caplog.text


def test_empty_sampled_cluster_does_not_warn_or_hijack_unsampled_windows(recwarn):
    edges = [
        (6, 8), (4, 7), (9, 1), (9, 7), (5, 1), (9, 0),
        (3, 2), (6, 4), (10, 2), (11, 6), (1, 2), (5, 3),
    ]
    sampled = np.zeros((12, len(edges)))
    for col, (u, v) in enumerate(edges):
        sampled[[u, v], col] = 1.0
    sample_ids = np.linspace(0, 13, 12, dtype=np.int64)
    vectors = np.zeros((14, len(edges)))
    vectors[sample_ids] = sampled
    vectors[[6, 12]] = sampled[:2]
    labels, k, _ = cluster.spectral(vectors, max_windows=12)
    warnings_seen = [str(w.message) for w in recwarn]
    assert warnings_seen == [] and k == 4, (
        f"warnings={warnings_seen}, k={k}, sampled_unique={np.unique(labels[sample_ids]).tolist()}, "
        f"unsampled={labels[[6, 12]].tolist()}"
    )
    assert np.unique(labels[sample_ids]).tolist() == [0, 1, 2, 3]
    assert np.unique(labels).tolist() == [0, 1, 2, 3]
    assert labels[[6, 12]].tolist() == labels[sample_ids[:2]].tolist()


def test_tunable_neighbour_cap_and_edge_similarity_keep_legacy_mode(monkeypatch):
    assert cluster._MAX_NEIGHBOURS == 90
    assert cluster._MIN_EDGE_SIMILARITY == 0.3
    vectors, truth = blobs([580, 580, 7, 7])
    vectors = vectors + 0.35
    labels, k, evals = cluster.spectral(vectors)
    assert k == 4 and purity(labels, truth) == 1.0
    assert float(evals[3]) < 1e-12

    # Legacy reference: keep = min(n - 1, max(6, round(p * n))), no similarity floor.
    x = cluster._embeddings(vectors)
    n = len(x)
    sim = x @ x.T
    np.fill_diagonal(sim, 0)
    keep = min(n - 1, max(6, int(round(0.03 * n))))
    thresh = np.partition(sim, n - keep, axis=1)[:, n - keep, None]
    weights = np.where(sim >= thresh, np.maximum(sim, 0), 0.0)
    adj = 0.5 * (weights + weights.T)
    deg = np.maximum(adj.sum(1), 1e-9) ** -0.5
    lap = np.eye(n) - deg[:, None] * adj * deg[None, :]
    ref_evals, ref_evecs = np.linalg.eigh(0.5 * (lap + lap.T))
    ref_leading = ref_evals[:13]
    ref_k = int(np.argmax(np.diff(ref_leading))) + 1
    ref_labels = cluster._kmeans(cluster._normalise(ref_evecs[:, :ref_k]), ref_k, None)

    monkeypatch.setattr(cluster, "_MAX_NEIGHBOURS", n)
    monkeypatch.setattr(cluster, "_MIN_EDGE_SIMILARITY", -1.0)
    leg_labels, leg_k, leg_evals = cluster.spectral(vectors)
    assert leg_k == ref_k
    assert np.array_equal(leg_labels, ref_labels)
    assert np.allclose(leg_evals, ref_leading)
    assert float(leg_evals[3]) > 0.3


@pytest.mark.parametrize("case", ["queued_before_timeout", "flushed_before_exit"])
def test_queued_or_flushed_events_win_over_timeout_and_worker_exit(fake_worker, monkeypatch, case):
    import time

    monkeypatch.setattr("core.transcriber.get_duration", lambda path: 0.01)
    if case == "queued_before_timeout":
        monkeypatch.setattr(diar, "WORKER_MIN_TIMEOUT_S", 0.05)
        fake_worker("""
            emit({'event': 'progress', 'fraction': 0.5})
            emit({'event': 'fallback', 'segments': [{'start': 0, 'end': 2, 'speaker': 'Speaker 07'}]})
            emit({'event': 'done', 'segments': [{'start': 0, 'end': 2, 'speaker': 'Speaker 00'}]})
        """)
        result = diar.diarize("in-memory.wav", progress_cb=lambda _f: time.sleep(0.12))
        assert result == [diar.DiarSegment(0, 2, "Speaker 00")]
    else:
        monkeypatch.setattr(diar, "WORKER_MIN_TIMEOUT_S", 0.05)
        fake_worker("""
            emit({'event': 'progress', 'fraction': 0.5})
            emit({'event': 'fallback', 'segments': [{'start': 0, 'end': 2, 'speaker': 'Speaker 07'}]})
            time.sleep(30)
        """)
        result = diar.diarize("in-memory.wav", progress_cb=lambda _f: time.sleep(0.12))
        assert result == [diar.DiarSegment(0, 2, "Speaker 07")]


def test_hung_window_extraction_hits_stall_limit_not_masked_by_heartbeat(fake_worker, monkeypatch, caplog):
    monkeypatch.setenv("PYTHONPATH", str(Path(diar.__file__).resolve().parents[1]))
    started = fake_worker("""
        from types import SimpleNamespace
        import numpy as np
        from core import diarization as diar

        diar.SEGMENTATION_HEARTBEAT_S = 0.05
        diar.availability_reason = lambda: ""
        diar._model_path = lambda _name: diar.__file__
        diar._prepare_audio_16k_mono = lambda _path: (np.ones(32000, dtype=np.float32), 16000)

        class Stream:
            def accept_waveform(self, sr, piece): pass
            def input_finished(self): pass

        class Extractor:
            def __init__(self, cfg): pass
            def create_stream(self): return Stream()
            def compute(self, stream):
                time.sleep(30)
                return np.ones(8, dtype=np.float32)

        class Diarizer:
            def __init__(self, cfg): pass
            def process(self, samples, callback):
                callback(4, 4)
                return SimpleNamespace(sort_by_start_time=lambda: [
                    SimpleNamespace(start=0.0, end=2.0, speaker=7)
                ])

        sys.modules["sherpa_onnx"] = SimpleNamespace(
            OfflineSpeakerDiarizationConfig=lambda **kw: SimpleNamespace(validate=lambda: True, **kw),
            OfflineSpeakerSegmentationModelConfig=lambda **kw: SimpleNamespace(**kw),
            OfflineSpeakerSegmentationPyannoteModelConfig=lambda **kw: SimpleNamespace(**kw),
            SpeakerEmbeddingExtractorConfig=lambda **kw: SimpleNamespace(**kw),
            FastClusteringConfig=lambda **kw: SimpleNamespace(**kw),
            OfflineSpeakerDiarization=Diarizer,
            SpeakerEmbeddingExtractor=Extractor,
        )
        diar._diarize_impl(
            "in-memory.wav",
            progress_cb=lambda f: emit({"event": "progress", "fraction": float(f)}),
            fallback_cb=lambda turns: emit({"event": "fallback", "segments": [
                {"start": s.start, "end": s.end, "speaker": s.speaker} for s in turns
            ]}),
        )
    """)
    monkeypatch.setattr(diar, "WORKER_STALL_TIMEOUT_S", 0.25)
    monkeypatch.setattr(diar, "WORKER_MIN_TIMEOUT_S", 0.9)
    monkeypatch.setattr("core.transcriber.get_duration", lambda path: 0.01)
    assert diar.diarize("in-memory.wav") == [diar.DiarSegment(0, 2, "Speaker 07")]
    assert started[-1].poll() is not None
    assert "made no progress" in caplog.text, f"expected stall log, got: {caplog.text!r}"


def test_float32_duplicates_and_coincident_turn_tie_break_are_permutation_invariant():
    x_dup = np.ones((100, 192), dtype=np.float32)
    labels, k, _ = cluster.spectral(x_dup)
    assert k == 1, f"expected k=1 for 100 identical float32 vectors, got k={k}"
    assert labels.tolist() == [0] * 100

    turns_dup = [(0.0, 1.5)] * 100
    spans_dup = np.tile([[0.0, 1.5]], (100, 1))
    ids_dup = np.arange(100)
    rng = np.random.default_rng(7)
    perm = rng.permutation(100)
    assert cluster.cluster_turns(turns_dup, x_dup, spans_dup, ids_dup) == [0] * 100
    assert cluster.cluster_turns(
        turns_dup, x_dup[perm], spans_dup[perm], ids_dup[perm],
    ) == [0] * 100

    # Coincident turns with an identical window vector at (0.0, 1.5) and a
    # second window on turn 1: turn_id must break the exact (turn, span, bytes)
    # tie when max_windows subsamples the ordered windows.
    v0, v1 = blobs([20, 20], dim=16, seed=3)[0][:20], blobs([20, 20], dim=16, seed=3)[0][20:]
    turns = [(0.0, 2.25), (0.0, 2.25)] + [(float(i + 3), float(i + 4.5)) for i in range(38)]
    shared = v0[0].copy()
    vecs = np.vstack([shared, shared, v1[0], v0[1:20], v1[1:20]]).astype(np.float32)
    spans = np.array(
        [(0.0, 1.5), (0.0, 1.5), (0.75, 2.25)]
        + [(float(i + 3), float(i + 4.5)) for i in range(38)]
    )
    ids = np.array([0, 1, 1] + list(range(2, 40)))
    base = cluster.cluster_turns(turns, vecs, spans, ids, max_windows=20)
    for seed in range(10):
        p = np.random.default_rng(seed).permutation(len(vecs))
        assert cluster.cluster_turns(turns, vecs[p], spans[p], ids[p], max_windows=20) == base


def test_two_windows_orthogonal_and_similar_do_not_raise():
    labels_orth, k_orth, _ = cluster.spectral(np.eye(2, 8, dtype=np.float32))
    assert k_orth == 2
    assert labels_orth.tolist() == [0, 1]

    labels_same, k_same, _ = cluster.spectral(np.ones((2, 8), dtype=np.float32))
    assert k_same == 1
    assert labels_same.tolist() == [0, 0]


def test_laplacian_temporaries_reduce_peak_memory_with_bit_identical_labels():
    import tracemalloc

    vectors, _ = blobs([500] * 4, dim=64, noise=0.15, seed=1)
    x = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    n = len(x)
    sim = x @ x.T
    np.fill_diagonal(sim, 0)
    keep = min(n - 1, max(6, int(round(0.03 * n))))
    thresh = np.partition(sim, n - keep, axis=1)[:, n - keep, None]
    weights = np.where(sim >= thresh, np.maximum(sim, 0), 0.0)
    adj = 0.5 * (weights + weights.T)
    deg = np.maximum(adj.sum(1), 1e-9) ** -0.5
    lap = np.eye(n) - deg[:, None] * adj * deg[None, :]
    evals, evecs = np.linalg.eigh(0.5 * (lap + lap.T))
    ref_k = int(np.argmax(np.diff(evals[:13]))) + 1
    ref_labels = cluster._kmeans(cluster._normalise(evecs[:, :ref_k]), ref_k, None)
    del sim, thresh, weights, adj, deg, lap, evals, evecs

    tracemalloc.start()
    labels, k, _ = cluster.spectral(vectors)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    peak_mb = peak / (1024 * 1024)
    assert k == ref_k == 4
    assert np.array_equal(labels, ref_labels)
    # The peak depends on the numpy build; only the order of magnitude is stable: at most
    # about eight n x n float64 matrices at once.
    limit_mb = 8 * n * n * 8 / (1024 * 1024)
    assert peak_mb < limit_mb, f"expected peak_mb < {limit_mb:.0f} MB, got {peak_mb:.2f} MB"
