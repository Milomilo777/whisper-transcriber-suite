"""Translation wave 6: the Clone Your Voice / Text to Voice tab (app/widgets/voice_clone_tab.py).

The fixture ``tests/fixtures/i18n/i18n_wave_6_en.json`` was captured from the tab BEFORE its
strings went through the translation layer (app/i18n.py). It holds two parts:

- ``pure``: texts the tab's helper functions build (the long-text confirm step in each branch,
  the time hint, the kept-pieces note), made without any window;
- ``tab``: the tab built on a real Tk root (hidden) and driven through its states with the
  hermetic fakes of ``test_voice_clone_tab.py``: every widget text, section title and help
  text, each status line it shows, each error dialog and file dialog it opens.

In English every text must stay byte-identical; in the pseudo-locale every text the tab owns
must be marked (only texts from core/ and from other modules are allowed through, listed in
``_ALLOWED``). Saved settings and the voice the model is asked for must not depend on the
interface language.

Regenerate the fixture (only when a text is meant to change) with ``WTS_CAPTURE_I18N=1``.
"""
from __future__ import annotations

import dataclasses
import json
import os
import types
from pathlib import Path
from typing import Any, Callable

import pytest

from app.widgets import voice_clone_tab as vct
from core import tts_plan

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "i18n" / "i18n_wave_6_en.json"
CAPTURE = os.environ.get("WTS_CAPTURE_I18N") == "1"


# ----------------------------------------------------------------- windowless part

def _estimate(*, measured: bool = False, known: bool = True, size_high: int = 60_000_000) -> Any:
    return tts_plan.Estimate(
        units=4000.0, audio_low=600.0, audio_high=900.0,
        time_low=1200.0 if known else None, time_high=1800.0 if known else None,
        measured=measured, size_low=40_000_000, size_high=size_high)


def _disk(ok: bool = True) -> Any:
    # A relative folder: its drive is "" on every system, so the text is the same everywhere.
    return tts_plan.DiskCheck(folder="data", free_bytes=(10**12 if ok else 10**6),
                              need_bytes=60_000_000, margin_bytes=500_000_000)


def _job(done: int = 0, total: int = 5, finished: bool = False) -> Any:
    return types.SimpleNamespace(
        finished=finished, finished_audio_seconds=754.0, done=list(range(done)),
        spoken=lambda: list(range(total)), pending=lambda: list(range(total - done)),
        total_units=100.0, done_units=40.0, output_path=Path("out.wav"))


def _plan(engine: str = "kokoro", **kw: Any) -> Any:
    base: dict[str, Any] = dict(
        engine=engine, text="x", speed=1.0, device="cpu", version="", hardware="",
        installed=True, calibration=object(), estimate=_estimate(), disk=_disk())
    base.update(kw)
    return vct._JobPlan(**base)


def _pure_plans() -> dict[str, Any]:
    return {
        "unknown_not_installed": _plan(installed=False, calibration=None,
                                       estimate=_estimate(known=False)),
        "measured_omni_not_installed": _plan("omnivoice", installed=False,
                                             estimate=_estimate(measured=True)),
        "can_measure": _plan(calibration=None),
        "measure_failed": _plan(calibration=None, measure_failed=True),
        "resumed_measured": _plan(estimate=_estimate(measured=True), job=_job(2), resume_done=2),
        "resumed_unknown": _plan(estimate=_estimate(known=False), job=_job(2), resume_done=2),
        "finished": _plan(job=_job(5, finished=True)),
        "too_big": _plan(estimate=_estimate(size_high=tts_plan.MAX_WAV_BYTES + 1)),
        "no_disk": _plan(disk=_disk(ok=False)),
    }


def capture_pure() -> dict[str, Any]:
    plans = _pure_plans()
    out: dict[str, Any] = {"confirm": {k: vct._confirm_text(p) for k, p in plans.items()}}
    out["time_hint"] = {
        "measured": vct._time_hint(_plan(estimate=_estimate(measured=True))),
        "reference": vct._time_hint(_plan()),
        "unknown": vct._time_hint(_plan(estimate=_estimate(known=False))),
    }
    out["kept"] = [vct._kept_text((2, 5)), vct._kept_text((0, 5)), vct._kept_text(None)]
    return out


