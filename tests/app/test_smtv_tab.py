"""The Supreme Master TV tab (app/widgets/smtv_tab.py) -- no network."""
from __future__ import annotations

import types

import pytest

from app.theme import tokens
from app.widgets import chip_cloud, smtv_tab
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

def _all_widgets(w):
    yield w
    for c in w.winfo_children():
        yield from _all_widgets(c)


def test_explore_chips_list_every_program_and_drive_the_query(built):
    built.pump()
    explore = built.smtv_state.explore
    programs = {label for label, _t, _c in sb.PROGRAMS}
    assert explore.labels == list(smtv_tab._SHORTCUTS)
    assert set(smtv_tab._SHORTCUTS) <= programs  # every chip has a type/category
    explore.activate(1)
    built.pump()
    label = smtv_tab._SHORTCUTS[1]
    t, c = next((t, c) for lb, t, c in sb.PROGRAMS if lb == label)
    assert built.calls[-1][2:4] == (t, c)
    built.smtv_state.program_var.set(smtv_tab._SHORTCUTS[0])
    assert explore.selected == smtv_tab._SHORTCUTS[0]  # the dropdown and the chips agree


def test_cards_and_hero_offer_no_transcribe_or_live_buttons(built):
    built.pump()
    texts = [w.cget('text') for w in _all_widgets(built.smtv_state.canvas.winfo_toplevel())
             if isinstance(w, ttk.Button)]
    assert not any('Transcribe' in t for t in texts)
    pills = built.smtv_state.hero_pills.labels  # the banner buttons are pills on the hero canvas
    assert not any(t.strip().endswith(('Watch live', 'TV schedule', 'Website')) for t in texts + pills)
    assert pills[0] == 'About the channel'  # first, and looking like the others
    assert pills[1:] == list(smtv_tab._HERO_PROGRAMS)
    for label in smtv_tab._HERO_PROGRAMS:  # banner shortcuts, all real programs
        assert label in {lb for lb, _t, _c in sb.PROGRAMS}
    assert not set(smtv_tab._HERO_PROGRAMS) & set(smtv_tab._SHORTCUTS)
    assert not any(t in texts for t in pills)  # no leftover square ttk buttons in the banner


def _hero_items(hero, kind):
    return [i for i in hero.find_all() if hero.type(i) == kind]


def test_banner_buttons_are_pills_that_look_the_same(built, root):
    built.pump()
    st = built.smtv_state
    hero, pills = st.hero_pills.hero, st.hero_pills
    root.update()
    assert len(pills.boxes) == len(pills.labels) == 1 + len(smtv_tab._HERO_PROGRAMS)
    assert len({round(h) for _x, _y, _w, h in pills.boxes}) == 1  # one height for all
    names = {str(img): key for key, img in pills._images.items()}
    keys = [names[hero.itemcget(i, "image")] for i in _hero_items(hero, "image")
            if "pills" in hero.gettags(i)]
    assert len(keys) == len(pills.labels)
    assert len({k[2:] for k in keys}) == 1  # same fill, border and width for every pill
    assert all(k[1] == keys[0][1] for k in keys)  # and the same height: no special first button
    assert not [w for w in _all_widgets(hero) if isinstance(w, ttk.Button)]  # drawn, not widgets


def test_banner_has_a_featured_programs_eyebrow_above_the_pills(built, root):
    built.pump()
    pills = built.smtv_state.hero_pills
    hero = pills.hero
    eyebrow = [i for i in _hero_items(hero, "text")
               if hero.itemcget(i, "text") == "FEATURED PROGRAMS"]
    assert len(eyebrow) == 1
    assert hero.itemcget(eyebrow[0], "fill") == tokens.HERO_ACCENT
    assert hero.bbox(eyebrow[0])[3] <= pills.boxes[0][1]  # sits above the first pill


