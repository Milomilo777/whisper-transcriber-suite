"""Speaker labels from short voice windows, using only NumPy and the stdlib.

Turn boundaries belong to the diarizer. This module only plans windows and
relabels those turns; callers retain their old labels if any step fails.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator, Sequence

import numpy as np
from numpy.typing import NDArray

# Adapted from 3D-Speaker (https://github.com/modelscope/3D-Speaker) — windowing and pruned spectral clustering.
# Adapted from WeSpeaker (https://github.com/wenet-e2e/wespeaker) — normalized Laplacian and largest eigengap.
# Ported from the locally checked RESEARCH/prototype, not the survey's code.
WINDOW_SECONDS = 1.5
STEP_SECONDS = 0.75
MIN_PIECE_SECONDS = 0.25
MAX_SPECTRAL_WINDOWS = 3000
# 3 % of the sampled windows at most. A lower cap protects short speakers on synthetic
# data, yet on a real 45-minute meeting file 30 raised the confusion from 0.398 to 0.469.
_MAX_NEIGHBOURS = 90
_MIN_EDGE_SIMILARITY = 0.3

Turns = Sequence[tuple[float, float]]
CancelCheck = Callable[[], bool] | None
Progress = Callable[[float], None] | None


class ClusteringCancelled(InterruptedError):
    """Cooperative cancellation, distinct from an invalid embedding."""


def _check_cancelled(cancelled: CancelCheck) -> None:
    if cancelled is not None and cancelled():
        raise ClusteringCancelled("speaker clustering cancelled")


@dataclass(frozen=True)
class SpeechWindow:
    turn_id: int
    start: float
    end: float


def _validate_turns(turns: Turns) -> None:
    for start, end in turns:
        if not (np.isfinite(start) and np.isfinite(end) and 0 <= start <= end):
            raise ValueError("invalid speaker turn boundaries")


def windows_from_turns(turns: Turns) -> Iterator[SpeechWindow]:
    """Yield windows in time order, retaining the caller's turn indices.

    The last piece can be shorter than 1.5 s; pieces below 0.25 s are
    omitted. The extractor repeats a short piece's own samples to 1.5 s.
    """
    _validate_turns(turns)
    for turn_id in sorted(range(len(turns)), key=lambda i: turns[i]):
        start, end = turns[turn_id]
        if end - start <= WINDOW_SECONDS:
            if end - start >= MIN_PIECE_SECONDS:
                yield SpeechWindow(turn_id, start, end)
            continue
        t = start
        while t + WINDOW_SECONDS < end + STEP_SECONDS:
            stop = min(t + WINDOW_SECONDS, end)
            if stop - t >= MIN_PIECE_SECONDS:
                yield SpeechWindow(turn_id, t, stop)
            t += STEP_SECONDS


def _normalise(x: NDArray) -> NDArray:
    return x / np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-9)


def _embeddings(vectors: NDArray) -> NDArray:
    x = np.asarray(vectors)
    if x.ndim != 2 or x.shape[1] == 0:
        raise ValueError("speaker embeddings must be a nonempty-width matrix")
    if x.dtype.kind not in "fiu":
        raise ValueError("speaker embeddings must be real numbers")
    if x.dtype.kind != "f" or x.dtype.itemsize < 8:
        x = x.astype(np.float64)
    if not np.isfinite(x).all():
        raise ValueError("speaker embeddings contain non-finite values")
    norms = np.linalg.norm(x, axis=1, keepdims=True)
    if not np.isfinite(norms).all() or (norms <= 1e-9).any():
        raise ValueError("speaker embeddings contain zero or invalid vectors")
    return x / norms


def _kmeans(x: NDArray, k: int, cancelled: CancelCheck) -> NDArray:
    """Seeded k-means++ on spectral coordinates (at most 12 dimensions)."""
    rng = np.random.default_rng(0)
    centers = [x[rng.integers(len(x))]]
    for _ in range(1, k):
        _check_cancelled(cancelled)
        distances = np.min(((x[:, None, :] - np.array(centers)[None]) ** 2).sum(2), axis=1)
        total = distances.sum()
        centers.append(x[rng.choice(len(x), p=distances / total)]
                       if total > 0 else x[rng.integers(len(x))])
    centers_array = np.array(centers)
    labels = np.zeros(len(x), dtype=np.int32)
    for iteration in range(50):
        _check_cancelled(cancelled)
        new = ((x[:, None, :] - centers_array[None]) ** 2).sum(2).argmin(1)
        if iteration and np.array_equal(new, labels):
            break
        labels = new
        for j in range(k):
            if (labels == j).any():
                centers_array[j] = x[labels == j].mean(0)
    return labels


def _dense_spectral(
    x: NDArray, p: float, max_k: int, min_neighbours: int,
    cancelled: CancelCheck, progress_cb: Progress,
) -> tuple[NDArray, int, NDArray]:
    n = len(x)
    if n == 1:
        return np.zeros(1, dtype=np.int32), 1, np.zeros(1)
    if n == 2:
        same = float(x[0] @ x[1]) >= 0.5
        return (
            np.zeros(2, dtype=np.int32) if same else np.array([0, 1], dtype=np.int32),
            1 if same else 2,
            np.array([0.0, 2.0 if same else 0.0]),
        )
    similarities = x @ x.T
    np.fill_diagonal(similarities, 0)
    keep = min(n - 1, max(min_neighbours, min(_MAX_NEIGHBOURS, int(round(p * n)))))
    thresholds = np.maximum(
        np.partition(similarities, n - keep, axis=1)[:, n - keep, None],
        _MIN_EDGE_SIMILARITY,
    )
    weights = np.where(similarities >= thresholds, np.maximum(similarities, 0), 0.0)
    del similarities, thresholds
    adjacency = 0.5 * (weights + weights.T)
    del weights
    degree = np.maximum(adjacency.sum(1), 1e-9) ** -0.5
    laplacian = -degree[:, None] * adjacency * degree[None, :]
    del adjacency, degree
    laplacian = 0.5 * (laplacian + laplacian.T)
    laplacian.flat[::n + 1] += 1.0
    _check_cancelled(cancelled)
    if progress_cb is not None:
        progress_cb(0.15)
    # eigh itself cannot poll Python. Production runs in a killable worker;
    # its heartbeat thread continues reporting during this bounded solve.
    eigenvalues, eigenvectors = np.linalg.eigh(laplacian)
    del laplacian
    _check_cancelled(cancelled)
    if progress_cb is not None:
        progress_cb(0.8)
    leading = eigenvalues[:min(max_k + 1, n)]
    gaps = np.diff(leading)
    # If more than max_k components are disconnected, all inspected
    # eigenvalues are zero up to construction roundoff. argmax would pick a
    # random tiny gap (often k=1). This is an unresolved count, not evidence
    # for one voice: let the worker keep its legacy labels. Use the matrix
    # construction precision and size, with no fitted acoustic threshold.
    if float(gaps.max()) <= np.finfo(x.dtype).eps * n:
        raise ValueError("no resolved eigengap within the speaker limit")
    k = int(np.argmax(gaps)) + 1
    labels = (np.zeros(n, dtype=np.int32) if k == 1
              else _kmeans(_normalise(eigenvectors[:, :k]), k, cancelled))
    used = np.unique(labels)
    if len(used) < k:
        labels = np.searchsorted(used, labels).astype(np.int32)
        k = int(len(used))
    return labels, k, leading


def spectral(
    vectors: NDArray, *, p: float = 0.03, max_k: int = 12,
    min_neighbours: int = 6, max_windows: int = MAX_SPECTRAL_WINDOWS,
    cancelled: CancelCheck = None, progress_cb: Progress = None,
) -> tuple[NDArray, int, NDArray]:
    """Cluster time-ordered embeddings with the prototype's eigengap rule.

    Above the cap only an evenly spaced sample enters the dense eigensolve.
    Remaining windows take the nearest cosine centroid in embedding space;
    sampled labels stay intact. Working matrices never exceed the cap.
    ``cluster_turns`` supplies canonical time order for shuffled inputs.
    """
    _check_cancelled(cancelled)
    if not (0 < p <= 1 and 1 <= max_k <= 12 and min_neighbours >= 1 and max_windows >= 2):
        raise ValueError("invalid spectral clustering limits")
    x = _embeddings(vectors)
    n = len(x)
    if n == 0:
        return np.empty(0, dtype=np.int32), 0, np.empty(0)
    sample_ids = np.linspace(0, n - 1, min(n, max_windows), dtype=np.int64)
    sampled = x[sample_ids]
    labels, k, eigenvalues = _dense_spectral(
        sampled, p, max_k, min_neighbours, cancelled, progress_cb,
    )
    if n > max_windows:
        centers = _normalise(np.array([sampled[labels == j].mean(0) for j in range(k)]))
        out = np.empty(n, dtype=np.int32)
        out[sample_ids] = labels
        unseen = np.ones(n, dtype=bool)
        unseen[sample_ids] = False
        remaining = np.flatnonzero(unseen)
        for offset in range(0, len(remaining), 512):
            _check_cancelled(cancelled)
            indices = remaining[offset:offset + 512]
            out[indices] = (x[indices] @ centers.T).argmax(1)
        labels = out
    _check_cancelled(cancelled)
    if progress_cb is not None:
        progress_cb(1.0)
    return labels, k, eigenvalues


def turns_from_windows(
    turns: Turns, turn_ids: NDArray, spans: NDArray, labels: NDArray,
) -> list[int]:
    """Duration-weighted votes, then nearest labelled turn by interval gap.

    Ties use times and labels, never input positions. Only turns with their
    own vote can label a short turn, so short-turn chains cannot propagate.
    """
    _validate_turns(turns)
    votes: dict[int, dict[int, float]] = {}
    for turn_id, (start, end), label in zip(turn_ids, spans, labels, strict=True):
        t, lab = int(turn_id), int(label)
        if not 0 <= t < len(turns) or not np.isfinite([start, end]).all() or end <= start or lab < 0:
            raise ValueError("invalid speaker window vote")
        vote = votes.setdefault(t, {})
        vote[lab] = vote.get(lab, 0.0) + float(end - start)
    final = {t: max(v, key=lambda lab: (v[lab], -lab)) for t, v in votes.items()}
    if not final and turns:
        raise ValueError("no speech windows to label speaker turns")
    known = sorted(final, key=lambda t: (turns[t], final[t]))
    for i, (start, end) in enumerate(turns):
        if i not in final:
            nearest = min(known, key=lambda j: (
                max(turns[j][0] - end, start - turns[j][1], 0.0), turns[j], final[j],
            ))
            final[i] = final[nearest]
    return [final[i] for i in range(len(turns))]


def cluster_turns(
    turns: Turns, vectors: NDArray, spans: NDArray, turn_ids: NDArray,
    *, max_windows: int = MAX_SPECTRAL_WINDOWS,
    cancelled: CancelCheck = None, progress_cb: Progress = None,
) -> list[int]:
    """Order windows canonically, cluster, vote, and return labels in input order."""
    _check_cancelled(cancelled)
    _validate_turns(turns)
    v, s, ids = np.asarray(vectors), np.asarray(spans), np.asarray(turn_ids)
    if (v.ndim != 2 or s.shape != (len(v), 2) or ids.shape != (len(v),)
            or ids.dtype.kind not in "iu" or (ids < 0).any() or (ids >= len(turns)).any()):
        raise ValueError("inconsistent speaker window arrays")
    if not np.isfinite(s).all() or (s[:, 1] <= s[:, 0]).any():
        raise ValueError("invalid speaker window spans")
    # Turn times precede window times, matching extraction even for overlapping
    # turns. Vector bytes break exact time ties without using input positions.
    order = sorted(range(len(v)), key=lambda i: (
        turns[int(ids[i])], int(ids[i]), float(s[i, 0]), float(s[i, 1]), v[i].tobytes(),
    ))
    labels, _k, _eigenvalues = spectral(
        v[order], max_windows=max_windows, cancelled=cancelled, progress_cb=progress_cb,
    )
    # Names follow first occurrence in canonical time order, not k-means ids.
    names: dict[int, int] = {}
    canonical = np.array([names.setdefault(int(label), len(names)) for label in labels], dtype=np.int32)
    _check_cancelled(cancelled)
    return turns_from_windows(turns, ids[order], s[order], canonical)