# ----------------------------------------------------------------- real-Tk part

def _new(root: Any, config: "dict | None" = None) -> tuple[Any, Any]:
    from tkinter import ttk

    from tests.app.test_voice_clone_tab import _make_app
    app = _make_app(root, config)
    frame = ttk.Frame(root)
    vct.build_voice_clone_tab(app, frame)
    frame.pack(fill="both", expand=True)
    root.update()
    return app, frame


def _watch(var: Any, log: list[str]) -> None:
    """Record every value the tab puts in ``var`` (the label shows the last one only)."""
    original = var.set

    def recording_set(value: Any) -> None:
        log.append(str(value))
        original(value)
    var.set = recording_set


def _set_engine(app: Any, kokoro: bool) -> None:
    app.vc_engine_combo.current(0 if kokoro else 1)  # by position: the label may be translated
    vct._sync_engine(app)


def _set_text(app: Any, text: str) -> None:
    app.vc_text.configure(state="normal")
    app.vc_text.delete("1.0", "end")
    app.vc_text.insert("1.0", text)
    vct._on_text_modified(app)


def _no_drive(text: str) -> str:
    """The confirm step names the drive of the output folder (it differs between systems)."""
    import re

    anchor = Path(tts_plan.output_root()).anchor
    if not anchor:
        return text
    return re.sub(r" on " + re.escape(anchor) + r"(?=\n|$)", " on <drive>", text)


def _key_texts(app: Any) -> dict[str, str]:
    return {
        "engine_state": str(app.vc_engine_state.cget("text")),
        "count": app.vc_count_var.get(),
        "speed": str(app.vc_speed_label.cget("text")),
        "start_btn": str(app.vc_confirm_start_btn.cget("text")),
    }


