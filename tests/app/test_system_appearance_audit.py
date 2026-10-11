from unittest.mock import MagicMock
from app.theme import system_appearance

def test_resolve_theme(monkeypatch):
    """Characterization test for `resolve_theme`."""
    class FakeBackend:
        def __init__(self, answer):
            self.answer = answer
        def is_dark(self):
            return self.answer

    assert system_appearance.resolve_theme("light", FakeBackend(True)) == "light"
    assert system_appearance.resolve_theme("dark", FakeBackend(False)) == "dark"
    assert system_appearance.resolve_theme("system", FakeBackend(True)) == "dark"
    assert system_appearance.resolve_theme("system", FakeBackend(False)) == "light"
    assert system_appearance.resolve_theme("system", FakeBackend(None)) == system_appearance.UNKNOWN_FALLBACK
    assert system_appearance.resolve_theme("unknown", FakeBackend(True)) == "dark"

    class FailingBackend:
        def is_dark(self):
            raise Exception("broken")
    
    assert system_appearance.resolve_theme("system", FailingBackend()) == system_appearance.UNKNOWN_FALLBACK

def test_get_backend():
    """Characterization test for `get_backend`."""
    assert isinstance(system_appearance.get_backend("win32"), system_appearance.WindowsBackend)
    assert isinstance(system_appearance.get_backend("darwin"), system_appearance.MacBackend)
    assert isinstance(system_appearance.get_backend("linux"), system_appearance.DarkdetectBackend)

def test_system_theme_watcher():
    """Characterization test for `SystemThemeWatcher`."""
    mock_root = MagicMock()
    mock_callback = MagicMock()
    mock_backend = MagicMock()
    mock_backend.live = True
    
    mock_cancel = MagicMock()
    mock_backend.subscribe.return_value = mock_cancel
    
    watcher = system_appearance.SystemThemeWatcher(mock_root, mock_callback, mock_backend)
    assert not watcher.running
    
    watcher.start()
    assert watcher.running
    mock_backend.subscribe.assert_called_once_with(mock_callback, mock_root)
    
    watcher.start() # Second call should do nothing
    assert mock_backend.subscribe.call_count == 1
    
    watcher.stop()
    assert not watcher.running
    mock_cancel.assert_called_once()
    
    watcher.stop() # Second call should do nothing
    assert mock_cancel.call_count == 1

def test_darkdetect_backend(monkeypatch):
    """Characterization test for `DarkdetectBackend`."""
    backend = system_appearance.DarkdetectBackend()
    
    # Missing package
    import sys
    monkeypatch.setitem(sys.modules, 'darkdetect', None)
    assert backend.is_dark() is None
    
    # Installed, returns Dark
    class FakeDarkdetect:
        @staticmethod
        def theme():
            return "Dark"
    monkeypatch.setitem(sys.modules, 'darkdetect', FakeDarkdetect)
    assert backend.is_dark() is True
    
    # Installed, returns Light
    class FakeDarkdetectLight:
        @staticmethod
        def theme():
            return "Light"
    monkeypatch.setitem(sys.modules, 'darkdetect', FakeDarkdetectLight)
    assert backend.is_dark() is False
    
    # Installed, returns None
    class FakeDarkdetectNone:
        @staticmethod
        def theme():
            return None
    monkeypatch.setitem(sys.modules, 'darkdetect', FakeDarkdetectNone)
    assert backend.is_dark() is False
    
    assert backend.subscribe(lambda: None, MagicMock()) is system_appearance._no_op

