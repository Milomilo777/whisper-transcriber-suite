"""A summary shown or saved as plain text must not carry Markdown markers (Groq models add them)."""
from __future__ import annotations

import pytest

from core import llm


@pytest.mark.parametrize("raw, plain", [
    ("- **Budget**: approved", "- Budget: approved"),
    ("**Key points**\n* one\n* two", "Key points\n- one\n- two"),
    ("## Summary\n- a", "Summary\n- a"),
    ("__two words__ and text", "two words and text"),
    ("2 * 3 = 6 and a_b_c", "2 * 3 = 6 and a_b_c"),   # arithmetic and identifiers stay
    # markers inside words or code are not bold: powers, kwargs, dunder and snake names stay
    ("2**3 = 8 and 4**2", "2**3 = 8 and 4**2"),
    ("Use a**b**c", "Use a**b**c"),
    ("g(**kw)", "g(**kw)"),
    ("__init__ and __main__", "__init__ and __main__"),
    ("snake__case__name", "snake__case__name"),
    ("**مهم**: بله", "مهم: بله"),
    ("no markers here", "no markers here"),
    ("", ""),
])
def test_plain_summary_text(raw: str, plain: str) -> None:
    assert llm.plain_summary_text(raw) == plain


def test_prompt_asks_for_plain_text() -> None:
    assert "plain text" in llm._summarise_prompt("hello", 5)


def test_both_runners_clean_the_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    for cls in (llm.LLMRunner, llm.RemoteLLMRunner):
        runner = cls.__new__(cls)
        monkeypatch.setattr(cls, "_chat", lambda self, *a, **k: "- **One**: x", raising=True)
        assert runner.summarise("t") == "- One: x"
