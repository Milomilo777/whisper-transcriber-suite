"""Transcript editing operations as pure functions."""

from __future__ import annotations

import math
import copy
import unicodedata

class SegmentOpError(ValueError):
    """Raised when a segment operation is rejected."""

def shift(segments: list[dict], seconds: float, *, start_index: int = 0, end_index: int | None = None) -> list[dict]:
    """Shift segments[start_index:end_index] (and their words) by `seconds`. The input is never mutated."""
    if not math.isfinite(seconds):
        raise SegmentOpError(f"Shift amount {seconds} is not finite.")

    if end_index is None:
        end_index = len(segments)

    if not (0 <= start_index <= end_index <= len(segments)):
        raise SegmentOpError("Index out of range.")

    res = copy.deepcopy(segments)

    for i in range(start_index, end_index):
        seg = res[i]
        new_start = seg["start"] + seconds
        new_end = seg["end"] + seconds

        if new_start < 0 or new_end < 0:
            raise SegmentOpError("Shift resulted in negative time.")

        seg["start"] = new_start
        seg["end"] = new_end

        if "words" in seg:
            for w in seg["words"]:
                new_w_start = w["start"] + seconds
                new_w_end = w["end"] + seconds
                if new_w_start < 0 or new_w_end < 0:
                    raise SegmentOpError("Shift resulted in negative word time.")
                w["start"] = new_w_start
                w["end"] = new_w_end

    return res

def linear_sync(segments: list[dict], a: tuple[float, float], b: tuple[float, float]) -> list[dict]:
    """Two-point sync. Input is never mutated."""
    old_a, new_a = a
    old_b, new_b = b

    if old_a == old_b:
        raise SegmentOpError("old_a == old_b in linear_sync.")

    scale = (new_b - new_a) / (old_b - old_a)
    if not (math.isfinite(scale) and scale > 0):
        raise SegmentOpError("Scale must be finite and positive.")

    res = copy.deepcopy(segments)

    for seg in res:
        new_start = new_a + (seg["start"] - old_a) * scale
        new_end = new_a + (seg["end"] - old_a) * scale

        if not math.isfinite(new_start) or not math.isfinite(new_end) or new_start < 0 or new_end < 0:
            raise SegmentOpError("Mapped time is negative or not finite.")

        seg["start"] = new_start
        seg["end"] = new_end

        if "words" in seg:
            for w in seg["words"]:
                new_w_start = new_a + (w["start"] - old_a) * scale
                new_w_end = new_a + (w["end"] - old_a) * scale
                if not math.isfinite(new_w_start) or not math.isfinite(new_w_end) or new_w_start < 0 or new_w_end < 0:
                    raise SegmentOpError("Mapped word time is negative or not finite.")
                w["start"] = new_w_start
                w["end"] = new_w_end

    return res

def _is_cjk(char: str) -> bool:
    if not char:
        return False
    cp = ord(char)
    return (
        0x4E00 <= cp <= 0x9FFF or   # CJK Unified Ideographs
        0x3400 <= cp <= 0x4DBF or   # CJK Unified Ideographs Extension A
        0x3040 <= cp <= 0x309F or   # Hiragana
        0x30A0 <= cp <= 0x30FF or   # Katakana
        0xAC00 <= cp <= 0xD7A3      # Hangul Syllables
    )