def capture_tab(mp: pytest.MonkeyPatch, root: Any, fakes: Any, tmp_path: Path) -> dict[str, Any]:
    """Drive the tab through its states and collect every text it shows."""
    from tkinter import filedialog

    from app.services import voice_clone_service
    from core import offline, recorder, synthetic_audio, tts_job, tts_kokoro, voice_clone

    from tests.app.i18n_walk import visible_texts

    out: dict[str, Any] = {}
    errors: list[list[Any]] = []
    sections: list[list[str]] = []
    dialogs: list[Any] = []
    patterns: list[Any] = []
    status: list[str] = []
    confirm: list[str] = []

    def record_error(_parent: Any, title: str, message: str, detail: "str | None" = None) -> None:
        errors.append([title, message, detail])

    real_section = vct.section_labelframe

    def record_section(parent: Any, title: str, help_text: Any, **kw: Any) -> Any:
        sections.append([title, help_text() if callable(help_text) else help_text])
        return real_section(parent, title, help_text, **kw)

    mp.setattr(vct, "show_error", record_error)
    mp.setattr(vct, "section_labelframe", record_section)
    mp.setattr(offline, "is_offline", lambda *_a, **_k: False)
    mp.setattr(vct, "open_async", lambda *_a, **_k: None)  # Preview never opens a player

    def new(config: "dict | None" = None) -> tuple[Any, Any]:
        app, frame = _new(root, config)
        _watch(app.vc_status_var, status)
        _watch(app.vc_confirm_var, confirm)
        return app, frame

    def mark(name: str) -> None:
        """Close one step: what it showed goes into ``out[name]``."""
        out[name] = {"status": list(status), "confirm": [_no_drive(t) for t in confirm],
                     "errors": [list(e) for e in errors]}
        status.clear()
        confirm.clear()
        errors.clear()

    # The whole tab, as built (Kokoro, the default), with every panel's widgets.
    app, frame = new()
    out["sections"] = list(sections)
    out["tree"] = [list(p) for p in visible_texts(frame)]
    out["kokoro_ready"] = _key_texts(app)
    mp.setattr(tts_kokoro, "is_downloaded", lambda: False)
    vct._sync_engine(app)
    out["kokoro_missing"] = _key_texts(app)
    mp.setattr(tts_kokoro, "is_downloaded", lambda: True)
    _set_engine(app, kokoro=False)
    out["omni_ready"] = _key_texts(app)
    mp.setattr(voice_clone, "is_available", lambda: False)
    vct._sync_engine(app)
    out["omni_missing"] = _key_texts(app)
    mp.setattr(voice_clone, "is_available", lambda: True)
    _set_engine(app, kokoro=True)
    command = str(app.vc_speed_scale.cget("command"))
    app.vc_speed_var.set(1.5)
    root.tk.call(command, "1.5")
    out["speed_moved"] = _key_texts(app)
    _set_text(app, "Hello there.")
    out["typed"] = _key_texts(app)
    _set_text(app, "")
    mark("build")

    # Refusals before anything starts.
    app.vc_generate_btn.invoke()
    mark("no_text")
    mp.setattr(tts_plan, "text_limit", lambda _cfg: 10)
    _set_text(app, "Hello there.")
    out["typed_over_limit"] = _key_texts(app)
    app.vc_generate_btn.invoke()
    mp.setattr(tts_plan, "text_limit", lambda _cfg: tts_plan.MAX_TEXT_CHARS)
    mark("text_too_long")
    _set_text(app, "مرحبا بالعالم هذا نص عربي طويل")
    app.vc_generate_btn.invoke()
    mark("kokoro_no_voice")
    _set_engine(app, kokoro=False)
    app.vc_mode_var.set(vct._MODE_DESIGN)
    vct._sync_engine(app)
    _set_text(app, "word " * 1100)
    app.vc_generate_btn.invoke()
    mark("design_too_long")
    app.vc_mode_var.set(vct._MODE_CLONE)
    vct._sync_engine(app)
    _set_text(app, "Hello there.")
    vct._generate(app)
    mark("clone_no_samples")
    app.vc_samples[:] = ["a.wav"]
    vct._generate(app)
    mark("clone_no_tick")

    # Reference clips: issues, the limit, removing one, recording.
    app.vc_samples[:] = []
    Issue = voice_clone.ReferenceIssue
    vct._finish_adding_sample(app, "a.wav", Issue("a.wav", "CORE: too quiet", blocking=True))
    vct._finish_adding_sample(app, "b.wav", Issue("b.wav", "CORE: a bit short"))
    app.vc_consent_check.invoke()
    vct._finish_adding_sample(app, "c.wav", None)
    app.vc_samples_listbox.selection_set(0)
    vct._remove_sample(app)
    app.vc_samples[:] = ["s"] * voice_clone.MAX_REFERENCE_SAMPLES
    vct._finish_adding_sample(app, "d.wav", None)
    vct._validate_and_add_sample(app, "e.wav")
    mark("samples")
    vct._record_sample(app)  # still at the limit
    app.vc_samples[:] = []
    mp.setattr(recorder, "mic_available", lambda: False)
    mp.setattr(recorder, "mic_availability_reason", lambda: "CORE: no input device")
    vct._record_sample(app)
    mp.setattr(recorder, "mic_available", lambda: True)

    class FailingRecorder:
        def __init__(self, **_k: Any) -> None: ...

        def start(self) -> None:
            raise RuntimeError("CORE: device busy")

    mp.setattr(recorder, "Recorder", FailingRecorder)
    vct._record_sample(app)

    class BrokenRecorder(FailingRecorder):
        def start(self) -> None: ...

        def stop(self) -> str:
            raise RuntimeError("CORE: stream lost")

    mp.setattr(recorder, "Recorder", BrokenRecorder)
    vct._record_sample(app)
    vct._tick_recording(app, 0)
    mark("recording")

    # Kept clips offered back for an earlier job of this text.
    for finished in (True, False):
        mp.setattr(tts_job, "find_kept_references",
                   lambda *_a, finished=finished, **_k: (["k.wav"], finished))
        app.vc_samples[:] = []
        vct._offer_kept_clips(app, "Hello there.", 1.0)
    mp.setattr(tts_job, "find_kept_references", lambda *_a, **_k: None)
    mark("kept_clips")

    # A short Kokoro job, start to finish.
    app, frame = new()
    _set_text(app, "Hello there.")
    app.vc_generate_btn.invoke()
    mark("kokoro_short")
    app.vc_preview_btn.invoke()
    mark("kokoro_preview")

    # A long Kokoro job: the confirm step, the measuring run, piece by piece.
    def fake_run(job: Any, speak: Any, *, on_progress: Any = None, on_joined: Any = None,
                 **_k: Any) -> Any:
        on_progress(tts_job.Progress(0, 3, 0.0, None))
        on_progress(tts_job.Progress(1, 3, 0.4, 125.0))
        out_path = tmp_path / "joined.wav"
        out_path.write_bytes(b"RIFF")
        if on_joined is not None:
            on_joined(out_path)
        return tts_job.RunResult(str(out_path), 300.0, 3, 4000.0, 300.0, 90.0)

    mp.setattr(tts_job, "run", fake_run)
    from tests.app.test_voice_clone_tab import LONG
    _set_text(app, LONG)
    app.vc_generate_btn.invoke()
    out["confirm_measure"] = _key_texts(app)
    app.vc_confirm_measure_btn.invoke()
    out["confirm_measured"] = _key_texts(app)
    app.vc_confirm_start_btn.invoke()
    mark("kokoro_long")
    app, frame = new()
    _set_text(app, LONG + " Again.")
    app.vc_generate_btn.invoke()
    app.vc_confirm_cancel_btn.invoke()
    mark("confirm_cancelled")

    def failing_measure(**_k: Any) -> Any:
        raise RuntimeError("CORE: no audio device")

    # A fresh speed store each time, so the confirm step offers the measuring run again.
    real_measure = tts_kokoro.measure_speed
    mp.setattr(tts_plan, "calibration_path", lambda: tmp_path / "speed-2.json")
    mp.setattr(tts_kokoro, "measure_speed", failing_measure)
    _set_text(app, LONG + " Once more.")
    app.vc_generate_btn.invoke()
    app.vc_confirm_measure_btn.invoke()
    app.vc_confirm_cancel_btn.invoke()
    mp.setattr(tts_plan, "calibration_path", lambda: tmp_path / "speed-3.json")
    mp.setattr(tts_kokoro, "measure_speed", real_measure)
    real_record = tts_plan.record_measurement
    mp.setattr(tts_plan, "record_measurement", lambda *_a, **_k: None)
    _set_text(app, LONG + " And again.")
    app.vc_generate_btn.invoke()
    app.vc_confirm_measure_btn.invoke()
    app.vc_confirm_cancel_btn.invoke()
    mp.setattr(tts_plan, "record_measurement", real_record)
    mp.setattr(tts_plan, "calibration_path", lambda: tmp_path / "speed.json")
    mark("measure_failed")

    # The confirm step for a finished and for an unfinished job.
    app, frame = new()
    for name, plan in (("finished", _plan(job=_job(5, finished=True))),
                       ("resumed", _plan(job=_job(2), resume_done=2))):
        app.vc_plan = plan
        vct._show_confirm(app)
        out[f"confirm_{name}"] = _key_texts(app)
        vct._close_confirm(app)
    for plan in (_plan(estimate=_estimate(size_high=tts_plan.MAX_WAV_BYTES + 1)),
                 _plan(disk=_disk(ok=False)), _plan(calibration=None),
                 _plan(estimate=_estimate(measured=True))):
        app.vc_plan = plan
        vct._show_confirm(app)
        vct._close_confirm(app)
    finished_plan = _plan(job=_job(5, finished=True))
    app.vc_plan = finished_plan
    vct._use_finished(app, finished_plan)
    mark("confirm_variants")

    # Start over: no room, then another window holding the job.
    app, frame = new()
    job = _job(2)
    job.parts_dir = tmp_path

    def busy_discard() -> None:
        raise tts_job.JobBusy("CORE: another window runs this job.")

    job.discard = busy_discard
    app.vc_plan = _plan(job=job, resume_done=2)
    app.vc_confirm_open = True
    real_check = tts_plan.check_disk
    mp.setattr(tts_plan, "check_disk", lambda *_a, **_k: _disk(ok=False))
    vct._confirm_restart(app)
    mp.setattr(tts_plan, "check_disk", real_check)
    vct._confirm_restart(app)
    app.vc_confirm_open = False
    mark("start_over")

    # OmniVoice: a short run, the install, a failed install offline, a stuck worker.
    app, frame = new()
    _set_engine(app, kokoro=False)
    app.vc_mode_var.set(vct._MODE_AUTO)
    vct._sync_engine(app)
    _set_text(app, "Hello there.")
    app.vc_generate_btn.invoke()
    mark("omni_short")

    def model_loading_worker(*_a: Any, **_k: Any) -> Any:
        worker = types.SimpleNamespace(start=lambda: None, is_running=lambda: True,
                                       stop=lambda: None)

        def generate(text: str, samples: list, output_path: str, **kw: Any) -> dict:
            kw["on_model_loading"]()
            raise RuntimeError("CORE: out of memory")
        worker.generate = generate
        return worker

    mp.setattr(voice_clone_service, "VoiceCloneWorker", model_loading_worker)
    app.vc_worker = None
    app.vc_generate_btn.invoke()
    mark("omni_failed")
    mp.setattr(voice_clone, "is_available", lambda: False)
    mp.setattr(voice_clone, "ensure_installed", lambda **_k: False)
    app.vc_generate_btn.invoke()
    mp.setattr(offline, "is_offline", lambda *_a, **_k: True)
    app.vc_generate_btn.invoke()
    mp.setattr(offline, "is_offline", lambda *_a, **_k: False)
    mp.setattr(voice_clone, "is_available", lambda: True)
    mark("omni_install_failed")
    app.vc_worker = types.SimpleNamespace(is_running=lambda: False, wait_for_exit=lambda: False)
    app.vc_generate_btn.invoke()
    mark("omni_worker_stuck")

    # A piece-by-piece clone whose consent record cannot be written.
    app, frame = new()
    _set_engine(app, kokoro=False)
    app.vc_mode_var.set(vct._MODE_CLONE)
    vct._sync_engine(app)
    clip = tmp_path / "ref.wav"
    from tests.app.test_voice_clone_tab import _write_wav
    _write_wav(str(clip), 5.0)
    app.vc_samples[:] = [str(clip)]
    app.vc_consent_check.invoke()

    def no_record(*_a: Any, **_k: Any) -> None:
        raise OSError("CORE: read-only")

    mp.setattr(synthetic_audio, "append_consent_record", no_record)
    _set_text(app, LONG + " Cloned.")
    mp.setattr(voice_clone_service, "VoiceCloneWorker",
               lambda *_a, **_k: types.SimpleNamespace(start=lambda: None,
                                                       is_running=lambda: True))
    app.vc_worker = None
    app.vc_generate_btn.invoke()
    if app.vc_confirm_open:
        app.vc_confirm_start_btn.invoke()
    mark("omni_job_warning")

    # Results reported straight to the tab.
    vct._generate_failed(app, "CORE: busy elsewhere", busy=True)
    vct._generate_failed(app, "CORE: crashed", kept=(2, 5))
    vct._generate_failed(app, "CORE: crashed")
    vct._generate_cancelled(app, kept=(2, 5))
    vct._generate_done(app, {"output_path": "", "elapsed_seconds": 3.0})
    vct._generate_done(app, {"output_path": "", "elapsed_seconds": 3.0, "audio_seconds": 7.0,
                             "units_run": 10, "warning": "x"})
    mark("results")

    # File dialogs and playing / saving the result.
    def record_dialog(**kw: Any) -> str:
        dialogs.append([kw.get("title"), [t[0] for t in kw.get("filetypes", [])]])
        patterns.append([t[1] for t in kw.get("filetypes", [])])
        return ""

    mp.setattr(filedialog, "askopenfilename", record_dialog)
    mp.setattr(filedialog, "asksaveasfilename", record_dialog)
    vct._load_sample(app)
    app.vc_last_output = str(clip)
    vct._save(app)
    mp.setattr(filedialog, "asksaveasfilename", lambda **_k: str(tmp_path / "copy.wav"))
    import shutil

    def no_copy(*_a: Any) -> None:
        raise OSError("CORE: disk full")

    mp.setattr(shutil, "copyfile", no_copy)
    vct._save(app)
    mp.setattr(vct, "open_async", lambda _p, _w, done: done(RuntimeError("CORE: no player")))
    vct._play(app)
    out["file_dialogs"] = dialogs
    out["raw_file_patterns"] = patterns  # not text: the file name patterns
    mark("files")
    return out


