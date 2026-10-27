"""The window icon: .ico through ``wm iconbitmap`` on Windows only, a PNG elsewhere (X11 rejects the .ico)."""
from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from app import app as app_module


class _Fake:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def iconbitmap(self, **kw: Any) -> None:
        self.calls.append(("iconbitmap", kw))

    def iconphoto(self, default: bool, image: Any) -> None:
        self.calls.append(("iconphoto", image))


def _run(monkeypatch: pytest.MonkeyPatch, platform: str) -> _Fake:
    fake = _Fake()
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(app_module.tk, "PhotoImage", lambda file: types.SimpleNamespace(file=file))
    app_module.App._install_icon(fake)  # type: ignore[arg-type]
    return fake


def test_linux_uses_the_png_not_the_ico(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _run(monkeypatch, "linux")
    assert [c[0] for c in fake.calls] == ["iconphoto"]
    assert fake.calls[0][1].file.endswith("whisper.png")


def test_windows_keeps_the_ico(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _run(monkeypatch, "win32")
    assert [c[0] for c in fake.calls] == ["iconbitmap"]
    assert fake.calls[0][1]["default"].endswith("whisper.ico")


def test_macos_sets_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _run(monkeypatch, "darwin").calls == []