def merge_with_next(segments: list[dict], index: int) -> list[dict]:
    """Merges a segment with the next one. Returns a new list of deep-copied segments."""
    if index < 0 or index >= len(segments) - 1:
        raise SegmentOpError("Index out of range for merge (must not be last segment).")

    left = segments[index]
    right = segments[index + 1]

    if "speaker" in left and "speaker" in right and left["speaker"] != right["speaker"]:
        raise SegmentOpError("Cannot merge segments with different speakers.")

    res = copy.deepcopy(segments)
    new_seg = copy.deepcopy(left)

    new_seg["start"] = min(left["start"], right["start"])
    new_seg["end"] = max(left["end"], right["end"])

    for k, v in right.items():
        if k not in new_seg:
            new_seg[k] = copy.deepcopy(v)

    l_text = left.get("text", "") or ""
    r_text = right.get("text", "") or ""

    # Join on the whitespace-stripped edges: whisper texts carry a leading
    # space, and stacking it on the joiner made "hello " + " world" come out
    # with three spaces (and hid the Han char from the CJK rule below).
    l_join = l_text.rstrip()
    r_join = r_text.lstrip()

    # check CJK
    no_space = False
    if l_join and r_join:
        if _is_cjk(l_join[-1]) and _is_cjk(r_join[0]):
            no_space = True

    if no_space or not (l_join and r_join):
        new_seg["text"] = l_join + r_join
    else:
        new_seg["text"] = l_join + " " + r_join

    if "words" in left or "words" in right:
        new_seg["words"] = copy.deepcopy(left.get("words", [])) + copy.deepcopy(right.get("words", []))

    has_suspect = False
    suspect_val = False
    suspect_reason = None
    if "suspect" in left:
        has_suspect = True
        suspect_val = suspect_val or left["suspect"]
        if left["suspect"] and "suspect_reason" in left:
            suspect_reason = left["suspect_reason"]
    if "suspect" in right:
        has_suspect = True
        suspect_val = suspect_val or right["suspect"]
        if right["suspect"] and suspect_reason is None and "suspect_reason" in right:
            suspect_reason = right["suspect_reason"]

    if has_suspect:
        new_seg["suspect"] = suspect_val
    if suspect_reason is not None:
        new_seg["suspect_reason"] = suspect_reason
    elif "suspect_reason" in new_seg and not suspect_val:
        del new_seg["suspect_reason"]


    res[index] = new_seg
    del res[index + 1]

    return res

def split_at(segments: list[dict], index: int, char_offset: int) -> list[dict]:
    """Splits a segment text at char_offset. Returns a new list of deep-copied segments."""
    if index < 0 or index >= len(segments):
        raise SegmentOpError("Index out of range.")

    seg = segments[index]
    text = seg.get("text", "") or ""

    if char_offset <= 0 or char_offset >= len(text):
        raise SegmentOpError("char_offset out of bounds.")
    if unicodedata.combining(text[char_offset]) != 0:
        raise SegmentOpError("Cannot split before a combining mark.")

    left_text_raw = text[:char_offset]
    right_text_raw = text[char_offset:]

    left_text_stripped = left_text_raw.strip()
    right_text_stripped = right_text_raw.strip()

    if not left_text_stripped or not right_text_stripped:
        raise SegmentOpError("Split would result in empty text part.")

    has_words = "words" in seg and seg["words"]
    words = seg.get("words", [])

    left_end_time = None
    right_start_time = None
    left_words = None
    right_words = None

    if has_words and len(words) > 0:
        words_concat = "".join(w["word"].strip() for w in words)
        text_stripped_concat = text.replace(" ", "")

        covers_text = (words_concat == text_stripped_concat)

        if covers_text:
            char_idx = 0
            word_split_idx = 0
            inside_word = False

            for w_idx, w in enumerate(words):
                w_text = w["word"].strip()
                pos = text.find(w_text, char_idx)
                if pos != -1:
                    end_pos = pos + len(w_text)
                    if pos < char_offset < end_pos:
                        inside_word = True
                        break
                    if end_pos <= char_offset:
                        word_split_idx = w_idx + 1
                    char_idx = end_pos

            if not inside_word:
                if word_split_idx > 0 and word_split_idx < len(words):
                    left_end_time = words[word_split_idx - 1]["end"]
                    right_start_time = words[word_split_idx]["start"]
                    left_words = words[:word_split_idx]
                    right_words = words[word_split_idx:]
                elif word_split_idx == len(words):
                    left_end_time = words[-1]["end"]
                    right_start_time = words[-1]["end"]
                    left_words = words
                    right_words = []
                elif word_split_idx == 0:
                    left_end_time = words[0]["start"]
                    right_start_time = words[0]["start"]
                    left_words = []
                    right_words = words

    if left_end_time is None or right_start_time is None:
        len_l = len(left_text_stripped)
        len_r = len(right_text_stripped)
        ratio = len_l / (len_l + len_r)

        split_point = seg["start"] + (seg["end"] - seg["start"]) * ratio

        if seg["start"] < seg["end"]:
            # Clamp to ensure strict positive duration if original duration > 0
            if split_point <= seg["start"]:
                split_point = seg["start"] + 1e-9
            if split_point >= seg["end"]:
                split_point = seg["end"] - 1e-9

        left_end_time = split_point
        right_start_time = split_point

        if has_words:
            left_words = []
            right_words = []
            for w in words:
                w_mid = (w["start"] + w["end"]) / 2
                if w_mid < left_end_time:
                    left_words.append(w)
                else:
                    right_words.append(w)


    left_seg = copy.deepcopy(seg)
    right_seg = copy.deepcopy(seg)

    left_seg["text"] = left_text_raw.rstrip()
    right_seg["text"] = right_text_raw.lstrip()

    left_seg["end"] = left_end_time
    right_seg["start"] = right_start_time

    if "words" in seg:
        left_seg["words"] = copy.deepcopy(left_words) if left_words is not None else []
        right_seg["words"] = copy.deepcopy(right_words) if right_words is not None else []

    res = copy.deepcopy(segments)
    res[index] = left_seg
    res.insert(index + 1, right_seg)

    return res

