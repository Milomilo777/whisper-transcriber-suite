from __future__ import annotations
import gc
import threading
import time
import pytest
from core import _gc_import_guard

def test_gc_disabled_import_disables_and_restores():
    # Make sure GC is enabled initially
    gc.enable()
    assert gc.isenabled()
    
    with _gc_import_guard.gc_disabled_import():
        assert not gc.isenabled()
        
    assert gc.isenabled()

def test_gc_disabled_import_respects_previous_state():
    # Make sure GC is disabled initially; always re-enable it, even when an assert fails.
    gc.disable()
    try:
        assert not gc.isenabled()
        with _gc_import_guard.gc_disabled_import():
            assert not gc.isenabled()
        assert not gc.isenabled()
    finally:
        gc.enable()

def test_gc_disabled_import_exception_propagation():
    gc.enable()
    class DummyError(Exception):
        pass
        
    with pytest.raises(DummyError):
        with _gc_import_guard.gc_disabled_import():
            assert not gc.isenabled()
            raise DummyError("Oops")
            
    # GC should be restored even if an exception occurs
    assert gc.isenabled()

def test_gc_disabled_import_recursive_deadlock():
    # Hypothesis: calling gc_disabled_import inside gc_disabled_import will not deadlock
    # now that we use RLock.
    
    result = []
    
    def recursive_call():
        try:
            with _gc_import_guard.gc_disabled_import():
                with _gc_import_guard.gc_disabled_import():
                    result.append("success")
        except Exception as e:
            result.append(e)

    t = threading.Thread(target=recursive_call, daemon=True)
    t.start()
    t.join(timeout=0.5)
    
    assert not t.is_alive(), "Deadlock occurred"
    assert result == ["success"]
