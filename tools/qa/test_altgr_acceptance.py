"""Finite native AltGr acceptance; no layout install or clipboard access."""
from pathlib import Path
import ast
import ctypes
import json
import os
import sys
import time
import tkinter as tk

import psutil
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from altgr_guards import GuardError, guarded_chord, is_altgr_text, ownership_allowed, select_loaded_layout, temporary_layout
from receipt_io import write_json_checkpoint


def test_finite_native_altgr_acceptance(record_property):
    packet = Path(__file__).parent
    source = packet.parent
    plan = json.loads((packet / "plan.json").read_text())
    # Write directly inside the always-uploaded runner-temp directory so a
    # step timeout cannot leave the only receipt outside the artifact paths.
    output = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True) / "wts-altgr" / "raw.json"
    assert output.parent.is_dir()
    process = psutil.Process()
    identity = (process.pid, process.create_time())
    data = {"head": plan["head"], "pid": identity[0], "created": identity[1], "status": "STARTED", "injected_events": 0, "observations": []}

    def save():
        write_json_checkpoint(output, data)

    save()
    root = None
    try:
        assert sys.platform == "win32"
        root = tk.Tk()
        root.title("Owned P17B AltGr acceptance")
        root.geometry("500x240+140+140")
        data["tk_version"] = str(root.tk.call("info", "patchlevel"))
        assert root.tk.call("tk", "windowingsystem") == "win32"
        callback_errors = []
        root.report_callback_exception = lambda *args: callback_errors.append(repr(args))

        def pump(seconds=0.15):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                root.update()
                time.sleep(0.01)
            assert not callback_errors, callback_errors

        user = ctypes.windll.user32
        kernel = ctypes.windll.kernel32
        kernel.GetCurrentThreadId.restype = ctypes.c_ulong
        thread = int(kernel.GetCurrentThreadId())
        user.GetKeyboardLayout.restype = ctypes.c_void_p
        user.GetKeyboardLayoutList.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
        user.GetKeyboardLayoutList.restype = ctypes.c_int
        user.MapVirtualKeyExW.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p]
        user.ToUnicodeEx.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_wchar_p, ctypes.c_int, ctypes.c_uint, ctypes.c_void_p]
        user.ToUnicodeEx.restype = ctypes.c_int
        user.ActivateKeyboardLayout.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        user.ActivateKeyboardLayout.restype = ctypes.c_void_p
        user.GetForegroundWindow.restype = ctypes.c_void_p
        user.GetFocus.restype = ctypes.c_void_p
        user.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        user.GetAncestor.restype = ctypes.c_void_p
        user.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        user.GetAsyncKeyState.argtypes = [ctypes.c_int]
        user.GetAsyncKeyState.restype = ctypes.c_short

        class Layout:
            def current(self):
                return int(user.GetKeyboardLayout(0) or 0)

            def loaded(self):
                count = int(user.GetKeyboardLayoutList(0, None))
                if not 0 <= count <= 32:
                    raise GuardError("Loaded layout count outside finite bound")
                items = (ctypes.c_void_p * count)()
                received = int(user.GetKeyboardLayoutList(count, items))
                if not 0 <= received <= count:
                    raise GuardError("Layout enumeration changed")
                return [int(items[i] or 0) for i in range(received)]

            def owns_thread(self):
                return int(kernel.GetCurrentThreadId()) == thread

            def activate(self, hkl, flags):
                assert flags == 0 and self.owns_thread()
                return int(user.ActivateKeyboardLayout(hkl, flags) or 0)

            def translate(self, hkl, vk, alt):
                assert sys.getwindowsversion().build >= 14393
                state = (ctypes.c_ubyte * 256)()
                state[vk] = 0x80
                if alt:
                    for key in (0x11, 0xA2, 0x12, 0xA5):
                        state[key] = 0x80
                buffer = ctypes.create_unicode_buffer(16)
                count = int(user.ToUnicodeEx(vk, user.MapVirtualKeyExW(vk, 0, hkl), state, buffer, 16, 4, hkl))
                assert count <= 16
                return buffer[:count] if count > 0 else ""

        layout = Layout()
        selection = select_loaded_layout(layout)
        data["layout_selection"] = selection
        save()
        record_property("loaded_layout_evidence", json.dumps(selection))
        if selection["selected"] is None:
            data.update(status="BLOCKED-ENV", reason="No already-loaded layout produces a distinct printable AltGr character on the app shortcut keys A/C/X/V", plain_entry_baseline="NOT_RUN", app_hook="NOT_RUN")
            save()
            pytest.skip("BLOCKED-ENV: no eligible already-loaded AltGr layout; zero input sent")

        class Keyboard(ctypes.Structure):
            _fields_ = [("vk", ctypes.c_ushort), ("scan", ctypes.c_ushort), ("flags", ctypes.c_ulong), ("time", ctypes.c_ulong), ("extra", ctypes.c_size_t)]

        class Mouse(ctypes.Structure):
            _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("data", ctypes.c_ulong), ("flags", ctypes.c_ulong), ("time", ctypes.c_ulong), ("extra", ctypes.c_size_t)]

        class Payload(ctypes.Union):
            _fields_ = [("ki", Keyboard), ("mi", Mouse)]

        class Input(ctypes.Structure):
            _fields_ = [("type", ctypes.c_ulong), ("payload", Payload)]

        user.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(Input), ctypes.c_int]
        user.SendInput.restype = ctypes.c_uint
        entry = tk.Entry(root)
        entry.pack(padx=20, pady=30)
        root.deiconify()
        root.lift()
        entry.focus_force()
        pump()
        events = []
        entry.bind("<KeyPress>", lambda event: events.append({"state": event.state, "keysym": event.keysym, "keycode": event.keycode, "char": event.char}), add="+")
        virtual_actions = []
        real_generate = entry.event_generate

        def block_native_clipboard(event, action):
            virtual_actions.append("native:" + action)
            return "break"

        clipboard_guard_tag = "P17BClipboardGuard" + str(identity[0])
        entry.bindtags((clipboard_guard_tag, *entry.bindtags()))
        for action in ("<<Copy>>", "<<Cut>>", "<<Paste>>"):
            root.bind_class(clipboard_guard_tag, action, lambda event, action=action: block_native_clipboard(event, action), add="+")

        def intercept_virtual(sequence, **kwargs):
            if sequence in ("<<Copy>>", "<<Cut>>", "<<Paste>>"):
                virtual_actions.append(sequence)
                return None
            return real_generate(sequence, **kwargs)

        # Observe the real hook's decision without overwriting owner clipboard data.
        entry.event_generate = intercept_virtual
        baselines = {}
        handler_results = []
        with temporary_layout(layout, selection["selected"]) as state:
            data["thread_layout_state"] = state
            for phase in ("plain_entry_baseline", "actual_app_hook"):
                if phase == "actual_app_hook":
                    tree = ast.parse((source / "app/app.py").read_text(encoding="utf-8"))
                    app = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "App")
                    names = {"_clipboard_action", "_install_clipboard_keys"}
                    methods = [n for n in app.body if isinstance(n, ast.FunctionDef) and n.name in names]
                    values = [n for n in app.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_CLIPBOARD_VK" for t in n.targets)]
                    assert len(methods) == 2 and len(values) == 1
                    namespace = {"tk": tk, "sys": sys}
                    node = ast.ClassDef(name="App", bases=[], keywords=[], body=values + methods, decorator_list=[])
                    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(source / "app/app.py"), "exec"), namespace)
                    instance = namespace["App"]()

                    def bind_all(sequence, handler, add=None):
                        def wrapped(event):
                            result = handler(event)
                            handler_results.append(result)
                            return result
                        root.bind_all(sequence, wrapped, add=add)

                    instance.bind_all = bind_all
                    instance._install_clipboard_keys()
                for vk in selection["eligible_keys"]:
                    entry.delete(0, "end")
                    entry.focus_force()
                    pump()
                    events.clear()
                    virtual_actions.clear()
                    handler_results.clear()
                    proofs = []

                    class Native:
                        def owns(self):
                            current = psutil.Process()
                            if (current.pid, current.create_time()) != identity:
                                return False
                            foreground = user.GetForegroundWindow()
                            pid = ctypes.c_ulong()
                            user.GetWindowThreadProcessId(foreground, ctypes.byref(pid))
                            focus = user.GetFocus()
                            focus_pid = ctypes.c_ulong()
                            if focus:
                                user.GetWindowThreadProcessId(focus, ctypes.byref(focus_pid))
                            proof = {"foreground_hwnd": foreground, "expected_top_hwnd": user.GetAncestor(entry.winfo_id(), 2), "foreground_pid": pid.value, "expected_pid": identity[0], "native_focus_hwnd": focus, "expected_widget_hwnd": entry.winfo_id(), "native_focus_pid": focus_pid.value, "native_focus_root_hwnd": user.GetAncestor(focus, 2) if focus else None, "tk_focus_matches": root.focus_get() is entry}
                            proofs.append(proof)
                            return ownership_allowed(proof) and layout.current() == selection["selected"] and layout.owns_thread()

                        def down(self, key):
                            return bool(user.GetAsyncKeyState(key) & 0x8000)

                        def send(self, sequence):
                            packets = (Input * len(sequence))()
                            for index, (key, flags) in enumerate(sequence):
                                packets[index].type = 1
                                packets[index].payload.ki = Keyboard(key, 0, flags, 0, 0)
                            count = int(user.SendInput(len(sequence), packets, ctypes.sizeof(Input)))
                            data["injected_events"] += count
                            return count

                    native = Native()
                    if any(native.down(key) for key in (0x10, 0x11, 0x12, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, vk)):
                        raise GuardError("Modifier or target key held; no input admitted")
                    selected_probe = next(item for item in selection["probes"] if item["hkl"] == hex(selection["selected"]))
                    expected = next(item["altgr"] for item in selected_probe["keys"] if item["vk"] == vk)
                    row = {"phase": phase, "vk": vk, "expected_altgr": expected, "ownership": proofs}
                    data["observations"].append(row)
                    save()
                    row["input"] = guarded_chord(native, vk)
                    pump()
                    if not native.owns():
                        raise GuardError("Owned focus/layout changed after chord")
                    row.update(text=entry.get(), events=list(events), virtual_actions=list(virtual_actions), handler_results=list(handler_results))
                    save()
                    if phase == "plain_entry_baseline":
                        value = entry.get()
                        if value != expected or not is_altgr_text(value) or virtual_actions:
                            data.update(status="BLOCKED-ENV", reason="Plain Entry did not produce exactly the selected printable AltGr mapping without a clipboard action")
                            save()
                            pytest.skip("BLOCKED-ENV: printable native Entry baseline unavailable; app hook not run")
                        baselines[vk] = value
                    else:
                        assert entry.get() == baselines[vk] and not virtual_actions and "break" not in handler_results, row
            data["status"] = "PASS"
        data["layout_after"] = hex(layout.current())
        assert data["thread_layout_state"]["restored"]
    except GuardError as error:
        data.update(status="BLOCKED-ENV", reason=str(error))
        save()
        pytest.skip("BLOCKED-ENV: native input safety guard denied completion")
    except Exception as error:
        data.update(status="FAIL", error=type(error).__name__, message=str(error))
        raise
    finally:
        if "layout" in locals():
            data["layout_after"] = hex(layout.current())
        if root is not None:
            root.destroy()
        save()
