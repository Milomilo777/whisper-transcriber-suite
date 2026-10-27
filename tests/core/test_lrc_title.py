"""A ``]`` in the media name must not terminate the ``[ti:...]`` tag.

LRC has no escape syntax: a reader ends the ``ti`` tag at the first
``]``, so a file named ``mix]tape [2024].mp3`` was tagged ``ti:mix``
and the remainder ``tape [2024]]`` landed in the body, where readers
render it as a stray lyric line. Strip the bracket characters from the
title (the md writer's heading does the same for its markup).
"""
from core.writers import lrc


def test_lrc_title_brackets_dropped():
    out = lrc.write([], "mix]tape [2024].mp3")
    assert out.splitlines() == ["[ti:mixtape 2024]"]
