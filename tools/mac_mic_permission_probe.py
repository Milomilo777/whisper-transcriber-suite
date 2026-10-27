#!/usr/bin/env python3
"""Check the macOS microphone notice on a real Mac or in the macOS VM.

Run from a Terminal inside a desktop session, from the repo root::

    python tools/mac_mic_permission_probe.py [--open-settings]

Part 1 (automatic) prints what ``app.mac_permissions`` reads::

    INFO status: authorized|denied|restricted|not_determined|unknown
    PASS|FAIL <check>: <detail>

PASS needs a status other than ``unknown`` (``unknown`` means the ctypes query to AVFoundation
failed). ``--open-settings`` also opens Privacy & Security > Microphone; look at the screen.

Part 2 (by hand, in the built app; a VM without an audio device cannot prove step 4):

1. Reset the answer:  ``tccutil reset Microphone <bundle id>``  (the id is CFBundleIdentifier
   in the app's Info.plist) and delete ``mac_mic_notice_seen`` from the app's config.json.
2. Open the Live tab, press Start listening. Expect the short notice ("macOS will ask ...") with
   only a Close button, then, after Close, macOS's own question. Answer Don't Allow.
3. Press Start listening again. Expect the other notice ("macOS is not giving this app the
   microphone ...") with Open System Settings; the button must open the Microphone pane. Listening
   must not start. Turn the app on there, return, press Start: it listens.
4. With a real microphone, mute it at the system level and listen: after about 5 s expect the
   same blocked notice once (not again until the next Start).
5. On Windows and Linux none of these notices ever appears (the unit tests pin that).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import mac_permissions  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--open-settings", action="store_true")
    args = parser.parse_args()
    if sys.platform != "darwin":
        print("INFO this is not macOS; nothing to probe")
        return 2
    status = mac_permissions.microphone_status()
    print(f"INFO status: {status}")
    ok = status != mac_permissions.UNKNOWN
    print(f"{'PASS' if ok else 'FAIL'} status-read: AVFoundation answered {status}")
    reason = mac_permissions.notice_reason(status, seen=False)
    print(f"INFO notice for a first start: {reason}")
    if args.open_settings:
        opened = mac_permissions.open_microphone_settings()
        print(f"{'PASS' if opened else 'FAIL'} open-settings: open returned "
              f"{'0' if opened else 'an error'}; the Microphone pane should be showing")
        ok = ok and opened
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
