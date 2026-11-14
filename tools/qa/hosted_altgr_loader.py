"""Hosted-only AltGr loader; adopt with the reviewed public-safe companions."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

HELPER_BASE_SHA = "3adf5845e3d28d131dcb3cb78572c12de5fe5cf4"
KEYS = (65, 67, 88, 86)


def validate_hosted_context(env, actual_head, tracked_dirty, platform_name):
    """Pure admission check: this function never constructs a Windows API."""
    required = {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted", "RUNNER_OS": "Windows"}
    for name, value in required.items():
        if env.get(name) != value:
            raise RuntimeError("Hosted context denied: " + name)
    expected = env.get("QA_EXPECTED_HEAD", "")
    if not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise RuntimeError("QA_EXPECTED_HEAD must be exactly 40 lowercase hex characters")
    if platform_name != "win32" or expected != env.get("GITHUB_SHA") or expected != actual_head:
        raise RuntimeError("Hosted platform or exact source SHA mismatch")
    if tracked_dirty:
        raise RuntimeError("Tracked checkout changes are forbidden")
    if env.get("QA_ALTGR_KLID") != "00020407":
        raise RuntimeError("Only the preselected German Extended E1 layout is allowed")
    return {"source_head": expected, "klid": env["QA_ALTGR_KLID"], "hosted_context_verified": True}


def write_fallback_junit(output, status, reason):
    """Retain an explicit non-passing case when pytest could not emit XML."""
    path = Path(output) / "results.xml"
    if path.exists():
        return
    blocked = status == "BLOCKED-ENV"
    suite = ET.Element("testsuite", name="hosted_altgr_setup", tests="1",
                       skipped="1" if blocked else "0", errors="0" if blocked else "1", failures="0")
    case = ET.SubElement(suite, "testcase", classname="hosted_altgr_loader", name="native_acceptance_setup")
    ET.SubElement(case, "skipped" if blocked else "error", message=reason, type=status).text = reason
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


def final_verdict(rc, clean_xml, probe_status, missing_keys):
    if rc != 0 or not clean_xml or probe_status != "PASS":
        return ("BLOCKED-ENV" if probe_status == "BLOCKED-ENV" else "FAIL"), 1
    if missing_keys:
        return "INCOMPLETE-KEY-COVERAGE", 1
    return "PASS", 0


def main():
    env = os.environ.copy()
    workspace = Path(env["GITHUB_WORKSPACE"]).resolve(strict=True)

    def git(*args):
        return subprocess.check_output(["git", "-C", str(workspace), *args], text=True).strip()

    # No ctypes import or Win32 API construction occurs before this admission.
    context = validate_hosted_context(env, git("rev-parse", "HEAD"),
                                      git("status", "--porcelain", "--untracked-files=no"), sys.platform)
    run_id, attempt = env.get("GITHUB_RUN_ID", ""), env.get("GITHUB_RUN_ATTEMPT", "")
    if not run_id.isdecimal() or not attempt.isdecimal():
        raise RuntimeError("Numeric GitHub run ID and attempt are required")
    output = Path(env["RUNNER_TEMP"]).resolve(strict=True) / "wts-altgr"
    output.mkdir(exist_ok=False)
    job = "wts-hosted-altgr-" + run_id + "-" + attempt
    raw = output / "raw.json"
    if raw.exists():
        raise RuntimeError("Existing native receipt forbids replay")
    packet = workspace / "qa_native_packet"
    packet.mkdir(exist_ok=False)
    helpers = {}
    for name in ("test_altgr_acceptance.py", "altgr_guards.py"):
        source = Path(__file__).resolve().parent / name
        data = source.read_bytes()
        helpers[name] = hashlib.sha256(data).hexdigest()
        shutil.copyfile(source, packet / name)
    (packet / "plan.json").write_text(json.dumps({"job": job, "head": context["source_head"]}), encoding="utf-8")
    identity = {**context, "run_id": run_id, "run_attempt": attempt, "job": job,
                "helper_original_base_sha": HELPER_BASE_SHA, "helper_sha256": helpers,
                "layout_api_started": False, "status": "STARTED", "missing_keys": list(KEYS)}
    identity_path = output / "loaderidentity.json"

    def save():
        identity_path.write_text(json.dumps(identity, indent=2), encoding="utf-8")

    save()
    target = 0
    loaded_new = False
    load_attempted = False
    pytest_started = False
    exit_code = 1
    old_autoload = os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD")
    guards = None
    original_select = None
    try:
        import ctypes
        user = ctypes.windll.user32
        kernel = ctypes.windll.kernel32
        kernel.GetCurrentThreadId.restype = ctypes.c_ulong
        user.GetKeyboardLayout.argtypes = [ctypes.c_ulong]
        user.GetKeyboardLayout.restype = ctypes.c_void_p
        user.GetKeyboardLayoutList.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
        user.GetKeyboardLayoutList.restype = ctypes.c_int
        user.LoadKeyboardLayoutW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint]
        user.LoadKeyboardLayoutW.restype = ctypes.c_void_p
        user.ActivateKeyboardLayout.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        user.ActivateKeyboardLayout.restype = ctypes.c_void_p
        user.UnloadKeyboardLayout.argtypes = [ctypes.c_void_p]
        user.UnloadKeyboardLayout.restype = ctypes.c_int
        identity["layout_api_started"] = True
        save()
        thread = int(kernel.GetCurrentThreadId())
        original = int(user.GetKeyboardLayout(0) or 0)
        count = int(user.GetKeyboardLayoutList(0, None))
        if not original or not 0 < count <= 32:
            raise RuntimeError("Original hosted thread layout inventory is unavailable")
        handles = (ctypes.c_void_p * count)()
        received = int(user.GetKeyboardLayoutList(count, handles))
        if not 0 < received <= count:
            raise RuntimeError("Hosted layout inventory changed")
        before = [int(handles[index] or 0) for index in range(received)]
        identity.update(original_hkl=hex(original), loaded_before=[hex(hkl) for hkl in before], thread=thread)
        load_attempted = True
        target = int(user.LoadKeyboardLayoutW(context["klid"], 0) or 0)
        if not target:
            raise RuntimeError("Preselected hosted layout could not be loaded")
        loaded_new = target not in before
        identity.update(target_hkl=hex(target), newly_loaded=loaded_new, load_flags=0)
        save()
        if "altgr_guards" in sys.modules:
            raise RuntimeError("Unexpected preloaded guard module")
        spec = importlib.util.spec_from_file_location("altgr_guards", packet / "altgr_guards.py")
        guards = importlib.util.module_from_spec(spec)
        sys.modules["altgr_guards"] = guards
        spec.loader.exec_module(guards)
        original_select = guards.select_loaded_layout

        def select_target_only(api):
            # Retain real inventory and all mapping probes, restrict admission only.
            selection = original_select(api)
            row = next((item for item in selection["probes"] if item["hkl"] == hex(target)), None)
            eligible = [item["vk"] for item in row["keys"] if item["eligible"]] if row else []
            selection.update(selected=target if set(eligible) == set(KEYS) else None, eligible_keys=eligible,
                             hosted_requested_hkl=hex(target))
            identity.update(eligible_keys=eligible, missing_keys=[key for key in KEYS if key not in eligible],
                            real_layout_selection=selection)
            save()
            return selection

        guards.select_loaded_layout = select_target_only
        os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        import pytest
        pytest_started = True
        rc = int(pytest.main([str(packet / "test_altgr_acceptance.py"), "--noconftest",
                              "--rootdir=" + str(packet), "-o", "addopts=", "-p", "no:cacheprovider",
                              "-vv", "-rs", "--junitxml=" + str(output / "results.xml")]))
        identity["pytest_exit"] = rc
        if not raw.is_file():
            raise RuntimeError("Native probe produced no raw receipt")
        observation = json.loads(raw.read_text())
        identity["probe_status"] = observation.get("status")
        rows = observation.get("observations", [])
        covered = [key for key in KEYS if any(row.get("vk") == key and row.get("phase") == "actual_app_hook"
                   and row.get("text") == row.get("expected_altgr") and not row.get("virtual_actions")
                   and "break" not in row.get("handler_results", []) for row in rows)]
        identity["covered_keys"] = covered
        identity["missing_keys"] = [key for key in KEYS if key not in covered]
        xml = ET.parse(output / "results.xml").getroot()
        cases = list(xml.iter("testcase"))
        clean_xml = len(cases) == 1 and not any(list(xml.iter(kind)) for kind in ("skipped", "failure", "error"))
        identity["status"], exit_code = final_verdict(rc, clean_xml, observation.get("status"), identity["missing_keys"])
    except BaseException as error:
        identity.update(status="FAIL" if pytest_started else "BLOCKED-ENV", error=type(error).__name__, message=str(error))
    finally:
        cleanup_errors = []
        if guards is not None and original_select is not None:
            guards.select_loaded_layout = original_select
        if old_autoload is None:
            os.environ.pop("PYTEST_DISABLE_PLUGIN_AUTOLOAD", None)
        else:
            os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = old_autoload
        if load_attempted:
            try:
                if int(kernel.GetCurrentThreadId()) != thread:
                    raise RuntimeError("Hosted fixture thread changed")
                if int(user.GetKeyboardLayout(0) or 0) != original:
                    if not user.ActivateKeyboardLayout(original, 0):
                        raise RuntimeError("Original thread layout activation failed")
                if int(user.GetKeyboardLayout(0) or 0) != original:
                    raise RuntimeError("Original thread layout restoration is unverified")
                identity["original_layout_restored"] = True
            except BaseException as error:
                cleanup_errors.append(str(error))
        if loaded_new and target:
            try:
                if not identity.get("original_layout_restored"):
                    raise RuntimeError("Retaining newly loaded layout because original restoration failed")
                if not user.UnloadKeyboardLayout(target):
                    raise RuntimeError("Newly loaded layout could not be unloaded")
                identity["new_layout_unloaded"] = True
            except BaseException as error:
                cleanup_errors.append(str(error))
        if cleanup_errors:
            identity.update(status="FAIL-CLEANUP", cleanup_errors=cleanup_errors)
            exit_code = 1
        write_fallback_junit(output, identity["status"], identity.get("message", "Native acceptance did not emit JUnit"))
        save()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
