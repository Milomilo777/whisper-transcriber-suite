import pytest
import tkinter as tk
from tkinter import ttk
from app.widgets import smtv_tab

def test_mix():
    assert smtv_tab._mix((0, 0, 0), (255, 255, 255), 0.5) == "#808080"
    assert smtv_tab._mix((0, 0, 0), (255, 255, 255), 0.0) == "#000000"
    assert smtv_tab._mix((0, 0, 0), (255, 255, 255), 1.0) == "#ffffff"

def test_hero_curve_points():
    points = smtv_tab._hero_curve_points(attenuation=1.0, width=100.0, height_max=50.0, amplitude=1.0, phase=0.0)
    assert len(points) == 402 # 201 points * 2 (x, y)
    assert points[0] == 100.0 * (-2 + 2) / 4 # x0
    assert points[1] == pytest.approx(50.0, 0.1) # y0


@pytest.fixture(scope="module")
def root():
    pytest.importorskip("tkinter")
    import tkinter as tk
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("no Tk display available")
    r.withdraw()
    yield r
    try:
        r.destroy()
    except tk.TclError:
        pass

@pytest.fixture
def app_mock(root):
    import types
    posted = []
    app = types.SimpleNamespace(
        post_to_main=posted.append,
        logged=[],
        download_url_var=tk.StringVar(master=root),
        download_mode_var=tk.StringVar(master=root, value="Audio and video"),
        auto_transcribe_var=tk.BooleanVar(master=root, value=False),
        smtv_download_all_parts_var=tk.BooleanVar(master=root, value=True),
        update_download_mode=lambda: None,
        _save_auto_transcribe_pref=lambda: None,
        nb=types.SimpleNamespace(select=lambda tab: setattr(app, "selected", tab)),
        t3="download-tab",
        after=root.after,
        after_cancel=root.after_cancel
    )
    app.log = app.logged.append
    app.post_to_main = posted.append
    app.posted = posted
    return app

def test_destroy_cancels_timer_and_ignores_tclerror():
    import types
    import tkinter as tk
    
    app = types.SimpleNamespace(
        after_calls=[],
        after_cancels=[]
    )
    def fake_after_cancel(id):
        app.after_cancels.append(id)
        raise tk.TclError("fake error")
    app.after_cancel = fake_after_cancel
    
    state = smtv_tab._TabState(app)
    state._audio_after_id = "test_timer_123"
    
    state.destroy()
    
    assert "test_timer_123" in app.after_cancels
    assert state._audio_after_id is None

def test_destroy_does_not_call_cancel_if_no_timer():
    import types
    app = types.SimpleNamespace(
        after_calls=[],
        after_cancels=[]
    )
    def fake_after_cancel(id):
        app.after_cancels.append(id)
    app.after_cancel = fake_after_cancel
    
    state = smtv_tab._TabState(app)
    state._audio_after_id = None
    
    state.destroy()
    
    assert not app.after_cancels

def test_add_card_none_values(app_mock, root):
    state = smtv_tab._TabState(app_mock)
    state.inner = ttk.Frame(root)
    state._wrap = 600
    
    class MockItem:
        def __init__(self):
            self.title = None
            self.abstract = None
            self.program = None
            self.date = None
            self.duration = None
            self.views = None
            self.url = "http://test"
            self.thumbnail = None
            
    item = MockItem()
    
    try:
        state._add_card(item)
    except Exception as e:
        pytest.fail(f"_add_card crashed on None values: {e}")