# ----------------------------------------------------------------- tests

def _marked(text: str) -> bool:
    """``is_pseudo_marked`` that also accepts a marked text inside a marked text (a translated
    reason placed into a translated sentence): innermost segments are removed first."""
    import re

    from tests.app.i18n_walk import is_pseudo_marked

    inner = re.compile(r"\[[^\[\]]*? ~+\]")
    while True:
        stripped = inner.sub("", text)
        if stripped == text:
            return is_pseudo_marked(text)
        text = stripped


# Texts that do not belong to this tab's own strings, with the reason.
_ALLOWED_PREFIX = "CORE: "  # messages the fakes pass in as core/ would (engine errors, issues)


def _allowed(text: str, app: Any) -> bool:
    from app.domain.languages import SUBTITLE_LANGUAGES
    from core import offline, tts_kokoro

    if text.startswith(_ALLOWED_PREFIX):
        return True
    if text in {v.label for v in tts_kokoro.VOICES}:
        return True  # Kokoro voice names come from core/tts_kokoro.py
    if text in {n for n, _c in SUBTITLE_LANGUAGES}:
        return True  # language names come from app/domain/languages.py (another wave)
    if text == offline.message("downloading the speech model software"):
        return True  # the offline sentence is built in core/offline.py
    return False


def _all_texts(data: Any) -> list[str]:
    if isinstance(data, str):
        return [data]
    if isinstance(data, dict):
        return [t for k, v in data.items() if not k.startswith("raw_") for t in _all_texts(v)]
    if isinstance(data, list):
        if len(data) == 2 and isinstance(data[0], str) and data[0].startswith("."):
            return [data[1]]  # [widget path, text]
        return [t for v in data for t in _all_texts(v)]
    return []


