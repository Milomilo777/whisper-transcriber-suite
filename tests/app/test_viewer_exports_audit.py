import io
import zipfile

from app.dialogs.viewer_exports import signature


def test_signature_robustness():

    assert signature("txt", b"\xef\xbb\xbfhello\nworld") == "hello\nworld"
    assert signature("txt", b"hello\r\nworld\r\n") == "hello\nworld"
    assert signature("txt", b"hello\nworld\n\n\n") == "hello\nworld"

def test_signature_edge_cases():
    assert signature("txt", b"") == ""
    assert signature("txt", b"\r\n\r\n") == ""

    assert signature("txt", b"a\nb") != signature("txt", b"a\nc")
    assert signature("txt", b"\na") != signature("txt", b"a")
    assert signature("txt", b"a ") != signature("txt", b"a")

def test_signature_docx():
    def build_docx(parts):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for name, content in parts.items():
                z.writestr(name, content)
        return buf.getvalue()

    docx1 = build_docx({"word/document.xml": b"text1", "docProps/core.xml": b"volatile1"})
    docx2 = build_docx({"word/document.xml": b"text1", "docProps/core.xml": b"volatile2"})
    docx_changed = build_docx({"word/document.xml": b"text2", "docProps/core.xml": b"volatile1"})

    assert signature("docx", docx1) == signature("docx", docx2)
    assert signature("docx", docx1) != signature("docx", docx_changed)
