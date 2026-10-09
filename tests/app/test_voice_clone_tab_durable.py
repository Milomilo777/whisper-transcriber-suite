"""Review fixes for the Text to Voice tab (app/widgets/voice_clone_tab.py):
Play on macOS/Linux, one language code for OmniVoice, the disk check before
every start, a finished job reused instead of spoken again, the time for the
pieces left, controls locked while a job runs, a clone job's clips kept with
the job, Kokoro refusing a script it has no voice for, the scratch sweep off
the Tk thread, and Start over refused while another window runs the job.

Same hermetic fakes as test_voice_clone_tab.py: no model, worker or download.
"""
from __future__ import annotations

import os
import types
from typing import Any

import pytest

tk = pytest.importorskip("tkinter")

from app.widgets import voice_clone_tab as vct  # noqa: E402
from core import tts_job  # noqa: E402
from tests.app.test_voice_clone_tab import (  # noqa: E402,F401
    LONG, _build, _cancel_kokoro_after, _confirm_shown, _engine, _kokoro_job, _packed,
    _plain_kokoro, _tick, _write_wav, fakes, no_dialogs, root,
)


def _disabled(widget: Any) -> bool:
    try:
        return str(widget.cget("state")) == "disabled"
    except tk.TclError:
        return widget.instate(["disabled"])


# ------------------------------------------------------------- Play (S08-1)


@pytest.mark.parametrize("platform, command", [("darwin", "open"), ("linux", "xdg-open")])
def test_play_opens_the_file_on_macos_and_linux(root, fakes, monkeypatch, tmp_path,
                                                no_dialogs, platform, command):
    from app.widgets import platform as plat

    opened: list = []
    monkeypatch.setattr(plat, "sys", types.SimpleNamespace(platform=platform))
    monkeypatch.delattr(os, "startfile", raising=False)
    def popen(cmd, **_k):
        opened.append(cmd)
        return types.SimpleNamespace(wait=lambda timeout=None: 0)  # the opener exited 0

    monkeypatch.setattr(plat.subprocess, "Popen", popen)
    app = _build(root, fakes)
    out = tmp_path / "speech.wav"
    _write_wav(str(out), 1.0)
    app.vc_last_output = str(out)
    vct._play(app)
    assert no_dialogs == []
    assert opened == [[command, str(out)]]


def test_preview_plays_through_the_same_opener(root, fakes, monkeypatch):
    played: list = []
    monkeypatch.setattr(vct, "open_with_default_app", lambda path: played.append(path))
    app = _build(root, fakes)
    _engine(app, vct._ENGINE_KOKORO, "")
    vct._preview(app)
    assert played == [app.vc_last_output]


# --------------------------------------------------- language code (S08-3)


def test_omnivoice_gets_one_language_code_not_the_list(root, fakes):
    app = _build(root, fakes)
    _engine(app, vct._ENGINE_OMNI, "Hello there.", mode=vct._MODE_DESIGN)
    app.vc_lang_var.set("Chinese (Simplified)")
    app.vc_generate_btn.invoke()
    assert fakes["generate"][0]["language"] == "zh"


# ------------------------------------------------ disk check always (S08-8)


def test_a_job_the_disk_cannot_hold_never_starts_even_without_the_confirm_step(
        root, fakes, monkeypatch):
    from core import tts_plan

    monkeypatch.setattr(tts_plan, "needs_confirm", lambda _est: False)
    fakes["free"] = 1000
    app = _build(root, fakes)
    _engine(app, vct._ENGINE_KOKORO, "Hello there.")
    app.vc_generate_btn.invoke()
    assert fakes["kokoro"] == []
    assert _confirm_shown(app)
    assert "Not enough free disk space" in app.vc_confirm_var.get()
    app.vc_confirm_cancel_btn.invoke()


# ------------------------------------------ finished jobs, time left (S08-7)


def _finish_long_kokoro(app: Any) -> str:
    _kokoro_job(app)
    app.vc_confirm_start_btn.invoke()
    assert app.vc_status_var.get().startswith("Done")
    return app.vc_last_output


def test_generate_on_a_finished_job_reuses_its_file(root, fakes, monkeypatch):
    monkeypatch.setitem(tts_job.PIECE_CHARS, "kokoro", 600)
    app = _build(root, fakes)
    _engine(app, vct._ENGINE_KOKORO, LONG)
    out = _finish_long_kokoro(app)
    stamp = os.stat(out).st_mtime_ns
    spoken = len(fakes["kokoro"])

    app.vc_generate_btn.invoke()
    assert _confirm_shown(app)
    assert "already spoken" in app.vc_confirm_var.get()
    assert str(app.vc_confirm_start_btn.cget("text")) == "Use the finished file"
    assert _packed(app.vc_confirm_restart_btn)
    app.vc_confirm_start_btn.invoke()
    assert len(fakes["kokoro"]) == spoken  # nothing spoken again
    assert app.vc_last_output == out and os.stat(out).st_mtime_ns == stamp
    assert str(app.vc_play_btn.cget("state")) == "normal"
    assert "finished earlier" in app.vc_status_var.get()
    assert not _confirm_shown(app) and not app.vc_busy


