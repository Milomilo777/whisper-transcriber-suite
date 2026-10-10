"""The book showcases inside the Supreme Master TV tab (app/widgets/book_panel.py) -- no network."""
from __future__ import annotations

import io
import threading
import time
import types
from typing import Any

import pytest

from app.widgets import smtv_tab
from core import offline
from core.integrations import smtv_books
from core.integrations import smtv_browse as sb

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

CRISIS, LOVE = smtv_books.BOOKS


@pytest.fixture(scope="module")
def root():
    try:
        r = tk.Tk()
    except tk.TclError:  # pragma: no cover - headless CI
        pytest.skip("no Tk display available")
    r.withdraw()
    yield r
    try:
        r.destroy()
    except tk.TclError:
        pass


def _jpeg() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (120, 160), (30, 90, 200)).save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture
def built(root, monkeypatch, tmp_path):
    monkeypatch.setattr(sb, "search", lambda lang, q, t, c, page, **kw: sb.SearchPage(
        items=[], total=0, page=page))
    monkeypatch.setattr(smtv_books, "cache_dir", lambda: tmp_path)
    posted: list = []
    app = types.SimpleNamespace(post_to_main=posted.append, logged=[])
    app.log = app.logged.append
    app.download_url_var = tk.StringVar(master=root)
    app.download_mode_var = tk.StringVar(master=root, value="Audio and video")
    app.auto_transcribe_var = tk.BooleanVar(master=root, value=False)
    app.smtv_download_all_parts_var = tk.BooleanVar(master=root, value=True)
    app.update_download_mode = lambda: None
    app._save_auto_transcribe_pref = lambda: None
    app.nb = types.SimpleNamespace(select=lambda tab: None)
    app.t3 = "download-tab"
    frame = ttk.Frame(root)
    smtv_tab.build_smtv_tab(app, frame)
    frame.pack(fill="both", expand=True)
    root.deiconify()
    root.update()

    def pump(until=lambda: True, seconds: float = 3.0):
        deadline = time.time() + seconds
        while time.time() < deadline:
            while posted:
                posted.pop(0)()
            root.update()
            if until():
                return
            time.sleep(0.01)

    app.pump, app.posted = pump, posted
    pump(lambda: not app.smtv_state.loading)
    yield app
    frame.destroy()


@pytest.fixture
def opened(monkeypatch):
    urls: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url, *a, **k: urls.append(url) or True)
    return urls


def _texts(widget: Any) -> list[str]:
    out = []
    for child in widget.winfo_children():
        try:
            out.append(str(child.cget("text")))
        except tk.TclError:
            pass
        out.extend(_texts(child))
    return out


# --------------------------------------------------------------- entries

def test_books_row_has_two_separate_entries(built):
    st = built.smtv_state
    assert st.books_row.labels == [CRISIS.title, LOVE.title]
    assert not st.panel.winfo_ismapped()


def test_choosing_a_book_replaces_the_video_list_with_its_panel(built):
    st = built.smtv_state
    st.show_book(CRISIS.title)
    assert st.panel.winfo_manager() == "grid"
    assert st.body.winfo_manager() == ""
    assert st.panel.book is CRISIS
    texts = _texts(st.panel)
    assert CRISIS.title in texts and CRISIS.subtitle in texts
    assert any(CRISIS.author in t for t in texts)
    assert CRISIS.summary in texts
    assert st.books_row.selected == CRISIS.title
    assert st.explore is not None and st.explore.selected is None


def test_second_book_swaps_the_content(built):
    st = built.smtv_state
    st.show_book(CRISIS.title)
    st.show_book(LOVE.title)
    assert st.panel.book is LOVE
    texts = _texts(st.panel)
    assert LOVE.title in texts and CRISIS.title not in texts
    assert st.books_row.selected == LOVE.title


def test_back_button_returns_to_the_videos(built):
    st = built.smtv_state
    st.show_book(LOVE.title)
    st.panel.close_button.invoke()
    assert st.panel.winfo_manager() == ""
    assert st.body.winfo_manager() == "grid"
    assert st.books_row.selected is None
    assert st.explore is not None and st.explore.selected == st.program_var.get()


def test_a_search_or_program_shortcut_closes_the_panel(built):
    st = built.smtv_state
    st.show_book(CRISIS.title)
    st.show_program("Words of Wisdom")
    built.pump(lambda: not st.loading)
    assert st.panel.winfo_manager() == ""
    assert st.body.winfo_manager() == "grid"


def test_escape_closes_the_panel(built, root):
    st = built.smtv_state
    st.show_book(CRISIS.title)
    root.update()
    st.panel.link_buttons[0].focus_force()
    root.update()
    st.panel.link_buttons[0].event_generate("<Escape>")
    root.update()
    assert st.panel.winfo_manager() == ""


# ----------------------------------------------------------------- links

@pytest.mark.parametrize("book", smtv_books.BOOKS, ids=lambda b: b.key)
def test_every_button_opens_its_official_page(built, opened, book):
    st = built.smtv_state
    st.show_book(book.title)
    assert [b["text"] for b in st.panel.link_buttons] == [ln.label for ln in book.links]
    for button, link in zip(st.panel.link_buttons, book.links):
        button.invoke()
        assert opened[-1] == link.url
    assert opened == [ln.url for ln in book.links]


def test_link_buttons_are_keyboard_reachable(built):
    st = built.smtv_state
    st.show_book(CRISIS.title)
    for button in st.panel.link_buttons:
        assert str(button.cget("takefocus")) not in ("0",)
    assert str(st.panel.close_button.cget("takefocus")) not in ("0",)


