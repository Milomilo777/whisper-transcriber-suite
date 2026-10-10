import json
import io
import sys
import threading

from core import voice_clone_worker

def test_emit_success(capsys):
    voice_clone_worker.emit("ready", some_key="value")
    captured = capsys.readouterr()
    data = json.loads(captured.out.strip())
    assert data == {"event": "ready", "some_key": "value"}

def test_emit_fallback(capsys):
    class Unserializable:
        pass
    voice_clone_worker.emit("ready", some_key=Unserializable())
    captured = capsys.readouterr()
    data = json.loads(captured.out.strip())
    assert data["event"] == "ready"
    assert "payload not JSON-serialisable" in data["_emit_warning"]
    assert "Unserializable" in data["some_key"]

def test_emit_fallback_repr_crash(capsys):
    class BadRepr:
        def __repr__(self):
            raise RuntimeError("broken repr")
    class Unserializable:
        def __repr__(self):
            return "CustomRepr"
    
    try:
        voice_clone_worker.emit("ready", bad_key=BadRepr(), good_key=Unserializable())
    except Exception as e:
        assert False, f"emit crashed: {e}"
    captured = capsys.readouterr()
    data = json.loads(captured.out.strip())
    assert data["event"] == "ready"
    assert data["bad_key"].startswith("<unrepresentable: RuntimeError")
    assert data["good_key"] == "CustomRepr"

def test_process_priority_no_psutil(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "psutil", None)
    res = voice_clone_worker._process_priority()
    assert res == "unknown"

def test_exit_if_orphaned_does_not_exit_if_not_busy(monkeypatch):
    exited = False
    def fake_hard_exit(code):
        nonlocal exited
        exited = True
    monkeypatch.setattr(voice_clone_worker, "_hard_exit", fake_hard_exit)
    monkeypatch.setattr(voice_clone_worker, "wait_parent_gone", lambda i, w: True)
    monkeypatch.setattr(voice_clone_worker, "parent_alive", lambda i: False)
    
    monkeypatch.setattr(voice_clone_worker, "_busy", threading.Event())  # not busy; no global state leaks
    voice_clone_worker._exit_if_orphaned(None, "test")
    assert not exited

def test_exit_if_orphaned_exits_if_busy(monkeypatch):
    exited = False
    def fake_hard_exit(code):
        nonlocal exited
        exited = True
    monkeypatch.setattr(voice_clone_worker, "_hard_exit", fake_hard_exit)
    monkeypatch.setattr(voice_clone_worker, "wait_parent_gone", lambda i, w: True)
    monkeypatch.setattr(voice_clone_worker, "parent_alive", lambda i: False)
    
    busy = threading.Event()
    busy.set()
    monkeypatch.setattr(voice_clone_worker, "_busy", busy)  # a fresh Event: the module-global one stays untouched
    voice_clone_worker._exit_if_orphaned(None, "test")
    assert exited
