import pytest
from types import SimpleNamespace
from app import app as appmod
import core.burn_subs as burn_subs
import core._threads as threads

def test_manual_burn_subs_returns_correct_path(tmp_path, monkeypatch):
    video = tmp_path / "vid.mp4"
    srt = tmp_path / "sub.srt"
    out = tmp_path / "out.mp4"
    salvaged = tmp_path / "out (2).mp4"

    video.write_bytes(b"vid")
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\ntest\n", encoding="utf-8")

    captured = []
    fake_app = SimpleNamespace(
        log=lambda msg: None,
        post_to_main=lambda f: f(),
        _burn_subs_done=captured.append,
        _burn_subs_failed=lambda msg: None
    )

    task = SimpleNamespace(file_path=str(video), output_paths=[str(srt)])

    monkeypatch.setattr(threads, "safe_thread", lambda fn, name="": fn())
    monkeypatch.setattr("tkinter.filedialog.asksaveasfilename", lambda **kw: str(out))

    def fake_burn(v, s, o, **kw):
        return str(salvaged)
    monkeypatch.setattr(burn_subs, "burn", fake_burn)

    appmod.App._burn_subs_for(fake_app, task)
    assert captured == [str(salvaged)]

def test_manual_burn_subs_handles_none_fallback(tmp_path, monkeypatch):
    video = tmp_path / "vid.mp4"
    srt = tmp_path / "sub.srt"
    out = tmp_path / "out.mp4"

    video.write_bytes(b"vid")
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\ntest\n", encoding="utf-8")

    captured = []
    fake_app = SimpleNamespace(
        log=lambda msg: None,
        post_to_main=lambda f: f(),
        _burn_subs_done=captured.append,
        _burn_subs_failed=lambda msg: None
    )

    task = SimpleNamespace(file_path=str(video), output_paths=[str(srt)])

    monkeypatch.setattr(threads, "safe_thread", lambda fn, name="": fn())
    monkeypatch.setattr("tkinter.filedialog.asksaveasfilename", lambda **kw: str(out))

    def fake_burn(v, s, o, **kw):
        return None
    monkeypatch.setattr(burn_subs, "burn", fake_burn)

    appmod.App._burn_subs_for(fake_app, task)
    assert captured == [str(out)]