# ---------------------------------------------------------------- covers

def test_offline_shows_the_placeholder_and_makes_no_request(built, monkeypatch):
    def boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("network primitive called while offline")

    monkeypatch.setattr(smtv_books.urllib.request, "urlopen", boom)
    offline.set_offline(True)
    st = built.smtv_state
    st.show_book(CRISIS.title)
    built.pump(lambda: st.panel.cover_state != "loading")
    assert st.panel.cover_state == "placeholder"
    assert st.panel.note_var.get() == "Cover not available while Work offline is on."


def test_cover_downloads_on_a_worker_thread_and_shows_on_the_main_thread(built, monkeypatch):
    main = threading.get_ident()
    seen: list[int] = []

    def fake_fetch(book, **_k):
        seen.append(threading.get_ident())
        time.sleep(0.05)
        return _jpeg()

    monkeypatch.setattr(smtv_books, "fetch_cover", fake_fetch)
    st = built.smtv_state
    st.show_book(LOVE.title)
    assert st.panel.cover_state == "loading"   # the worker has not touched Tk yet
    built.pump(lambda: st.panel.cover_state == "cover")
    assert st.panel.cover_state == "cover"
    assert seen and seen[0] != main
    assert st.panel.note_var.get() == ""


def test_cover_is_fetched_once_per_book(built, monkeypatch):
    calls: list[str] = []

    def fake_fetch(book, **_k):
        calls.append(book.key)
        return _jpeg()

    monkeypatch.setattr(smtv_books, "fetch_cover", fake_fetch)
    st = built.smtv_state
    st.show_book(LOVE.title)
    built.pump(lambda: st.panel.cover_state == "cover")
    st.show_book(CRISIS.title)
    built.pump(lambda: st.panel.cover_state == "cover" and len(calls) == 2)
    st.show_book(LOVE.title)
    built.pump()
    assert st.panel.cover_state == "cover"
    assert calls == [LOVE.key, CRISIS.key]


def test_a_late_cover_for_another_book_is_ignored(built, monkeypatch):
    release = threading.Event()

    def slow_fetch(book, **_k):
        if book is CRISIS:
            release.wait(3)
        return _jpeg()

    monkeypatch.setattr(smtv_books, "fetch_cover", slow_fetch)
    st = built.smtv_state
    st.show_book(CRISIS.title)      # its cover is slow
    st.show_book(LOVE.title)
    built.pump(lambda: st.panel.cover_state == "cover")
    release.set()
    built.pump(lambda: False, seconds=0.4)   # the slow one lands late
    assert st.panel.book is LOVE and st.panel.cover_state == "cover"


def test_a_bad_image_falls_back_to_the_placeholder(built, monkeypatch):
    monkeypatch.setattr(smtv_books, "fetch_cover", lambda book, **_k: b"not an image")
    st = built.smtv_state
    st.show_book(LOVE.title)
    built.pump(lambda: st.panel.cover_state != "loading")
    assert st.panel.cover_state == "placeholder"


# --------------------------------------------------------------- scrolling

def test_a_short_window_scrolls_the_panel_a_tall_one_does_not(built, root):
    st = built.smtv_state
    try:
        root.geometry("1000x900")
        st.show_book(CRISIS.title)
        built.pump(lambda: False, seconds=0.3)
        assert st.panel._vsb.winfo_manager() == ""
        root.geometry("1000x520")
        built.pump(lambda: False, seconds=0.3)
        assert st.panel._vsb.winfo_manager() == "grid"
        root.geometry("1000x900")
        built.pump(lambda: False, seconds=0.3)
        assert st.panel._vsb.winfo_manager() == ""
    finally:
        root.geometry("")


# ----------------------------------------------------------- picture helpers

def test_trim_margin_removes_the_white_border_and_keeps_content():
    from PIL import Image

    from app.widgets import book_panel

    img = Image.new("RGB", (100, 100), (255, 255, 255))
    img.paste(Image.new("RGB", (20, 40), (10, 20, 30)), (30, 20))
    out = book_panel._trim_margin(img, keep=2)
    assert out.size == (24, 44)
    blank = Image.new("RGB", (50, 50), (255, 255, 255))
    assert book_panel._trim_margin(blank, keep=2) is blank


def test_fit_on_mat_has_the_mat_size_and_never_blows_a_small_picture_up():
    from PIL import Image

    from app.widgets import book_panel

    tiny = Image.new("RGB", (20, 20), (200, 0, 0))
    mat = book_panel._fit_on_mat(tiny, 250, 310, 16)
    assert mat.size == (250, 310) and mat.mode == "RGBA"
    assert mat.getpixel((0, 0))[3] == 0                 # rounded corner is transparent
    xs = [x for x in range(250) if mat.getpixel((x, 155))[:3] == (200, 0, 0)]
    assert 0 < len(xs) <= 20 * book_panel._MAX_UPSCALE + 2
    tall = Image.new("RGB", (100, 2000), (0, 0, 200))
    assert book_panel._fit_on_mat(tall, 250, 310, 16).size == (250, 310)


def test_a_theme_change_recolours_the_cover_surround(built, root):
    st = built.smtv_state
    st.show_book(CRISIS.title)
    style = ttk.Style(root)
    old = style.lookup("TFrame", "background")
    try:
        style.configure("TFrame", background="#123456")
        st.panel.event_generate("<<ThemeChanged>>")
        built.pump(lambda: False, seconds=0.2)
        assert st.panel._cover.cget("background") == "#123456"
        assert st.panel._canvas.cget("background") == "#123456"
    finally:
        style.configure("TFrame", background=old)