def test_start_over_on_a_finished_job_speaks_it_again(root, fakes, monkeypatch):
    monkeypatch.setitem(tts_job.PIECE_CHARS, "kokoro", 600)
    app = _build(root, fakes)
    _engine(app, vct._ENGINE_KOKORO, LONG)
    _finish_long_kokoro(app)
    fakes["kokoro"].clear()
    app.vc_generate_btn.invoke()
    app.vc_confirm_restart_btn.invoke()
    assert fakes["kokoro"] == [p.strip() for p in tts_job.split_text(LONG, 600)]
    assert app.vc_status_var.get().startswith("Done")


def test_a_continued_job_shows_the_time_for_the_pieces_left(root, fakes, monkeypatch):
    from core import tts_kokoro, tts_plan

    monkeypatch.setitem(tts_job.PIECE_CHARS, "kokoro", 600)
    _cancel_kokoro_after(monkeypatch, fakes, 3)
    app = _build(root, fakes)
    _engine(app, vct._ENGINE_KOKORO, LONG)
    _kokoro_job(app)
    app.vc_confirm_start_btn.invoke()
    monkeypatch.setattr(tts_kokoro, "generate", _plain_kokoro(fakes))
    app.vc_generate_btn.invoke()
    plan = app.vc_plan
    est, job = plan.estimate, plan.job
    assert est.time_high is not None and job.done
    left = 1.0 - job.done_units / job.total_units
    whole = tts_plan.format_duration_range(est.time_low, est.time_high)
    rest = tts_plan.format_duration_range(est.time_low * left, est.time_high * left)
    text = app.vc_confirm_var.get()
    assert f"Time left for the {len(job.pending())} unfinished pieces" in text
    assert rest in text and rest != whole
    app.vc_confirm_cancel_btn.invoke()


# ---------------------------------------------------- locked controls (B5)


def _voice_controls(app: Any) -> "list[Any]":
    return [app.vc_record_btn, app.vc_load_btn, app.vc_remove_btn, app.vc_consent_check,
            app.vc_voice_combo, app.vc_lang_combo, *app.vc_mode_radios,
            *app.vc_design_widgets]


def test_voice_controls_are_locked_on_the_confirm_step_and_while_a_job_runs(
        root, fakes, monkeypatch):
    from core import tts_kokoro

    app = _build(root, fakes)
    _engine(app, vct._ENGINE_KOKORO, LONG)
    assert not any(_disabled(w) for w in _voice_controls(app) if w is not app.vc_lang_combo)
    app.vc_generate_btn.invoke()
    assert _confirm_shown(app)
    assert all(_disabled(w) for w in _voice_controls(app))

    seen: list = []
    inner = tts_kokoro.generate

    def gen(text: str, voice: str, out: str, **kw: Any) -> Any:
        seen.append([_disabled(w) for w in _voice_controls(app)])
        return inner(text, voice, out, **kw)

    monkeypatch.setattr(tts_kokoro, "generate", gen)
    if _packed(app.vc_confirm_measure_btn):
        app.vc_confirm_measure_btn.invoke()
    app.vc_confirm_start_btn.invoke()
    assert seen and all(all(states) for states in seen)  # locked during the run
    assert not any(_disabled(w) for w in _voice_controls(app) if w is not app.vc_lang_combo)


def test_cancel_on_the_confirm_step_unlocks_the_controls(root, fakes, tmp_path):
    ref = tmp_path / "a.wav"
    _write_wav(str(ref), 5.0)
    app = _build(root, fakes)
    _engine(app, vct._ENGINE_OMNI, LONG, mode=vct._MODE_CLONE)
    app.vc_samples[:] = [str(ref)]
    _tick(app)
    app.vc_generate_btn.invoke()
    assert _disabled(app.vc_consent_check) and _disabled(app.vc_lang_combo)
    app.vc_confirm_cancel_btn.invoke()
    assert not _disabled(app.vc_consent_check) and not _disabled(app.vc_lang_combo)
    assert app.vc_consent_var.get() is True  # nothing un-ticked it meanwhile