def delete(segments: list[dict], index: int) -> list[dict]:
    """Deletes the segment at the index. Returns a new list of deep-copied segments."""
    if index < 0 or index >= len(segments):
        raise SegmentOpError("Index out of range.")
    res = copy.deepcopy(segments)
    del res[index]
    return res

def set_text(segments: list[dict], index: int, text: str) -> list[dict]:
    """Sets the text for a segment. Returns a new list of deep-copied segments."""
    if index < 0 or index >= len(segments):
        raise SegmentOpError("Index out of range.")
    res = copy.deepcopy(segments)
    res[index]["text"] = (text or "").rstrip()
    return res

def set_times(segments: list[dict], index: int, start: float, end: float) -> list[dict]:
    """Sets start and end times for a segment. The result is NOT re-sorted; the caller decides."""
    if index < 0 or index >= len(segments):
        raise SegmentOpError("Index out of range.")
    if not math.isfinite(start) or not math.isfinite(end):
        raise SegmentOpError("Times must be finite.")
    if start < 0:
        raise SegmentOpError("Start time must be >= 0.")
    if end <= start:
        raise SegmentOpError("End time must be > start time.")

    res = copy.deepcopy(segments)
    res[index]["start"] = start
    res[index]["end"] = end
    return res

class History:
    """Undo/redo of whole segment lists. Input is never mutated."""
    def __init__(self, initial: list[dict], capacity: int = 200):
        self._capacity = capacity
        self._undo_stack: list[tuple[list[dict], str | None]] = [(copy.deepcopy(initial), None)]
        self._redo_stack = []

    def push(self, segments: list[dict], label: str):
        """Records a new state. Input is never mutated."""
        self._undo_stack.append((copy.deepcopy(segments), label))
        self._redo_stack.clear()
        if len(self._undo_stack) > self._capacity + 1:
            self._undo_stack.pop(0)

    def undo(self) -> list[dict]:
        """Undoes the last operation. Returns a deep copy; stored state is never mutated."""
        if not self.can_undo:
            raise SegmentOpError("Nothing to undo.")
        state, label = self._undo_stack.pop()
        self._redo_stack.append((state, label))
        return copy.deepcopy(self._undo_stack[-1][0])

    def redo(self) -> list[dict]:
        """Redoes the last undone operation. Returns a deep copy; stored state is never mutated."""
        if not self.can_redo:
            raise SegmentOpError("Nothing to redo.")
        state, label = self._redo_stack.pop()
        self._undo_stack.append((state, label))
        return copy.deepcopy(state)

    @property
    def can_undo(self) -> bool:
        return len(self._undo_stack) > 1

    @property
    def can_redo(self) -> bool:
        return len(self._redo_stack) > 0

    @property
    def undo_label(self) -> str | None:
        if self.can_undo:
            return self._undo_stack[-1][1]
        return None

    @property
    def redo_label(self) -> str | None:
        if self.can_redo:
            return self._redo_stack[-1][1]
        return None