def test_pure_english_texts_match_the_capture_made_before_translation() -> None:
    from app import i18n
    i18n.set_language("en")
    got = capture_pure()
    if CAPTURE:
        data = json.loads(FIXTURE.read_text(encoding="utf-8")) if FIXTURE.exists() else {}
        data["pure"] = got
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                           encoding="utf-8", newline="\n")
    assert got == json.loads(FIXTURE.read_text(encoding="utf-8"))["pure"]


def test_pure_pseudo_locale_marks_every_text() -> None:
    from app import i18n
    from tests.app.i18n_walk import is_pseudo_marked
    try:
        assert i18n.set_language(i18n.PSEUDO_LOCALE) == i18n.PSEUDO_LOCALE
        got = capture_pure()
    finally:
        i18n.set_language("en")
    texts = [t for t in _all_texts(got) if t.strip()]
    assert texts
    assert [t for t in texts if not is_pseudo_marked(t)] == []


def test_tab_english_texts_match_the_capture_made_before_translation(
        monkeypatch, root, fakes, tmp_path) -> None:
    from app import i18n
    i18n.set_language("en")
    got = capture_tab(monkeypatch, root, fakes, tmp_path)
    if CAPTURE:
        data = json.loads(FIXTURE.read_text(encoding="utf-8")) if FIXTURE.exists() else {}
        data["tab"] = got
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                           encoding="utf-8", newline="\n")
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))["tab"]
    for key in expected:
        assert got.get(key) == expected[key], key
    assert sorted(got) == sorted(expected)


