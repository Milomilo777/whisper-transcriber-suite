"""Small-cluster decisions use durations, embeddings, and temporal fallback."""
import random

import pytest

from core.diarization import DiarSegment as Turn, _speaker_gap, merge_small_speakers


@pytest.mark.parametrize("embeddings", [False, True])
def test_incident_49_speakers_become_two(embeddings):
    turns = [Turn(0, 600, "A"), Turn(700, 1300, "B")]
    vectors = {"A": [0.0], "B": [10.0]}
    for i in range(47):
        start = 1 + i if i % 2 == 0 else 701 + i
        label = f"noise{i:02d}"
        turns.append(Turn(start, start + 1, label))
        vectors[label] = [0.0 if i % 2 == 0 else 10.0]
    original = list(turns)
    result = merge_small_speakers(turns, centroids=vectors if embeddings else None)
    assert {s.speaker for s in result} == {"A", "B"}
    assert [s.speaker for s in result[2:]] == ["A" if i % 2 == 0 else "B" for i in range(47)]
    assert [(s.start, s.end) for s in result] == [(s.start, s.end) for s in turns]
    assert turns == original
    assert merge_small_speakers(result) == result


def test_embedding_distance_overrides_adjacency():
    turns = [Turn(0, 50, "A"), Turn(50, 52, "tiny"), Turn(152, 202, "B")]
    result = merge_small_speakers(turns, centroids={"A": [0.0], "tiny": [9.0], "B": [10.0]})
    assert result[1].speaker == "B"


def test_repeated_merges_update_duration_weighted_centroids():
    turns = [Turn(0, 2, "S1"), Turn(2, 8, "S2"),
             Turn(10, 30, "low"), Turn(40, 60, "high")]
    result = merge_small_speakers(turns, centroids={"S1": [3.0], "S2": [4.0],
                                                  "low": [0.0], "high": [7.6]})
    assert [s.speaker for s in result] == ["low", "low", "low", "high"]


@pytest.mark.parametrize("turns", [[], [Turn(0, 1, "only")]])
def test_empty_and_single_speaker(turns):
    assert merge_small_speakers(turns) == turns


def test_forced_count_is_unchanged():
    turns = [Turn(0, 1, "A"), Turn(1, 2, "B"), Turn(2, 50, "C")]
    assert merge_small_speakers(turns, num_speakers=3) is turns


@pytest.mark.parametrize("large,small,merged", [(100, 9, True), (100, 10, False),
                                              (1000, 25, True), (1000, 32, False)])
def test_absolute_or_relative_threshold(large, small, merged):
    turns = [Turn(0, large, "main"), Turn(large + 1, large + 1 + small, "small")]
    result = merge_small_speakers(turns)
    assert (len({s.speaker for s in result}) == 1) is merged


def test_zero_duration_and_whole_cluster_fallback():
    turns = [Turn(100, 99, "zero"), Turn(0, 4, "tiny"), Turn(100, 104, "tiny"),
             Turn(5, 55, "A"), Turn(105, 155, "B")]
    result = merge_small_speakers(turns)
    assert result[1].speaker == result[2].speaker
    assert len({s.speaker for s in result}) == 2
    assert merge_small_speakers(result) == result


def test_all_small_never_drops_last_speaker():
    result = merge_small_speakers([Turn(0, 1, "A"), Turn(2, 3, "B")])
    assert len({s.speaker for s in result}) == 1


def test_streamed_interval_gap_matches_full_pairwise_result():
    rng = random.Random(443)
    for case in range(50):
        left = sorted([Turn(start := rng.uniform(0, 100), start + rng.uniform(0, 5), "A")
                       for _ in range(12)], key=lambda s: s.start)
        # Alternate overlapping and separated lists, so a constant zero
        # implementation cannot accidentally satisfy the reference check.
        right = sorted([Turn(start := rng.uniform(0, 100) + (150 if case % 2 else 0),
                             start + rng.uniform(0, 5), "B")
                        for _ in range(19)], key=lambda s: s.start)
        expected = min(max(0, a.start - b.end, b.start - a.end) for a in left for b in right)
        assert _speaker_gap(left, right) == expected