def test_banner_pills_work_from_the_keyboard_and_the_mouse(built, root, monkeypatch):
    built.pump()
    st = built.smtv_state
    pills, hero = st.hero_pills, st.hero_pills.hero
    opened: list[str] = []
    monkeypatch.setattr(smtv_tab.webbrowser, "open", opened.append)
    assert str(hero.cget("takefocus")) == "1"  # reachable with Tab

    def press(key):
        # Other windows can take the focus from a test run on a busy desktop: take it back first.
        hero.focus_force()
        hero.event_generate("<FocusIn>")
        hero.event_generate(key)
        root.update()

    press("<Return>")  # focus starts on "About the channel"
    assert pills.has_focus
    rings = len(_hero_items(hero, "image"))
    assert opened and opened[0].endswith("about-us/")
    press("<Right>")
    press("<space>")
    built.pump()
    assert st.program_var.get() == smtv_tab._HERO_PROGRAMS[0] and pills.focus_index == 1
    assert built.calls[-1][2:4] != ("all", "")  # same search as the chip would run
    # A mouse click on the last pill runs the same action.
    x, y, w, h = pills.boxes[-1]
    hero.event_generate("<Button-1>", x=int(x + w / 2), y=int(y + h / 2))
    root.update()
    built.pump()
    assert st.program_var.get() == smtv_tab._HERO_PROGRAMS[-1]
    # The focus ring is one extra image, gone when the focus leaves.
    hero.event_generate("<FocusIn>")
    assert len(_hero_items(hero, "image")) == rings
    hero.event_generate("<FocusOut>")
    root.update()
    assert not pills.has_focus and len(_hero_items(hero, "image")) == rings - 1


def test_hovered_banner_pill_gets_the_gold_border(built, root):
    built.pump()
    pills = built.smtv_state.hero_pills
    x, y, w, h = pills.boxes[2]
    pills.hero.event_generate("<Motion>", x=int(x + w / 2), y=int(y + h / 2))
    root.update()
    assert pills.hover == 2
    names = {str(img): key for key, img in pills._images.items()}
    borders = {names[pills.hero.itemcget(i, "image")][3] for i in _hero_items(pills.hero, "image")}
    assert tokens.HERO_PILLS["hover_border"] in borders
    pills.hero.event_generate("<Leave>")
    root.update()
    assert pills.hover is None


def _blend(rgba, bg):
    a = rgba[3] / 255
    return tuple(rgba[i] * a + bg[i] * (1 - a) for i in range(3))


def _lum(rgb):
    lin = [c / 255 / 12.92 if c / 255 <= 0.03928 else ((c / 255 + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _ratio(a, b):
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _banner_colours():
    lo, hi = smtv_tab._HERO_LEFT, smtv_tab._HERO_RIGHT
    return [tuple(lo[i] + (hi[i] - lo[i]) * t / 10 for i in range(3)) for t in range(11)]


def test_banner_pill_text_stays_readable_over_the_whole_gradient():
    pal = tokens.HERO_PILLS
    scrim = (pal["scrim"], pal["scrim_alpha"])
    white = chip_cloud.hex_rgb(pal["text"])
    for alpha in (pal["rest_alpha"], pal["hover_alpha"]):
        fill = chip_cloud.flatten([scrim, (pal["fill"], alpha)])
        for bg in _banner_colours():
            assert _ratio(white, _blend(fill, bg)) >= 4.5, (alpha, bg)
    # Negative control: without the scrim a hovered pill fails AA where the banner is teal.
    bare = chip_cloud.flatten([(pal["fill"], pal["hover_alpha"])])
    assert _ratio(white, _blend(bare, smtv_tab._HERO_RIGHT)) < 4.5
    # The gold eyebrow, hover border and focus ring on the plain banner.
    gold = chip_cloud.hex_rgb(tokens.HERO_ACCENT)
    assert pal["hover_border"] == pal["ring"] == tokens.HERO_ACCENT
    for bg in _banner_colours():
        assert _ratio(gold, bg) >= 4.5


def test_sections_have_a_heading_on_their_own_line_and_the_chips_align_with_it(built, root):
    built.pump()
    st = built.smtv_state
    root.update()
    labels = {w.cget("text") for w in _all_widgets(st.canvas.winfo_toplevel())
              if isinstance(w, ttk.Label)}
    assert "Browse programs" in labels and "Books" in labels
    assert "Explore" not in labels  # the inline label is gone
    assert any(t.strip(" ·") == str(len(smtv_tab._SHORTCUTS)) for t in labels)  # muted count
    for heading, cloud in ((st.explore_heading, st.explore), (st.books_heading, st.books_row)):
        assert int(heading.grid_info()["row"]) < int(cloud.grid_info()["row"])  # above, not beside
        assert int(cloud.grid_info()["column"]) == int(heading.grid_info()["column"]) == 0
        title = heading.winfo_children()[0]
        assert abs(title.winfo_rootx() - (cloud.winfo_rootx() + chip_cloud.MARGIN)) <= 1
    divider = [w for w in st.explore.master.winfo_children() if isinstance(w, ttk.Separator)]
    assert len(divider) == 1 and int(divider[0].grid_info()["row"]) > int(
        st.books_row.grid_info()["row"])  # a divider closes the chip rows
