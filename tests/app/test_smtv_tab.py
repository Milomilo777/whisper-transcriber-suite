"""The Supreme Master TV tab (app/widgets/smtv_tab.py) -- no network."""
from __future__ import annotations

import types

import pytest

from app.widgets import smtv_tab
from core.integrations import smtv_browse as sb

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402


@pytest.fixture(scope="module")
def root():
    try:
        r = tk.Tk()
    except tk.TclError:  # pragma: no cover — headless CI
        pytest.skip("no Tk display available")
    r.withdraw()
    yield r
    try:
        r.destroy()
    except tk.TclError:
        pass


def _item(n: int) -> sb.VideoItem:
    return sb.VideoItem(url=f"https://suprememastertv.com/en1/v/{n:09d}.html",
                        title=f"Video {n}", program="Heartline", date="2026-09-23",
                        duration="3:14", views=1234, abstract="word " * 80)


@pytest.fixture
def built(root, monkeypatch):
    calls: list[tuple] = []

    def fake_search(lang, query, type_, cat, page, **kw):
        calls.append((lang, query, type_, cat, page))
        return sb.SearchPage(items=[_item(page * 100 + i) for i in range(2)],
                             total=45, page=page)

    monkeypatch.setattr(sb, "search", fake_search)
    posted: list = []
    app = types.SimpleNamespace(post_to_main=posted.append, logged=[])
    app.log = app.logged.append
    app.download_url_var = tk.StringVar(master=root)
    app.download_mode_var = tk.StringVar(master=root, value="Audio and video")
    app.auto_transcribe_var = tk.BooleanVar(master=root, value=False)
    app.smtv_download_all_parts_var = tk.BooleanVar(master=root, value=True)
    app.update_download_mode = lambda: None
    app._save_auto_transcribe_pref = lambda: None
    app.nb = types.SimpleNamespace(select=lambda tab: setattr(app, "selected", tab))
    app.t3 = "download-tab"
    frame = ttk.Frame(root)
    smtv_tab.build_smtv_tab(app, frame)
    assert calls == []  # nothing fetched until the tab is shown
    frame.pack(fill="both", expand=True)
    root.deiconify()
    root.update()

    def pump():
        import time
        deadline = time.time() + 3
        while time.time() < deadline:
            while posted:
                posted.pop(0)()
            root.update()
            if not app.smtv_state.loading:
                return
            time.sleep(0.01)

    app.pump, app.calls = pump, calls
    yield app
    frame.destroy()


def test_loads_first_page_and_pages_on(built):
    built.pump()
    st = built.smtv_state
    assert built.calls[0] == ("en", "", "all", "", 1)
    assert len(st._cards) == 2 and st.has_more
    assert "of 45" in st.status_var.get()
    st.load_more()
    built.pump()
    assert built.calls[-1][-1] == 2 and len(st._cards) == 4


def test_program_shortcut_and_language_drive_the_query(built):
    built.pump()
    st = built.smtv_state
    st.lang_var.set("Persian")
    st.show_program("Words of Wisdom")
    built.pump()
    assert built.calls[-1] == ("fa", "", "WOW", "", 1)
    assert st._rtl is True
    assert len(st._cards) == 2  # old results replaced, not appended


def test_new_search_is_not_blocked_by_one_in_flight(built):
    st = built.smtv_state
    st.loading = True          # first page still on its way
    st.lang_var.set("German")
    st.new_search()
    built.pump()
    assert built.calls[-1][0] == "de"


def test_download_and_transcribe_prefill_the_download_tab(built, root):
    built.after = root.after
    built.pump()
    st = built.smtv_state
    st.send_to_download("https://suprememastertv.com/en1/v/1.html", transcribe=False)
    assert built.download_url_var.get().endswith("/v/1.html")
    assert built.selected == "download-tab"
    assert built.download_mode_var.get() == "Audio and video"
    assert built.auto_transcribe_var.get() is False
    assert built.smtv_download_all_parts_var.get() is False  # just this video

    url = "https://suprememastertv.com/en1/v/2.html"
    st.send_to_download(url, transcribe=True)
    assert built.auto_transcribe_var.get() is True
    assert built.download_mode_var.get() == "Audio and video"  # not yet known
    # Lookup finished: a video-only clip keeps the video mode...
    built._smtv_episode = types.SimpleNamespace(page_url=url)
    built.audio_format_map = {}
    st._prefer_audio_when_available(url, tries=0)
    assert built.download_mode_var.get() == "Audio and video"
    # ...an episode with an mp3 switches to the smaller audio download.
    built.audio_format_map = {"mp3": "x"}
    st._prefer_audio_when_available(url, tries=0)
    assert built.download_mode_var.get() == "Audio"


def test_helpers():
    assert smtv_tab.format_views(None) == ""
    assert smtv_tab.format_views(999) == "999 views"
    assert smtv_tab.format_views(6362) == "6.4K views"
    assert smtv_tab.format_views(52000) == "52K views"
    assert smtv_tab.format_views(1_400_000) == "1.4M views"
    assert smtv_tab.shorten("a b", 10) == "a b"
    assert smtv_tab.shorten("word " * 100, 20).endswith("…")
    assert "·" not in smtv_tab.detail_line(sb.VideoItem(url="u", title="t"))
