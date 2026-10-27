"""An empty segment must get no dangling speaker label.

``base.labelled_text`` returns "" when the text is empty "so an empty
segment gets no dangling label", and the sibling test
``test_empty_segment_gets_no_dangling_speaker_label`` asserts exactly
that for txt / lrc / tsv / otr. The Express Scribe and InqScribe
writers hand-roll ``speaker_prefix + normalize_text`` instead, so an
empty segment came out as a bare ``"A: "`` line.
"""
from core.writers import express_scribe, inqscribe


def test_express_scribe_empty_segment_gets_no_dangling_label():
    segs = [{"start": 0.0, "end": 1.0, "text": "  ", "speaker": "A"}]
    assert express_scribe.write(segs) == "[00:00:00] \n"


def test_inqscribe_empty_segment_gets_no_dangling_label():
    segs = [{"start": 0.0, "end": 1.0, "text": "  ", "speaker": "A"}]
    assert inqscribe.write(segs) == "[00:00:00.00]\n"
