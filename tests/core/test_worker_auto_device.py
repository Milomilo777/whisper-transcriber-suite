"""The real worker must explain an AUTO preflight GPU downgrade after logging starts."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "tests/fixtures/worker_auto_device_probe.py"


def bootstrap(tmp_path, device, gpu_present, *, wizard_cpu=False, entrypoint="worker", broken_warning=False,
              flip_after_cpu_model=False, reconfigure_cpu=False):
    # Fresh interpreter: never clear live core modules in the full-suite process.
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("WHISPER_")}
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    run = subprocess.run([sys.executable, "-B", str(PROBE), str(tmp_path), device,
                          str(int(gpu_present)), str(int(wizard_cpu)), entrypoint, str(int(broken_warning)),
                          str(int(flip_after_cpu_model)), str(int(reconfigure_cpu))],
                         cwd=ROOT, env=env, capture_output=True, text=True, timeout=20,
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert run.returncode == 0, run.stderr + run.stdout
    return json.loads(run.stdout)


def messages_after_setup(result):
    return [r["message"] for r in result["records"]
            if r["after_setup"] and r["level"] in ("WARNING", "ERROR")] + [
        e.get("message", "") for e in result["events"] if e["event"] in ("log", "warning")]


@pytest.mark.parametrize("entrypoint", ["worker", "backend-existing", "backend-download"])
def test_auto_visible_gpu_missing_runtime_retains_intent_and_warning(tmp_path, entrypoint):
    result = bootstrap(tmp_path, "auto", True, entrypoint=entrypoint)
    ready = result["ready"]
    assert ready["device"] == "cpu" and result["model_loads"][-1] == ["cpu", "int8"]
    assert ready["requested_device"] in ("auto", "cuda"), ready
    assert ready["downgraded"] is True, ready
    assert "libcublas.so.12" in ready.get("fallback_reason", ""), ready
    assert any("libcublas.so.12" in message for message in messages_after_setup(result)), result


@pytest.mark.parametrize("device,gpu_present", [("cpu", True), ("auto", False)])
@pytest.mark.parametrize("entrypoint", ["worker", "backend-existing", "backend-download"])
def test_cpu_controls_do_not_falsely_warn_or_downgrade(tmp_path, device, gpu_present, entrypoint):
    result = bootstrap(tmp_path, device, gpu_present, entrypoint=entrypoint)
    assert result["ready"]["device"] == "cpu"
    assert result["ready"]["downgraded"] is False
    assert not any("libcublas" in message or "GPU unavailable" in message
                   for message in messages_after_setup(result))


@pytest.mark.parametrize("entrypoint", ["worker", "backend-existing", "backend-download"])
def test_persisted_cpu_choice_is_not_called_a_gpu_downgrade(tmp_path, entrypoint):
    result = bootstrap(tmp_path, "auto", True, wizard_cpu=True, entrypoint=entrypoint)
    assert result["ready"]["requested_device"] == "cpu"
    assert result["ready"]["downgraded"] is False
    assert not any("libcublas" in message or "GPU unavailable" in message
                   for message in messages_after_setup(result))


@pytest.mark.parametrize("config,wizard", [
    ({"device": "cuda"}, None), ({"device": "cpu"}, None),
    ({"device": "auto"}, ("cpu", "int8")),
])
def test_unrequested_gpu_metadata_is_not_probed(monkeypatch, config, wizard):
    from core import hardware
    calls = []
    monkeypatch.setattr(hardware, "device_choice_from_hardware_file", lambda: wizard)
    def unexpected_probe():
        calls.append("cuda_status")
        raise RuntimeError("Must not probe")
    monkeypatch.setattr(hardware, "cuda_status", unexpected_probe)
    assert hardware.resolve_device_for(config).fallback_reason is None
    assert calls == []


@pytest.mark.parametrize("entrypoint", ["worker", "backend-existing", "backend-download"])
def test_new_warning_observer_failure_cannot_fail_a_loaded_model(tmp_path, entrypoint):
    result = bootstrap(tmp_path, "auto", True, broken_warning=True, entrypoint=entrypoint)
    assert result["ready"]["device"] == "cpu" and result["ready"]["downgraded"] is True


def test_selection_carries_reason_without_consulting_a_later_probe(monkeypatch):
    from core import hardware
    missing = "Library libcublas.so.12 is not found or cannot be loaded"
    states = iter([hardware.CudaStatus(usable=False, gpu_present=True, reason=missing),
                   hardware.CudaStatus(usable=True, gpu_present=True, compute_types={"float16"})])
    calls = []
    def probe():
        calls.append("probe")
        return next(states)
    monkeypatch.setattr(hardware, "device_choice_from_hardware_file", lambda: None)
    monkeypatch.setattr(hardware, "cuda_status", probe)
    monkeypatch.setattr(hardware, "_cpu_compute_type", lambda value: "int8")
    selection = hardware.resolve_device_for({"device": "auto"})
    assert (selection.device, selection.compute_type) == ("cpu", "int8")
    assert calls == ["probe"]
    assert hardware.cuda_status().usable is True
    assert selection.fallback_reason == missing


def test_selection_reason_cannot_leak_into_explicit_cpu_config(monkeypatch):
    from core import hardware
    monkeypatch.setattr(hardware, "device_choice_from_hardware_file", lambda: None)
    monkeypatch.setattr(hardware, "cuda_status", lambda: hardware.CudaStatus(usable=False, gpu_present=True, reason="Missing runtime"))
    monkeypatch.setattr(hardware, "_cpu_compute_type", lambda value: "int8")
    assert hardware.resolve_device_for({"device": "auto"}).fallback_reason
    assert hardware.resolve_device_for({"device": "cpu"}).fallback_reason is None


@pytest.mark.parametrize("entrypoint", ["worker", "backend-existing", "backend-download"])
def test_real_load_keeps_selecting_reason_when_later_probe_changes(tmp_path, entrypoint):
    result = bootstrap(tmp_path, "auto", True, entrypoint=entrypoint, flip_after_cpu_model=True)
    assert result["later_probe_usable"] is True
    assert result["ready"]["device"] == "cpu" and result["ready"]["downgraded"] is True
    assert "libcublas.so.12" in result["ready"]["fallback_reason"]


@pytest.mark.parametrize("entrypoint", ["backend-existing", "backend-download"])
def test_explicit_cpu_after_auto_fallback_clears_old_intent_and_reason(tmp_path, entrypoint):
    result = bootstrap(tmp_path, "auto", True, entrypoint=entrypoint, reconfigure_cpu=True)
    assert result["ready"]["downgraded"] is True
    assert result["after_cpu"] == {"device": "cpu", "requested_device": "cpu",
                                   "downgraded": False, "fallback_reason": ""}
    assert not any("GPU unavailable" in row.get("message", "") for row in result["after_cpu_messages"])


@pytest.mark.parametrize("entrypoint", ["worker", "backend-existing", "backend-download"])
def test_explicit_cuda_load_failure_also_keeps_known_reason(tmp_path, entrypoint):
    result = bootstrap(tmp_path, "cuda", True, entrypoint=entrypoint)
    assert result["ready"]["requested_device"] == "cuda" and result["ready"]["downgraded"] is True
    assert "libcublas.so.12" in result["ready"].get("fallback_reason", "")


def test_bootstrap_child_never_requests_a_visible_console(monkeypatch, tmp_path):
    calls = []
    def run(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")
    monkeypatch.setattr(subprocess, "run", run)
    assert bootstrap(tmp_path, "cpu", False) == {}
    assert calls[0]["creationflags"] == (subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
