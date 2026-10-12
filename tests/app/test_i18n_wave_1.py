"""Translation wave 1: ten dialogs keep their English byte for byte and go through app/i18n.py.

The dialogs: quick start, model hub folder, model download, search, model advisor, model
loading, shareable page, English-only model, statistics and the subtitles-or-transcribe question.

``tests/fixtures/i18n/i18n_wave_1_en.json`` was captured from these dialogs BEFORE their
strings went through the translation layer. It holds, per state a person can reach, the texts
the dialog shows (window titles, labels, buttons, combobox values, tree headings) plus the
title and text of every message box and file dialog it opens, and the texts of the helper
functions that build sentences (``advisor_summary``, ``EnglishOnlyPrompt``, ...).

* ``test_*_english_*``: built in English, every text equals the capture.
* ``test_*_pseudo_*``: built in the ``qps-ploc`` pseudo-locale, every text is marked, except
  values that come from core/ or from the person's data (written ``«...»`` in the fakes below,
  so they are easy to tell apart) and the language names of ``app.domain.languages``.

To re-capture (only when an English text is meant to change): create the empty file
``tests/fixtures/i18n/i18n_wave_1_en.capture`` (or set ``WTS_CAPTURE_I18N=1``) and run
``test_tk_english_texts_match_the_capture`` on a machine with a display; it writes the fixture.
The Tk tests need a real Tk root; the windowless ones run anywhere.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterator

import pytest

from app import i18n
from tests.app.i18n_walk import is_pseudo_marked

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "i18n"
FIXTURE = FIXTURE_DIR / "i18n_wave_1_en.json"
CAPTURE_SENTINEL = FIXTURE_DIR / "i18n_wave_1_en.capture"
CAPTURE_ENV = "WTS_CAPTURE_I18N"

States = dict[str, list[str]]

# Values a fake hands in for core/ or the person's data are written «...».
_DATA = re.compile(r"«[^»]*»")


def _cuda(**kw: Any) -> Any:
    from core import hardware as hw
    return hw.CudaStatus(**{"usable": False, "gpu_present": False, **kw})


@pytest.fixture
def english() -> Iterator[None]:
    i18n.set_language("en")
    try:
        yield
    finally:
        i18n.set_language("en")


@pytest.fixture
def pseudo() -> Iterator[None]:
    assert i18n.set_language(i18n.PSEUDO_LOCALE) == i18n.PSEUDO_LOCALE
    try:
        yield
    finally:
        i18n.set_language("en")


# ----------------------------------------------------------------------------- windowless

def pure_states(tmp_path: Path) -> States:
    """Texts built by helper functions (no Tk): every branch of each."""
    from app.dialogs import english_only_model as eo
    from app.dialogs import model_advisor as ma
    from app.dialogs import quick_start as qs
    from app.dialogs import share_page as sp

    states: States = {}
    gpu = _cuda(usable=True, gpu_present=True, gpu_name="«RTX 9090»", memory_mb=8192)
    nameless_gpu = _cuda(usable=True, gpu_present=True)
    broken_gpu = _cuda(gpu_present=True, gpu_name="«GTX 9»")
    nameless_broken = _cuda(gpu_present=True)
    cpu = _cuda()
    summary: list[str] = []
    for status in (gpu, nameless_gpu, broken_gpu, nameless_broken, cpu):
        for cores, ram in ((8, 16.0), (0, 0.0), (4, 0.0), (0, 8.0)):
            for platform in ("win32", "darwin"):
                summary.append(ma.advisor_summary(status, cores=cores, ram_gb=ram, platform=platform))
    summary.append(ma.advisor_summary(cpu, cores=8, ram_gb=16.0, force_cpu=True))
    summary.append(ma.advisor_summary(cpu, cores=0, ram_gb=0.0, force_cpu=True))
    states["advisor_summary"] = summary

    prompts: list[str] = []
    for prompt in (
        eo.EnglishOnlyPrompt("«tiny.en»", "«Persian»", "«small»", "«Reason.»", "«500 MB»", True),
        eo.EnglishOnlyPrompt("«tiny.en»", "", "«small»", "«Reason.»", "«500 MB»", False),
        eo.EnglishOnlyPrompt("«tiny.en»", "«Persian»", "«small»", "«Reason.»", "", False),
    ):
        prompts += [prompt.headline(), prompt.problem(), prompt.recommendation()]
    states["english_only_prompt"] = prompts

    states["format_per_minute"] = [qs.format_per_minute(s) for s in (4.8, 28.2, 57.6, 85.2, 120.0)]
    hardware: list[str] = []
    for force in (False, True):
        fake_self = SimpleNamespace(_force_cpu=force)
        for status in (gpu, nameless_gpu, broken_gpu, nameless_broken, cpu):
            for cores in (8, 0):
                hardware.append(qs.QuickStartDialog._hardware_text(fake_self, status, cores))  # type: ignore[arg-type]
    states["quick_start_hardware"] = hardware
    states["quick_start_languages"] = [qs.language_options()[0][0]]

    states["share_privacy_note"] = [sp.privacy_note(str(tmp_path / "«My talk».mp4")), sp.privacy_note(None)]
    errors: list[str] = []
    for name, payload in (("dict.json", {"a": 1}), ("ints.json", [1, 2])):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        try:
            sp.load_transcript(str(path))
        except ValueError as e:
            errors.append(str(e))
    states["share_load_errors"] = errors
    return states


# ----------------------------------------------------------------------------- Tk

class Calls:
    """Message boxes, file dialogs and notices a dialog opens: [kind, title, text]."""

    def __init__(self, mp: pytest.MonkeyPatch) -> None:
        from tkinter import filedialog, messagebox

        self.rows: list[list[str]] = []
        self.answer = False
        for kind in ("showerror", "showwarning", "showinfo"):
            mp.setattr(messagebox, kind, self._box(kind))
        mp.setattr(messagebox, "askyesno", self._box("askyesno"))
        mp.setattr(filedialog, "askdirectory", self._file("askdirectory"))
        mp.setattr(filedialog, "asksaveasfilename", self._file("asksaveasfilename"))

    def _box(self, kind: str) -> Callable[..., Any]:
        def box(title: str = "", message: str = "", **_k: Any) -> bool:
            self.rows.append([kind, str(title), str(message)])
            return self.answer
        return box

    def _file(self, kind: str) -> Callable[..., str]:
        def ask(**k: Any) -> str:
            types = [str(label) for label, _pattern in k.get("filetypes", [])]
            self.rows.append([kind, str(k.get("title", "")), *types])
            return ""
        return ask

    def take(self) -> list[str]:
        out = [" | ".join(row) for row in self.rows]
        self.rows.clear()
        return out


def _texts(widget: Any) -> list[str]:
    from tkinter import ttk

    from tests.app.i18n_walk import visible_texts

    out = [text for _path, text in visible_texts(widget)]

    def trees(w: Any) -> Iterator[Any]:
        for child in w.winfo_children():
            if isinstance(child, ttk.Treeview):
                yield child
            yield from trees(child)

    for tree in trees(widget):
        for col in tree["columns"]:
            out.append(str(tree.heading(col, "text")))
    return out


def _new_toplevel(root: Any, before: set[str]) -> Any:
    found = [w for w in root.winfo_children()
             if w.winfo_class() == "Toplevel" and str(w) not in before]
    assert len(found) == 1, found
    return found[0]


def _children(root: Any) -> set[str]:
    return {str(w) for w in root.winfo_children()}


def _modal(root: Any, mp: pytest.MonkeyPatch, states: States, key: str,
           act: Callable[[Any], None] | None = None) -> None:
    """Replace ``root.wait_window``: snapshot the modal window, then act on it or close it."""
    def wait_window(window: Any = None) -> None:
        states[key] = _texts(window)
        if act is not None:
            act(window)
        if window.winfo_exists():
            window.destroy()
    mp.setattr(root, "wait_window", wait_window, raising=False)


def tk_states(root: Any, mp: pytest.MonkeyPatch, tmp_path: Path) -> States:
    """Every dialog of wave 1 in every state the fakes reach, plus its message boxes."""
    import core.model_manager as mm
    import core.search as core_search
    from core import _threads, hub, offline
    from app.dialogs import caption_choice as cc
    from app.dialogs import english_only_model as eo
    from app.dialogs import hub_setup as hs
    from app.dialogs import model_advisor as ma
    from app.dialogs import model_download as md
    from app.dialogs import model_loading as ml
    from app.dialogs import quick_start as qs
    from app.dialogs import search_dialog as sd
    from app.dialogs import share_page as sp
    from app.dialogs import statistics as st

    states: States = {}
    calls = Calls(mp)
    mp.setattr(hub, "default_hub_folder", lambda: "X:\\«hub»")
    mp.setattr(mm, "catalog_entry_info", lambda _c, slug: {"label": f"«{slug}» — fast"})
    mp.setattr(mm, "approx_download_size_text",
               lambda _c, slug: "" if slug.startswith("tiny") else "«about 1 GB»")
    mp.setattr(mm, "catalog_models",
               lambda _c: [("tiny", "«Tiny»"), ("small", "«Small»"), ("large-v3", "«Large v3»")])
    mp.setattr(mm, "model_downloaded", lambda _c, slug: slug == "small")
    mp.setattr(offline, "is_offline", lambda _c=None: False)

    # --- caption choice
    for kind in ("manual", "auto"):
        _modal(root, mp, states, f"caption_choice_{kind}")
        cc.ask_caption_choice(root, kind=kind, language="«French»")

    # --- English-only model
    prompt = eo.EnglishOnlyPrompt("«tiny.en»", "«Persian»", "«small»", "«Reason.»", "«500 MB»", False)
    _modal(root, mp, states, "english_only")
    eo.ask_english_only(root, prompt)

    # --- shareable page
    media = tmp_path / "«talk».mp4"
    media.write_bytes(b"x")
    _modal(root, mp, states, "share_options_media")
    sp.ask_options(root, media_path=str(media))
    _modal(root, mp, states, "share_options_no_media")
    sp.ask_options(root, media_path=None)
    sp.save_shareable_page(root, segments=[{"text": " "}], media_path=None, json_path="x.json")
    states["share_no_text"] = calls.take()

    def press(label: str) -> Callable[[Any], None]:
        def act(window: Any) -> None:
            from tkinter import ttk

            def walk(w: Any) -> Iterator[Any]:
                for c in w.winfo_children():
                    yield c
                    yield from walk(c)
            buttons = [w for w in walk(window) if isinstance(w, ttk.Button)]
            # creation order: Cancel, "Save and open in browser", "Save..."
            {"save": buttons[2], "open": buttons[1]}[label].invoke()
        return act

    json_path = tmp_path / "«t».json"
    _modal(root, mp, states, "_ignored", press("save"))
    sp.save_shareable_page(root, segments=[{"text": "hi"}], media_path=None, json_path=str(json_path))
    states["share_save_dialog"] = calls.take()
    mp.setattr(sp.filedialog, "asksaveasfilename", lambda **_k: str(json_path))
    _modal(root, mp, states, "_ignored", press("save"))
    sp.save_shareable_page(root, segments=[{"text": "hi"}], media_path=None, json_path=str(json_path))
    states["share_same_file"] = [row.replace(str(json_path), "<path>") for row in calls.take()]
    out_path = tmp_path / "«out».html"
    mp.setattr(sp.filedialog, "asksaveasfilename", lambda **_k: str(out_path))

    def refuse(*_a: Any, **_k: Any) -> None:
        raise OSError("«disk full»")

    mp.setattr(sp.html_transcript, "write_page", refuse)
    _modal(root, mp, states, "_ignored", press("save"))
    sp.save_shareable_page(root, segments=[{"text": "hi"}], media_path=None, json_path=str(json_path))
    states["share_write_error"] = calls.take()
    mp.setattr(sp, "open_async", lambda path, _m, done: done(OSError("«no browser»")))
    sp.open_in_browser("«page».html", root)
    states["share_open_error"] = calls.take()
    states.pop("_ignored", None)

    # --- statistics
    shown: list[str] = []
    mp.setattr(st, "notify", lambda _w, text, kind="info": shown.append(f"notify {kind} | {text}"))
    mp.setattr(st, "show_error", lambda _w, title, message, detail="", **_k: shown.append(
        f"show_error | {title} | {message} | {detail}"))
    mp.setattr(root, "history", None, raising=False)
    st.show_statistics(root)  # type: ignore[arg-type]

    class BrokenHistory:
        def stats(self) -> dict[str, Any]:
            raise OSError("«locked»")

    mp.setattr(root, "history", BrokenHistory(), raising=False)
    st.show_statistics(root)  # type: ignore[arg-type]
    states["statistics_errors"] = shown
    for key, langs in (("statistics_empty", []), ("statistics_full", [("«fa»", 3), ("«en»", 1)])):
        stats = {"downloads_finished": 2, "downloads_total": 3, "transcriptions_finished": 4,
                 "transcriptions_total": 5, "transcription_minutes": 12.5, "top_languages": langs}
        mp.setattr(root, "history", SimpleNamespace(stats=lambda s=stats: s), raising=False)
        before = _children(root)
        st.show_statistics(root)  # type: ignore[arg-type]
        top = _new_toplevel(root, before)
        states[key] = _texts(top)
        top.destroy()

    # --- model loading
    dlg = ml.ModelLoadingDialog(root)
    states["model_loading"] = _texts(dlg)
    dlg.cancel()

    # --- model advisor
    mp.setattr(ma.ModelAdvisorDialog, "_check", lambda self: None)
    app = SimpleNamespace(app_config={"whisper_model": "small"}, transcribe_model_var=None)
    adv = ma.ModelAdvisorDialog(root, app)  # type: ignore[arg-type]
    states["advisor_checking"] = _texts(adv)
    adv._result["error"] = RuntimeError("«no driver»")
    adv._poll()
    states["advisor_error"] = _texts(adv)
    adv.destroy()
    gpu = _cuda(usable=True, gpu_present=True, gpu_name="«RTX 9090»", memory_mb=8192)
    picks = [ma._hw.ModelPick("fastest", "small", "«fast reason»"),
             ma._hw.ModelPick("accurate", "large-v3", "«accurate reason»"),
             ma._hw.ModelPick("accurate", "tiny", "«tiny reason»"),
             ma._hw.ModelPick("fastest", "not-in-catalog", "«skipped»")]
    adv = ma.ModelAdvisorDialog(root, app)  # type: ignore[arg-type]
    adv._show(gpu, picks, 16.0, 8)
    states["advisor_two_picks"] = _texts(adv)
    adv.destroy()
    mp.setattr(offline, "is_offline", lambda _c=None: True)
    adv = ma.ModelAdvisorDialog(root, app)  # type: ignore[arg-type]
    adv._show(gpu, [ma._hw.ModelPick("fastest", "large-v3", "«only reason»")], 16.0, 8)
    states["advisor_one_pick_offline"] = _texts(adv)
    adv.destroy()
    mp.setattr(offline, "is_offline", lambda _c=None: False)
    adv = ma.ModelAdvisorDialog(root, app)  # type: ignore[arg-type]
    adv._show(gpu, [ma._hw.ModelPick("fastest", "not-in-catalog", "«x»")], 16.0, 8)
    states["advisor_none"] = _texts(adv)
    adv.destroy()

    # --- model download
    mp.setattr(md.ModelDownloadDialog, "_start_worker", lambda self: None)
    mp.setattr(md, "time", SimpleNamespace(time=lambda: 1000.0))

    def download() -> Any:
        return md.ModelDownloadDialog(root)

    dl = download()
    states["download_open"] = _texts(dl)
    dl._apply_progress({"percent": 10, "total": 3 * 1024 ** 3, "downloaded": 1024 ** 3,
                        "speed": 2 * 1024 ** 2, "remaining": 75})
    states["download_progress"] = _texts(dl)
    dl._apply_progress({"total": 2048})
    dl.cancel()
    dl._poll()
    states["download_cancelling"] = _texts(dl)
    dl.destroy()
    for reason in ("missing", "permission"):
        dl = download()
        dl.not_writable_dir = "X:\\«models»"
        dl.not_writable_reason = reason
        dl.events.put(("done", None))
        dl._poll()
        states[f"download_not_writable_{reason}"] = calls.take()
    dl = download()
    dl.error = "«disk full»"
    dl.events.put(("done", None))
    dl._poll()
    states["download_failed"] = calls.take()
    dl = download()
    dl.not_writable_dir = "X:\\«models»"
    calls.answer = True
    mp.setitem(sys.modules, "app.dialogs.hub_setup", None)
    dl.events.put(("done", None))
    dl._poll()
    states["download_picker_failed"] = [re.sub(r"(picker: ).*", r"\1<import error>", row)
                                        for row in calls.take()]
    calls.answer = False
    mp.setitem(sys.modules, "app.dialogs.hub_setup", hs)
    dl = download()
    mp.setattr(md.ModelDownloadDialog, "_handle_not_writable", lambda self, _d: True)
    dl.not_writable_dir = "X:\\«models»"
    dl.events.put(("done", None))
    dl._poll()
    states["download_retrying"] = _texts(dl)
    dl.destroy()

    # --- hub folder
    hub_dlg = hs.HubSetupDialog(root, {}, save=lambda _c: None)
    states["hub_open"] = _texts(hub_dlg)
    hub_dlg._browse()
    states["hub_browse"] = calls.take()

    def no_dirs(*_a: Any, **_k: Any) -> None:
        raise OSError("«denied»")

    mp.setattr(hs, "os", SimpleNamespace(makedirs=no_dirs, path=os.path, close=os.close, unlink=os.unlink))
    hub_dlg._probe_writable("X:\\«readonly»")
    states["hub_not_writable"] = calls.take()
    mp.setattr(hs, "os", os)
    hub_dlg._on_cancel()

    # --- search
    mp.setattr(_threads, "safe_thread", lambda target, args=(), kwargs=None, name=None: target(*args))
    posted: list[Callable[[], None]] = []
    mp.setattr(root, "post_to_main", posted.append, raising=False)

    def run_posted() -> None:
        while posted:
            posted.pop(0)()

    count = {"n": 5}
    mp.setattr(core_search, "reindex_all_history", lambda: count["n"])
    search = sd.SearchDialog(root)
    states["search_indexing"] = _texts(search)
    run_posted()
    states["search_indexed_5"] = _texts(search)
    count["n"] = 1
    search._reindex()
    run_posted()
    states["search_indexed_1"] = _texts(search)

    def broken_index() -> int:
        raise RuntimeError("«index broken»")

    mp.setattr(core_search, "reindex_all_history", broken_index)
    search._reindex()
    run_posted()
    states["search_index_failed"] = _texts(search)
    hits = [core_search.SearchHit(str(tmp_path / "«gone».json"), 0, "«hello»", 1.0, 3.0, 4.0),
            core_search.SearchHit(str(tmp_path / "«gone2».json"), 1, "«hello»", 0.5, 9.0, 10.0)]
    results = {"hits": hits}
    mp.setattr(core_search, "search", lambda _q, limit=100: results["hits"])
    search.query_var.set("«hello»")
    search._run_search()
    states["search_searching"] = _texts(search)
    run_posted()
    states["search_results_2"] = _texts(search)
    results["hits"] = hits[:1]
    search._run_search()
    run_posted()
    states["search_results_1"] = _texts(search)
    search.tree.focus("0")
    search._open_selected()
    states["search_missing"] = [row.replace(str(tmp_path), "<tmp>") for row in calls.take()]

    def broken_search(_q: str, limit: int = 100) -> list[Any]:
        raise RuntimeError("«bad query»")

    mp.setattr(core_search, "search", broken_search)
    search._run_search()
    run_posted()
    states["search_failed"] = _texts(search)
    search._on_close()

    # --- quick start
    done: list[Any] = []
    gpu_status = _cuda(usable=True, gpu_present=True, gpu_name="«RTX 9090»", memory_mb=8192)
    quick = qs.QuickStartDialog(root, {"download_folder": str(tmp_path)}, on_done=done.append,
                                probe=lambda: (gpu_status, 8), on_try_sample=lambda: None)
    quick._thread.join(5)
    states["quick_open"] = _texts(quick)
    quick._result = {"done": (gpu_status, 8, 4.0)}
    quick._poll()
    states["quick_hardware_known"] = _texts(quick)
    quick.language_var.set("Persian")
    quick._refresh_details()
    states["quick_persian"] = _texts(quick)
    quick._result = {"error": RuntimeError("«x»")}
    quick._poll()
    states["quick_check_failed"] = _texts(quick)
    quick._browse()
    quick.folder_var.set("")
    quick.finish()
    quick.folder_var.set("bad\x00name")
    quick.finish()
    states["quick_calls"] = calls.take()
    quick.skip()
    return states


@pytest.fixture
def tk_root() -> Iterator[Any]:
    tk = pytest.importorskip("tkinter")
    root = tk.Tk()
    root.withdraw()
    try:
        yield root
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


def _capture_requested() -> bool:
    return os.environ.get(CAPTURE_ENV) == "1" or CAPTURE_SENTINEL.exists()


def _fixture() -> dict[str, States]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# ----------------------------------------------------------------------------- English

def test_tk_english_texts_match_the_capture(tk_root: Any, monkeypatch: pytest.MonkeyPatch,
                                            tmp_path: Path, english: None) -> None:
    tk_part = tk_states(tk_root, monkeypatch, tmp_path)
    if _capture_requested():
        doc = {"pure": pure_states(tmp_path), "tk": tk_part}
        FIXTURE.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        pytest.skip(f"captured {FIXTURE.name}")
    assert tk_part == _fixture()["tk"]


def test_pure_english_texts_match_the_capture(tmp_path: Path, english: None) -> None:
    assert pure_states(tmp_path) == _fixture()["pure"]


# ----------------------------------------------------------------------------- pseudo-locale

def _language_names() -> set[str]:
    from app.domain.languages import SUBTITLE_LANGUAGES
    return {name for name, _codes in SUBTITLE_LANGUAGES}


def _unmarked(states: States) -> list[str]:
    """Texts with a letter outside a pseudo segment and outside a «data» value.

    Allowed: the language names of app.domain.languages (combobox values and the label the test
    selects; that module is not converted in this wave), and the kind prefixes this test adds.
    """
    names = _language_names()
    out: list[str] = []
    for key, rows in states.items():
        for text in rows:
            if text in names:
                continue
            parts = [_DATA.sub("", part) for part in text.split(" | ")]
            if parts and parts[0] in ("showerror", "showwarning", "showinfo", "askyesno",
                                      "askdirectory", "asksaveasfilename", "show_error",
                                      "notify info", "notify warning", "notify error"):
                parts = parts[1:]
            if not all(is_pseudo_marked(p) for p in parts):
                out.append(f"{key}: {text}")
    return out


def test_pure_pseudo_locale_marks_every_text(tmp_path: Path, pseudo: None) -> None:
    assert _unmarked(pure_states(tmp_path)) == []


def test_tk_pseudo_locale_marks_every_text(tk_root: Any, monkeypatch: pytest.MonkeyPatch,
                                           tmp_path: Path, pseudo: None) -> None:
    states = tk_states(tk_root, monkeypatch, tmp_path)
    assert _unmarked(states) == []
    # The capture reaches every state in the pseudo-locale too (no state lost on the way).
    assert set(states) == set(_fixture()["tk"])


def test_the_unmarked_check_catches_plain_english() -> None:
    """Negative control: an unconverted text is reported, a converted one is not."""
    assert _unmarked({"x": ["Close"]}) == ["x: Close"]
    assert _unmarked({"x": [i18n.pseudo_translate("Close")]}) == []
    assert _unmarked({"x": ["showerror | " + i18n.pseudo_translate("T") + " | Plain"]}) != []
    assert _unmarked({"x": [i18n.pseudo_translate("Saved {p}").replace("{p}", "«data»")]}) == []
    nested = i18n.pseudo_translate("Runs on {cpu}.").replace("{cpu}", i18n.pseudo_translate("the CPU"))
    assert _unmarked({"x": [nested]}) == []
    assert _unmarked({"x": ["Runs on " + i18n.pseudo_translate("the CPU")]}) != []


# ----------------------------------------------------------------------------- stored values

def test_quick_start_language_labels_map_to_the_same_codes_in_the_pseudo_locale() -> None:
    from app.dialogs import quick_start as qs

    i18n.set_language("en")
    english_options = qs.language_options()
    try:
        i18n.set_language(i18n.PSEUDO_LOCALE)
        pseudo_options = qs.language_options()
    finally:
        i18n.set_language("en")
    assert [code for _l, code in pseudo_options] == [code for _l, code in english_options]
    assert pseudo_options[0][1] == "" and is_pseudo_marked(pseudo_options[0][0])
    assert all(is_pseudo_marked(label) for label, _c in pseudo_options)  # names too
    assert english_options[0][0] == qs.AUTO_LANGUAGE_LABEL


def _quick_start_config(root: Any, mp: pytest.MonkeyPatch, folder: Path, language_label: str | None,
                        mode: str) -> dict[str, Any]:
    from core import hub
    from app.dialogs import quick_start as qs

    mp.setattr(hub, "default_hub_folder", lambda: str(folder / "hub"))
    done: list[Any] = []
    quick = qs.QuickStartDialog(root, {"download_folder": str(folder)}, on_done=done.append,
                                probe=lambda: (_cuda(), 4))
    if language_label is not None:
        values = list(quick.language_combo.tk.splitlist(quick.language_combo.cget("values")))
        from app.domain.languages import subtitle_language_label
        # The English name picks the entry: shown translated in the current language.
        quick.language_combo.current(values.index(subtitle_language_label(language_label)))
        quick.language_combo.event_generate("<<ComboboxSelected>>")
    else:
        quick.language_combo.current(0)  # the translated "several languages" label
    from tkinter import ttk

    def walk(w: Any) -> Iterator[Any]:
        for c in w.winfo_children():
            yield c
            yield from walk(c)

    radios = [w for w in walk(quick) if isinstance(w, ttk.Radiobutton)]
    radios[[m for m, _label in qs.MODES].index(mode)].invoke()  # as a click does
    quick.finish()
    assert len(done) == 1
    config: dict[str, Any] = {}
    qs.apply_choice(config, done[0])
    return config


@pytest.mark.parametrize("label, mode", [(None, "fast"), ("Persian", "best"), ("Japanese", "fast")])
def test_quick_start_saves_the_same_config_in_the_pseudo_locale(
        tk_root: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, label: str | None,
        mode: str) -> None:
    """The combobox shows translated labels; the saved language code and model stay the same."""
    i18n.set_language("en")
    english_config = _quick_start_config(tk_root, monkeypatch, tmp_path, label, mode)
    try:
        i18n.set_language(i18n.PSEUDO_LOCALE)
        pseudo_config = _quick_start_config(tk_root, monkeypatch, tmp_path, label, mode)
    finally:
        i18n.set_language("en")
    assert pseudo_config == english_config
    assert english_config["quick_start_done"] is True


def test_caption_choice_returns_stable_values_in_the_pseudo_locale(
        tk_root: Any, monkeypatch: pytest.MonkeyPatch, pseudo: None) -> None:
    from tkinter import ttk

    from app.dialogs import caption_choice as cc

    def press_first_button(window: Any) -> None:
        def walk(w: Any) -> Iterator[Any]:
            for c in w.winfo_children():
                yield c
                yield from walk(c)
        next(w for w in walk(window) if isinstance(w, ttk.Button)).invoke()

    states: States = {}
    _modal(tk_root, monkeypatch, states, "x", press_first_button)
    assert cc.ask_caption_choice(tk_root, kind="manual", language="«French»") == (
        cc.CHOICE_TRANSCRIBE, False)
