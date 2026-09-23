"""App.__init__ must create the post_to_main queue before building tabs.

Regression (found 2026-09-23 while adding the Supreme Master TV tab): tab
builders start background probes (the Transcribe tab's engine-status
check, the SMTV tab's first search) whose post_to_main could fire before
``_main_thread_calls`` existed -- an AttributeError in that thread and
the result silently lost (engine status never shown, a tab stuck on
"Loading..."). Checked statically: constructing the real App needs a
display, the whole config stack and a tray icon.
"""
from __future__ import annotations

import inspect

from app.app import App


def test_main_thread_queue_is_created_before_tabs_are_built():
    src = inspect.getsource(App.__init__)
    queue_at = src.find("self._main_thread_calls: Queue = Queue(")
    tabs_at = src.find("self._build_tabs()")
    assert queue_at != -1 and tabs_at != -1
    assert queue_at < tabs_at