def test_tab_pseudo_locale_leaves_no_text_untranslated(monkeypatch, root, fakes, tmp_path) -> None:
    from app import i18n
    from tests.app.i18n_walk import is_pseudo_marked
    try:
        assert i18n.set_language(i18n.PSEUDO_LOCALE) == i18n.PSEUDO_LOCALE
        got = capture_tab(monkeypatch, root, fakes, tmp_path)
    finally:
        i18n.set_language("en")
    texts = [t for t in _all_texts(got) if isinstance(t, str) and t.strip()]
    assert len(texts) > 100
    left = sorted({t for t in texts if not _marked(t) and not _allowed(t, None)})
    assert left == []
    # The fakes' core messages still reach the person, inside the marked sentence or alone.
    assert any("CORE: busy elsewhere" in t for t in texts)


# ----------------------------------------------------------------- stored values and lookups

def _drive_settings(root: Any) -> dict[str, Any]:
    """Pick Omni, design mode, a few design attributes and a language by POSITION, the way a
    person clicks them; return what is saved and what the model is asked for."""
    config: dict[str, Any] = {}
    app, _frame = _new(root, config)
    _set_engine(app, kokoro=False)
    app.vc_mode_var.set(vct._MODE_DESIGN)
    vct._sync_engine(app)
    gender, age, pitch, accent = app.vc_design_widgets[:4]
    gender.current(2)
    age.current(4)
    pitch.current(1)
    accent.current(3)
    app.vc_whisper_var.set(True)
    instruct = vct._design_instruct(app)
    app.vc_lang_combo.current(0)
    auto_code = vct._language_code(app)
    names = list(app.vc_lang_combo.cget("values"))
    app.vc_lang_combo.current(names.index("Japanese"))
    japanese = vct._omni_language(app)
    kokoro_after = (vct._is_kokoro(app), )
    _set_engine(app, kokoro=True)
    kokoro_after += (vct._is_kokoro(app), )
    _set_engine(app, kokoro=False)
    gender.current(0)
    any_instruct = vct._design_instruct(app)
    settings = vct._voice_settings(app, "omnivoice")
    return {"config": json.loads(json.dumps(config)), "instruct": instruct,
            "any_instruct": any_instruct, "auto_code": auto_code, "japanese": japanese,
            "kokoro": list(kokoro_after), "settings": settings}


