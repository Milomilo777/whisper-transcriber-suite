"""A speaker label carrying a newline must stay inside one Dialogue line.

ASS events are one physical line each; the *Name* field is written
raw (only commas are replaced), so a newline inside a hand-edited
label splits the Dialogue into a broken event and a garbage line.
:func:`core.writers.base.speaker_prefix` collapses such whitespace for
the line-based writers; the ASS *Name* field needs the same treatment.
"""
from core.writers import ass


def test_ass_speaker_newline_stays_on_one_dialogue_line():
    segs = [{"start": 0.0, "end": 1.0, "text": "hi", "speaker": "A\nB\tC"}]
    dialogue = [
        ln for ln in ass.write(segs).splitlines() if ln.startswith("Dialogue:")
    ]
    assert dialogue == [
        "Dialogue: 0,0:00:00.00,0:00:01.00,Default,A B C,0,0,0,,hi"
    ]
