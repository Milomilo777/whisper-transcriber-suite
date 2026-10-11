import pytest
from core.loop_guard import (
    guard_repeats, _is_tight, repeat_key, LoopGuardStats, repeat_limit
)
from collections import namedtuple

Seg = namedtuple("Seg", ["start", "end", "text", "avg_logprob", "compression_ratio", "no_speech_prob"])
def seg(start, end, text):
    return Seg(start, end, text, -0.1, 1.0, 0.0)

class TestLoopGuard:
    def test_repeat_key(self):
        assert repeat_key("Hello!") == "hello"
        assert repeat_key("  hello  ") == "hello"
        assert repeat_key("...") == ""
        assert repeat_key(None) == ""

    def test_repeat_limit(self):
        assert repeat_limit({}) == 3 # DEFAULT_REPEATS
        assert repeat_limit({"loop_guard_repeats": False}) == 0
        assert repeat_limit({"loop_guard_repeats": True}) == 3
        assert repeat_limit({"loop_guard_repeats": "4"}) == 4
        assert repeat_limit({"loop_guard_repeats": "invalid"}) == 3

    def test_is_tight(self):
        assert _is_tight(seg(0, 1, ""), seg(1.05, 2, ""))
        assert not _is_tight(seg(0, 1, ""), seg(2, 3, ""))
        assert not _is_tight(seg(None, None, ""), seg(None, None, ""))

    def test_guard_no_limit(self):
        segs = [seg(0, 1, "hello"), seg(1, 2, "hello")]
        res = list(guard_repeats(segs, limit=0))
        assert len(res) == 2

    def test_guard_marks(self):
        segs = [seg(0, 1, "hello"), seg(1.05, 2, "hello"), seg(2.05, 3, "hello")]
        stats = LoopGuardStats()
        res = list(guard_repeats(segs, limit=2, hard=5, stats=stats))
        assert len(res) == 3
        assert stats.marked == 2
        assert len(stats.marked_ids) == 2

    def test_guard_restart(self):
        class SegIter:
            def __init__(self, items):
                self.items = items
                self.idx = 0
            def __iter__(self):
                return self
            def __next__(self):
                if self.idx < len(self.items):
                    val = self.items[self.idx]
                    self.idx += 1
                    return val
                raise StopIteration

        items = [seg(0, 1, "hello"), seg(1.05, 2, "hello"), seg(2.05, 3, "hello")]
        it = SegIter(items)
        
        def good_restart(at):
            return [seg(2.05, 3, "world")]

        res = list(guard_repeats(it, limit=2, hard=3, restart=good_restart))
        assert len(res) == 2
        assert res[0].text == "hello"
        assert res[1].text == "world"

    def test_guard_restart_lazy_fail(self):
        class SegIter:
            def __init__(self, items):
                self.items = items
                self.idx = 0
            def __iter__(self):
                return self
            def __next__(self):
                if self.idx < len(self.items):
                    val = self.items[self.idx]
                    self.idx += 1
                    return val
                raise StopIteration

        items = [seg(0, 1, "hello"), seg(1.05, 2, "hello"), seg(2.05, 3, "hello")]
        it = SegIter(items)
        
        def lazy_restart(at):
            def gen():
                yield seg(3.05, 4, "world")
                raise ValueError("Lazy failure")
            return gen()

        res = []
        with pytest.raises(ValueError):
            for x in guard_repeats(it, limit=2, hard=3, restart=lazy_restart):
                res.append(x)
        assert len(res) == 2
        assert res[1].text == "world"

    def test_guard_restart_fail_fallback(self):
        items = [seg(0, 1, "hello"), seg(1.05, 2, "hello"), seg(2.05, 3, "hello")]
        
        def immediate_fail_restart(at):
            raise ValueError("Immediate fail")

        stats = LoopGuardStats()
        res = list(guard_repeats(items, limit=2, hard=3, restart=immediate_fail_restart, stats=stats))
        assert len(res) == 1
        assert stats.dropped == 2

    def test_repeat_key_unicode(self):
        assert repeat_key("السلام عليكم") == "السلامعليكم"
        assert repeat_key("你好") == "你好"
        assert repeat_key("Hello 😊") == "hello"
        assert repeat_key("こんにちは") == "こんにちは"
        assert repeat_key("  123 456  ") == "123456"