# --------------------------------------- clips kept with the job (S08-9, B8)


def test_a_clone_job_keeps_its_clips_and_continues_after_a_restart(root, fakes, monkeypatch,
                                                                   tmp_path):
    import json

    from core import synthetic_audio

    log = tmp_path / "consent.jsonl"
    monkeypatch.setattr(synthetic_audio, "consent_log_path", lambda: log)
    session = tmp_path / "20261001-090000"
    ref = session / "sample_1.wav"
    _write_wav(str(ref), 5.0)

    # First window: the job stops after two pieces.
    calls = fakes["generate"]
    worker_cls = __import__("app.services.voice_clone_service",
                            fromlist=["VoiceCloneWorker"]).VoiceCloneWorker

    class StopAfterTwo(worker_cls):  # type: ignore[misc, valid-type]
        def generate(self, text: str, samples: list, output_path: str, **kw: Any) -> dict:
            result = super().generate(text, samples, output_path, **kw)
            if len(calls) == 2:
                app.vc_cancel_event.set()
            return result

    from app.services import voice_clone_service
    monkeypatch.setattr(voice_clone_service, "VoiceCloneWorker", StopAfterTwo)
    app = _build(root, fakes)
    _engine(app, vct._ENGINE_OMNI, LONG, mode=vct._MODE_CLONE)
    app.vc_samples[:] = [str(ref)]
    _tick(app)
    app.vc_generate_btn.invoke()
    app.vc_confirm_start_btn.invoke()
    assert app.vc_status_var.get().startswith("Cancelled.")
    job_dir = next(tmp_path.glob("job-*"))
    kept = sorted((job_dir / "references").iterdir())
    assert len(kept) == 1 and kept[0].read_bytes() == ref.read_bytes()
    # The pieces were spoken from the job's own copy, not the scratch clip.
    assert {tuple(c["samples"]) for c in calls} == {(str(kept[0]),)}

    # The scratch folder is swept and the app restarts: no clips in the list.
    ref.unlink()
    monkeypatch.setattr(voice_clone_service, "VoiceCloneWorker",
                        type("Plain", (worker_cls,), {}))
    app2 = _build(root, fakes)
    _engine(app2, vct._ENGINE_OMNI, LONG, mode=vct._MODE_CLONE)
    _tick(app2)
    app2.vc_generate_btn.invoke()
    assert app2.vc_samples == [str(kept[0])]
    assert "kept with the unfinished job" in app2.vc_status_var.get()
    assert app2.vc_consent_var.get() is False  # the user ticks for these clips
    _tick(app2)
    app2.vc_generate_btn.invoke()
    assert "Unfinished job found" in app2.vc_confirm_var.get()
    app2.vc_confirm_start_btn.invoke()
    assert app2.vc_status_var.get().startswith("Done")
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    assert records[0]["reference_sha256"] == [synthetic_audio.sha256_file(kept[0])]


# --------------------------------------------- Kokoro script check (S08-10)


@pytest.mark.parametrize("text", [
    "\u0633\u0644\u0627\u0645 \u062f\u0646\u06cc\u0627\u060c \u0627\u06cc\u0646 "
    "\u06cc\u06a9 \u0622\u0632\u0645\u0627\u06cc\u0634 \u0627\u0633\u062a.",  # Persian
    "\u041f\u0440\u0438\u0432\u0435\u0442, \u043c\u0438\u0440.",  # Russian
    "\uc548\ub155\ud558\uc138\uc694.",  # Korean
    "\u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e35\u0e04\u0e23\u0e31\u0e1a",  # Thai
])
def test_kokoro_refuses_a_script_none_of_its_voices_read(root, fakes, monkeypatch,
                                                         no_dialogs, text):
    from core import tts_kokoro

    downloads: list = []
    monkeypatch.setattr(tts_kokoro, "is_downloaded", lambda: False)
    monkeypatch.setattr(tts_kokoro, "download", lambda **_k: downloads.append(1))
    app = _build(root, fakes)
    _engine(app, vct._ENGINE_KOKORO, text)
    app.vc_generate_btn.invoke()
    assert [e[1] for e in no_dialogs] == ["Kokoro has no voice for this text"]
    assert "OmniVoice" in no_dialogs[0][2]
    assert fakes["kokoro"] == [] and downloads == []
    assert not app.vc_busy


