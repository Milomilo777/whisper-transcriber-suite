"""Windowless safety contracts for the QA probe; all native APIs are fakes."""
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def guards():
    path = Path(__file__).resolve().parents[1] / "tools/qa/altgr_guards.py"
    spec = importlib.util.spec_from_file_location("tested_altgr_guards", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ChordAPI:
    def __init__(self, owners=(True, True, True), held=(), results=(6, 3)):
        self.owners = iter(owners)
        self.held = held
        self.results = iter(results)
        self.calls = []

    def owns(self):
        return next(self.owners)

    def down(self, key):
        return key in self.held

    def send(self, events):
        self.calls.append(events)
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        return result


CHORD = [(0xA2, 0), (0xA5, 1), (65, 0), (65, 2), (0xA5, 3), (0xA2, 2)]
RELEASE = [(65, 2), (0xA5, 3), (0xA2, 2)]


def test_guarded_chord_success_uses_left_ctrl_and_release_proof(guards):
    api = ChordAPI()
    assert guards.guarded_chord(api, 65) == {"sent_events": 6, "cleanup_keyups": 3}
    assert api.calls == [CHORD, RELEASE]


@pytest.mark.parametrize("owners", [(False,), (True, False)])
def test_guarded_chord_rejects_ownership_loss_before_submission(guards, owners):
    api = ChordAPI(owners=owners)
    with pytest.raises(guards.GuardError, match="ownership|owned"):
        guards.guarded_chord(api, 65)
    assert api.calls == []


@pytest.mark.parametrize("key", [0xA2, 0xA5, 65])
def test_guarded_chord_rejects_each_held_key(guards, key):
    api = ChordAPI(held=(key,))
    with pytest.raises(guards.GuardError, match="already held"):
        guards.guarded_chord(api, 65)
    assert api.calls == []


@pytest.mark.parametrize("sent", range(6))
def test_guarded_chord_partial_send_still_releases_only_owned_keys(guards, sent):
    api = ChordAPI(results=(sent, 3))
    with pytest.raises(guards.GuardError, match="Partial native input"):
        guards.guarded_chord(api, 65)
    assert api.calls == [CHORD, RELEASE]


def test_guarded_chord_send_exception_is_preserved_after_cleanup(guards):
    error = OSError("fake send failure")
    api = ChordAPI(results=(error, 3))
    with pytest.raises(OSError) as caught:
        guards.guarded_chord(api, 65)
    assert caught.value is error
    assert api.calls == [CHORD, RELEASE]


@pytest.mark.parametrize("released", [0, 1, 2])
def test_guarded_chord_incomplete_cleanup_is_fatal(guards, released):
    api = ChordAPI(results=(6, released))
    with pytest.raises(guards.GuardCleanupError, match="release incomplete"):
        guards.guarded_chord(api, 65)
    assert api.calls == [CHORD, RELEASE]


def test_guarded_chord_cleanup_exception_is_fatal(guards):
    error = OSError("fake release failure")
    api = ChordAPI(results=(6, error))
    with pytest.raises(guards.GuardCleanupError, match="release failed") as caught:
        guards.guarded_chord(api, 65)
    assert caught.value.__cause__ is error
    assert api.calls == [CHORD, RELEASE]


def test_guarded_chord_releases_after_foreground_loss_then_aborts(guards):
    api = ChordAPI(owners=(True, True, False))
    with pytest.raises(guards.GuardError, match="Foreground changed during input"):
        guards.guarded_chord(api, 65)
    assert api.calls == [CHORD, RELEASE]


class LayoutAPI:
    def __init__(self, current=1, loaded=(1, 2), owners=(True, True), actions=None):
        self.value = current
        self.layouts = loaded
        self.owners = iter(owners)
        self.actions = iter(actions) if actions is not None else None
        self.calls = []

    def current(self):
        return self.value

    def loaded(self):
        return self.layouts

    def owns_thread(self):
        return next(self.owners)

    def activate(self, target, flags):
        self.calls.append((target, flags))
        previous = self.value
        if self.actions is not None:
            result, value = next(self.actions)
            self.value = value
            if isinstance(result, Exception):
                raise result
            return result
        self.value = target
        return previous


def test_temporary_layout_switches_and_restores_with_proof(guards):
    api = LayoutAPI()
    with guards.temporary_layout(api, 2) as proof:
        assert api.value == 2
        assert proof == {"original": "0x1", "selected": "0x2", "activation_flags": 0, "restored": False}
    assert api.value == 1
    assert api.calls == [(2, 0), (1, 0)]
    assert proof["restored"] is True


def test_temporary_layout_same_target_needs_no_activation(guards):
    api = LayoutAPI(loaded=())
    with guards.temporary_layout(api, 1) as proof:
        assert proof["restored"] is False
    assert api.calls == []
    assert proof["restored"] is True


def test_temporary_layout_restores_after_body_exception(guards):
    api = LayoutAPI()
    error = ValueError("body failure")
    with pytest.raises(ValueError) as caught:
        with guards.temporary_layout(api, 2) as proof:
            raise error
    assert caught.value is error
    assert api.calls == [(2, 0), (1, 0)]
    assert proof["restored"] is True


@pytest.mark.parametrize("actions", [
    [(0, 2), (2, 1)],
    [(1, 1), (1, 1)],
    [(OSError("activation failed"), 2), (2, 1)],
])
def test_temporary_layout_failed_activation_still_restores(guards, actions):
    api = LayoutAPI(actions=actions)
    with pytest.raises((guards.GuardError, OSError)):
        with guards.temporary_layout(api, 2):
            pytest.fail("Failed activation must not yield")
    assert api.calls == [(2, 0), (1, 0)]
    assert api.value == 1


@pytest.mark.parametrize("result,value,message", [(0, 2, "could not be restored"), (2, 2, "restoration is unverified")])
def test_temporary_layout_restoration_failure_keeps_proof_false(guards, result, value, message):
    api = LayoutAPI(actions=[(1, 2), (result, value)])
    with pytest.raises(guards.GuardCleanupError, match=message):
        with guards.temporary_layout(api, 2) as proof:
            pass
    assert proof["restored"] is False
    assert api.calls == [(2, 0), (1, 0)]


def test_temporary_layout_unloaded_target_is_rejected(guards):
    api = LayoutAPI()
    with pytest.raises(guards.GuardError, match="not already loaded"):
        with guards.temporary_layout(api, 3):
            pytest.fail("Unloaded target must not yield")
    assert api.calls == []


@pytest.mark.parametrize("owners,expected_calls", [((False,), []), ((True, False), [(2, 0)])])
def test_temporary_layout_requires_thread_ownership(guards, owners, expected_calls):
    api = LayoutAPI(owners=owners)
    with pytest.raises(guards.GuardError, match="fixture thread"):
        with guards.temporary_layout(api, 2):
            pass
    assert api.calls == expected_calls


@pytest.mark.parametrize("original,target", [(0, 2), (True, 2), (1, 0), (1, True), (None, 2), (1, "2")])
def test_temporary_layout_rejects_unknown_identity(guards, original, target):
    api = LayoutAPI(current=original)
    with pytest.raises(guards.GuardError, match="identity is unknown"):
        with guards.temporary_layout(api, target):
            pytest.fail("Invalid identity must not yield")
    assert api.calls == []


@pytest.mark.parametrize("loaded", [(0,), (True,), ("2",), tuple(range(1, 34))])
def test_temporary_layout_rejects_invalid_loaded_enumeration(guards, loaded):
    api = LayoutAPI(loaded=loaded)
    with pytest.raises(guards.GuardError, match="Loaded-layout identity"):
        with guards.temporary_layout(api, 2):
            pytest.fail("Invalid enumeration must not yield")
    assert api.calls == []


def ownership_proof():
    return {"foreground_hwnd": 10, "expected_top_hwnd": 10,
            "foreground_pid": 20, "expected_pid": 20,
            "native_focus_hwnd": 11, "expected_widget_hwnd": 11,
            "native_focus_pid": 20, "native_focus_root_hwnd": 10,
            "tk_focus_matches": True}


def test_ownership_allowed_accepts_complete_matching_proof(guards):
    assert guards.ownership_allowed(ownership_proof()) is True


@pytest.mark.parametrize("field", list(ownership_proof()))
def test_ownership_allowed_rejects_each_missing_field(guards, field):
    proof = ownership_proof()
    del proof[field]
    assert guards.ownership_allowed(proof) is False


@pytest.mark.parametrize("field", [field for field in ownership_proof() if field != "tk_focus_matches"])
@pytest.mark.parametrize("value", [0, -1, True, None, "10", 10.0])
def test_ownership_allowed_rejects_nonpositive_or_noninteger_identity(guards, field, value):
    proof = ownership_proof()
    proof[field] = value
    assert guards.ownership_allowed(proof) is False


@pytest.mark.parametrize("field", ["foreground_hwnd", "foreground_pid", "native_focus_pid", "native_focus_root_hwnd"])
def test_ownership_allowed_rejects_cross_window_or_process_proof(guards, field):
    proof = ownership_proof()
    proof[field] += 1
    assert guards.ownership_allowed(proof) is False


@pytest.mark.parametrize("value", [False, 1, "true", None])
def test_ownership_allowed_requires_literal_tk_focus_true(guards, value):
    proof = ownership_proof()
    proof["tk_focus_matches"] = value
    assert guards.ownership_allowed(proof) is False
