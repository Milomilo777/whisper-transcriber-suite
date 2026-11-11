"""One unreadable history JSON field must not stop rebuilding healthy search rows."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from core import search


@pytest.fixture
def bounded_json_integers():
    previous = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(4300)
    try:
        yield
    finally:
        sys.set_int_max_str_digits(previous)


@pytest.mark.parametrize("damaged", ["[" * 1100 + "0" + "]" * 1100, "1" * 5000],
                         ids=["depth", "integer_limit"])
def test_reindex_keeps_healthy_transcripts_after_json_resource_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damaged: str, bounded_json_integers,
) -> None:
    files = [tmp_path / "first.json", tmp_path / "last.json"]
    originals = {}
    for path, text in zip(files, ["first healthy transcript", "last healthy transcript"]):
        data = json.dumps([{"start": 0.0, "end": 1.0, "text": text}]).encode()
        path.write_bytes(data)
        originals[path] = data

    class History:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def list_transcriptions(self, **_kwargs):
            return [{"output_paths": [str(files[0])]}, {"output_paths": damaged},
                    {"output_paths": [str(files[1])]}]

    # History deliberately retains an unreadable optional field as its raw
    # string. Use the portable JSON scanner for stable nesting-limit behavior.
    decoder = json.JSONDecoder()
    decoder.scan_once = json.scanner.py_make_scanner(decoder)
    native_loads = json.loads

    def loads(raw, *args, **kwargs):
        return decoder.decode(raw) if raw == damaged else native_loads(raw, *args, **kwargs)

    monkeypatch.setattr(search.json, "loads", loads)
    monkeypatch.setattr("core.history.HistoryDB", History)
    monkeypatch.setattr(search, "user_data_dir", lambda: tmp_path)
    assert search.reindex_all_history() == 2
    assert len(search.search("first")) == 1
    assert len(search.search("last")) == 1
    assert search.reindex_all_history() == 2
    assert all(path.read_bytes() == content for path, content in originals.items())
