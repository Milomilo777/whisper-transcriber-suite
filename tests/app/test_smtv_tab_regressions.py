import pytest
import types
from app.widgets import smtv_tab
from core.integrations import smtv_browse as sb

tk = pytest.importorskip("tkinter")
from tkinter import ttk

@pytest.fixture(scope="module")
def root():
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

    def pump():
        import time
        deadline = time.time() + 3
        while time.time() < deadline:
            while posted:
                posted.pop(0)()
            root.update()
            if not getattr(app, "smtv_state", types.SimpleNamespace(loading=False)).loading:
                return
            time.sleep(0.01)
    app.pump = pump
    app.root = root
    return app

def test_smtv_search_thread_crash_is_logged(app_mock, monkeypatch, caplog):
    def fake_search(*args, **kwargs):
        raise ValueError("simulated crash inside work")

    monkeypatch.setattr(sb, "search", fake_search)

    frame = ttk.Frame(app_mock.root)
    smtv_tab.build_smtv_tab(app_mock, frame)
    app_mock.smtv_state.new_search()

    import time
    time.sleep(0.1) # let the thread crash
    app_mock.pump()

    assert "simulated crash inside work" in caplog.text

def test_smtv_tab_destroy_shuts_down_thread_pool(app_mock):
    frame = ttk.Frame(app_mock.root)
    smtv_tab.build_smtv_tab(app_mock, frame)
    state = app_mock.smtv_state

    # Assert pool is running and doesn't shutdown automatically
    assert not state._pool._shutdown

    # Destroying state should shutdown pool
    assert hasattr(state, "destroy")
    state.destroy()
    assert state._pool._shutdown

def test_prefer_audio_when_available_cancels_previous_after(app_mock):
    frame = ttk.Frame(app_mock.root)
    smtv_tab.build_smtv_tab(app_mock, frame)
    state = app_mock.smtv_state

    app_mock.download_url_var.set("http://test.com")

    # First call
    state._prefer_audio_when_available("http://test.com", tries=1)
    assert getattr(state, "_audio_after_id", None) is not None
    first_id = state._audio_after_id

    # Second call should cancel the first
    state._prefer_audio_when_available("http://test.com", tries=1)
    assert getattr(state, "_audio_after_id", None) is not None
    assert state._audio_after_id != first_id
