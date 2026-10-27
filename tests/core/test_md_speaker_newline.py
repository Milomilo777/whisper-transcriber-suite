"""A speaker label carrying a newline must stay on one markdown line.

The markdown writer glues the speaker into its own ``**HH:MM:SS** _Name:_``
line; a raw newline inside a hand-edited label splits that line in two,
the same break :func:`core.writers.base.speaker_prefix` already collapses
away for the line-based txt / lrc / tsv / srt writers.
"""
from core.writers import md


def test_md_speaker_newline_stays_on_one_line():
    segs = [{"start": 0.0, "end": 1.0, "text": "hi", "speaker": "A\nB\tC"}]
    assert md.write(segs).splitlines() == [
        "# Transcript",
        "",
        "**00:00:00** _A B C:_ hi",
    ]