def test_saved_settings_and_model_input_do_not_depend_on_the_language(root, fakes) -> None:
    from app import i18n
    i18n.set_language("en")
    english = _drive_settings(root)
    try:
        i18n.set_language(i18n.PSEUDO_LOCALE)
        pseudo = _drive_settings(root)
    finally:
        i18n.set_language("en")
    assert english["config"]["voice_clone"] == {"engine": "omnivoice", "mode": "design",
                                                "kokoro_voice": english["config"]["voice_clone"]["kokoro_voice"]}
    assert english["instruct"] and "female" in english["instruct"]
    assert english["auto_code"] == "" and english["japanese"] == "ja"
    assert english["kokoro"] == [False, True]
    assert pseudo == english


def test_saved_engine_is_shown_in_the_pseudo_locale(root, fakes) -> None:
    from app import i18n
    try:
        i18n.set_language(i18n.PSEUDO_LOCALE)
        app, _frame = _new(root, {"voice_clone": {"engine": "omnivoice", "mode": "auto"}})
        assert not vct._is_kokoro(app)
        assert app.vc_engine_var.get() == app.vc_engine_combo.cget("values")[1]
        app2, _frame2 = _new(root, {})
        assert vct._is_kokoro(app2)
    finally:
        i18n.set_language("en")


def test_every_design_value_has_a_marked_label() -> None:
    """A design attribute the model knows but the tab has no label for would show in English."""
    from app import i18n
    from core import voice_clone as vc
    from tests.app.i18n_walk import is_pseudo_marked
    labels = getattr(vct, "_DESIGN_LABELS", None)
    if labels is None:
        pytest.skip("the tab is not converted yet")
    values = vc.DESIGN_GENDERS + vc.DESIGN_AGES + vc.DESIGN_PITCHES + vc.DESIGN_ACCENTS
    assert sorted(labels) == sorted(values)
    try:
        i18n.set_language(i18n.PSEUDO_LOCALE)
        assert all(is_pseudo_marked(vct._design_label(v)) for v in values)
    finally:
        i18n.set_language("en")
    assert [vct._design_label(v) for v in values] == [v[:1].upper() + v[1:] for v in values]


# Real Tk root and the hermetic fakes of the voice-tab tests (a hidden window; never local).
from tests.app.test_voice_clone_tab import fakes, root  # noqa: E402,F401
