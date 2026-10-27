"""A speaker label carrying a newline must not break inside the run.

python-docx turns a ``\\n`` in run text into a ``<w:br/>`` (and a tab
into ``<w:tab/>``), so a hand-edited label like ``"A\\nB\\tC"`` renders
the bold ``Speaker: `` prefix across two visual lines. Every other
writer collapses the label's embedded whitespace (``speaker_prefix``
for the text formats, and the md / ass writers likewise).
"""
import io
import zipfile

from core.writers import docx_writer


def test_docx_speaker_newline_stays_on_one_line():
    segs = [{"start": 0.0, "end": 1.0, "text": "hi", "speaker": "A\nB\tC"}]
    doc = docx_writer.write_bytes(segs, "a.wav")
    xml = zipfile.ZipFile(io.BytesIO(doc)).read("word/document.xml").decode("utf-8")
    assert "<w:br/>" not in xml
    assert "<w:tab/>" not in xml
    assert "A B C: " in xml