@pytest.mark.parametrize("text", [
    "Hello there, this is fine.",
    "\u3053\u3093\u306b\u3061\u306f\u3002\u3053\u308c\u306f\u79c1\u306e\u58f0\u3067\u3059\u3002",
    "\u4f60\u597d\uff0c\u4e16\u754c\u3002",
    "\u0928\u092e\u0938\u094d\u0924\u0947 \u0926\u0941\u0928\u093f\u092f\u093e\u0964",
    "OK \u0633\u0644\u0627\u0645 then many English words follow in this sentence.",
])
def test_kokoro_accepts_the_scripts_its_voices_read(root, fakes, no_dialogs, text):
    app = _build(root, fakes)
    _engine(app, vct._ENGINE_KOKORO, text)
    app.vc_generate_btn.invoke()
    assert no_dialogs == []
    assert fakes["kokoro"] == [text]


# --------------------------------------------- sweep off the Tk thread (B13)


def test_the_scratch_sweep_runs_on_a_worker_thread(root, fakes, monkeypatch):
    from tkinter import ttk

    from core import _threads
    from tests.app.test_voice_clone_tab import _make_app

    started: list = []
    monkeypatch.setattr(_threads, "safe_thread", lambda fn, **k: started.append(k.get("name")))
    monkeypatch.setattr(vct, "_sweep_scratch_dirs",
                        lambda: pytest.fail("the sweep ran on the Tk thread"))
    timers: list = []
    app = _make_app(root)
    app.after = lambda _ms, fn: timers.append(fn)
    vct.build_voice_clone_tab(app, ttk.Frame(root))
    assert len(timers) == 1
    timers[0]()  # what Tk runs two seconds after the tab opens
    assert started == ["voice-clone-sweep"]


# ------------------------------------- another window runs the job (B3)


def test_start_over_is_refused_while_another_window_runs_the_job(root, fakes, monkeypatch):
    from core import tts_kokoro

    monkeypatch.setitem(tts_job.PIECE_CHARS, "kokoro", 600)
    _cancel_kokoro_after(monkeypatch, fakes, 1)
    app = _build(root, fakes)
    _engine(app, vct._ENGINE_KOKORO, LONG)
    _kokoro_job(app)
    app.vc_confirm_start_btn.invoke()
    monkeypatch.setattr(tts_kokoro, "generate", _plain_kokoro(fakes))
    app.vc_generate_btn.invoke()
    plan = app.vc_plan
    other = tts_job.Job(plan.job.folder.parent, plan.job.key, "kokoro", plan.job.pieces)
    with other.claimed():  # the other window is speaking it
        app.vc_confirm_restart_btn.invoke()
        assert "another window" in app.vc_status_var.get()
        assert plan.job.piece_path(0).is_file()
    assert _confirm_shown(app)
    app.vc_confirm_cancel_btn.invoke()


# ------------------------------------------------ fresh review (C2.62)


def test_a_recording_that_ends_during_the_confirm_step_keeps_record_off(root, fakes,
                                                                        monkeypatch):
    monkeypatch.setattr(vct, "_validate_and_add_sample", lambda *_a: None)
    app = _build(root, fakes)
    _engine(app, vct._ENGINE_OMNI, LONG, mode=vct._MODE_DESIGN)
    app.vc_recorder = types.SimpleNamespace(stop=lambda: "sample.wav")
    app.vc_generate_btn.invoke()
    assert _confirm_shown(app)
    vct._finish_recording(app)
    assert _disabled(app.vc_record_btn)
    app.vc_confirm_cancel_btn.invoke()
    assert not _disabled(app.vc_record_btn)


def test_continue_while_another_window_runs_the_job_says_so(root, fakes, monkeypatch,
                                                           no_dialogs):
    from core import tts_kokoro

    monkeypatch.setitem(tts_job.PIECE_CHARS, "kokoro", 600)
    _cancel_kokoro_after(monkeypatch, fakes, 1)
    app = _build(root, fakes)
    _engine(app, vct._ENGINE_KOKORO, LONG)
    _kokoro_job(app)
    app.vc_confirm_start_btn.invoke()
    monkeypatch.setattr(tts_kokoro, "generate", _plain_kokoro(fakes))
    app.vc_generate_btn.invoke()
    plan = app.vc_plan
    spoken = len(fakes["kokoro"])
    other = tts_job.Job(plan.job.folder.parent, plan.job.key, "kokoro", plan.job.pieces)
    with other.claimed():
        app.vc_confirm_start_btn.invoke()
    assert len(fakes["kokoro"]) == spoken
    assert [e[1] for e in no_dialogs] == ["Running in another window"]
    assert app.vc_status_var.get().startswith("Not started:")
    assert not app.vc_busy


def test_letters_that_name_no_script_do_not_refuse_a_text():
    from core import tts_kokoro

    assert tts_kokoro.unsupported_script("1\u00ba 2\u00aa 3\u00b5 \u3005") is None
