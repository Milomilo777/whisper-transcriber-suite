"""Word counts for spaced and unspaced scripts.

Conventions:
- CJK and kana: one word per character.
- Thai, Lao, Khmer, Myanmar: graphemes counted over the whole text and divided by 4 (an approximation).
- Hangul and every other script: whitespace split.
- A token of non-ASCII punctuation only (CJK "。", fullwidth "！") is not a word.

History and statistics `word_count` follow these conventions.
"""

import re
import unicodedata

# CJK Characters: words=characters.
_CJK_RE = re.compile(
    r'['
    r'\u4E00-\u9FFF'    # CJK Unified Ideographs
    r'\u3400-\u4DBF'    # CJK Extension A
    r'\u3040-\u309F'    # Hiragana
    r'\u30A0-\u30FF'    # Katakana
    r'\u31F0-\u31FF'    # Katakana Phonetic Extensions
    r'\uF900-\uFAFF'    # CJK Compatibility Ideographs
    r'\U00020000-\U0002A6DF' # CJK Extension B
    r'\U0002A700-\U0002B73F' # CJK Extension C, D, E, F
    r'\U0002B740-\U0002B81F'
    r'\U0002B820-\U0002CEAF'
    r'\U0002CEB0-\U0002EBEF'
    r']'
)

# SE Asian scripts: written without spaces.
_SEA_RE = re.compile(
    r'['
    r'\u0E00-\u0E7F'    # Thai
    r'\u0E80-\u0EFF'    # Lao
    r'\u1780-\u17FF'    # Khmer
    r'\u1000-\u109F'    # Myanmar
    r']'
)


def count_words(text: str | None) -> int:
    """Number of words in *text* by the conventions above (0 for empty / None)."""
    if not text:
        return 0
    text = str(text)

    cjk_count = len(_CJK_RE.findall(text))

    sea_matches = _SEA_RE.findall(text)
    sea_graphemes = sum(1 for c in sea_matches if not unicodedata.category(c).startswith('M'))
    sea_word_count = max(1, sea_graphemes // 4) if sea_graphemes > 0 else 0

    remaining_text = _CJK_RE.sub(' ', text)
    remaining_text = _SEA_RE.sub(' ', remaining_text)

    # A token left over from unspaced text may be only CJK or fullwidth punctuation ("。", "、"); not a word.
    # ASCII punctuation keeps counting, as in the old whitespace split.
    spaced_word_count = sum(1 for tok in remaining_text.split() if not all(
        ord(c) > 127 and unicodedata.category(c).startswith('P') for c in tok))

    return cjk_count + sea_word_count + spaced_word_count
