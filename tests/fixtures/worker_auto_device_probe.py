"""Fresh actual worker bootstrap with only hardware and external driver faked."""
import importlib
import io
import json
import logging
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import pytest
SOURCE_ROOT = Path(__file__).resolve().parents[2]
MISSING = 'Library libcublas.so.12 is not found or cannot be loaded'

def boot(monkeypatch, tmp_path, wizard_cpu=False, entrypoint='worker', broken_warning=False,
         flip_after_cpu_model=False, reconfigure_cpu=False, reload_gpu=False, initial_gpu_usable=False):
    assert not any((name == 'core' or name.startswith('core.') for name in sys.modules))
    monkeypatch.setenv('WTS_PROFILE_DIR', str(tmp_path))
    monkeypatch.syspath_prepend(str(SOURCE_ROOT))
    for name in ('ctranslate2', 'torch'):
        monkeypatch.setitem(sys.modules, name, None)
    fake_fw = ModuleType('faster_whisper')
    fake_fw.__path__ = []
    monkeypatch.setitem(sys.modules, 'faster_whisper', fake_fw)
    backend = ModuleType('core.backends.faster_whisper_be')
    loads = []

    class FakeModel:

        def __init__(self, path, *, device, compute_type):
            loads.append((device, compute_type))
            self.model = SimpleNamespace(device=device, compute_type=compute_type)
            if flip_after_cpu_model and device == 'cpu':
                monkeypatch.setattr(hardware, 'cuda_status', lambda: hardware.CudaStatus(
                    usable=True, gpu_present=True, compute_types={'float16'}))
    backend.WhisperModel = FakeModel
    backend.BatchedInferencePipeline = None
    fake_fw.WhisperModel = FakeModel
    fake_fw.BatchedInferencePipeline = None
    if entrypoint == 'worker' or entrypoint.startswith('legacy-'):
        monkeypatch.setitem(sys.modules, 'core.backends.faster_whisper_be', backend)
    import platformdirs
    for name in ('user_config_dir', 'user_cache_dir', 'user_log_dir', 'user_data_dir', 'user_state_dir'):
        monkeypatch.setattr(platformdirs, name, lambda *a, **k: str(tmp_path))
    config = importlib.import_module('core.config')
    hardware = importlib.import_module('core.hardware')
    monkeypatch.setattr(hardware, 'device_choice_from_hardware_file', lambda: ('cpu', 'int8') if wizard_cpu else None)
    monkeypatch.setattr(hardware, 'prepare_cuda_runtime', lambda: False)

    def missing_runtime(*a, **k):
        raise RuntimeError(MISSING)
    monkeypatch.setattr(hardware, 'warm_up_cuda_model', missing_runtime)

    def run(device, gpu_present):
        cfg = dict(config.DEFAULT_CONFIG, device=device, model_path=str(tmp_path), transcribe_backend='faster_whisper')
        monkeypatch.setattr(config, 'load_config', lambda *a, **k: dict(cfg))
        status = hardware.CudaStatus(usable=False, gpu_present=gpu_present, reason=MISSING if gpu_present else 'No NVIDIA GPU', missing_libs=('libcublas.so.12',) if gpu_present else ())
        if initial_gpu_usable:
            status = hardware.CudaStatus(usable=True, gpu_present=gpu_present, compute_types={'float16'})
        monkeypatch.setattr(hardware, 'cuda_status', lambda: status)
        phase = {'logging_setup': False}
        records = []

        class Capture(logging.Handler):

            def emit(self, record):
                records.append(dict(message=record.getMessage(), after_setup=phase['logging_setup'], level=record.levelname))
        handler = Capture()
        for logger_name in ('core.hardware', 'core.transcriber', 'core.worker', 'core.backends.faster_whisper_be'):
            logger = logging.getLogger(logger_name)
            monkeypatch.setattr(logger, 'handlers', [handler])
            monkeypatch.setattr(logger, 'propagate', False)
            monkeypatch.setattr(logger, 'level', logging.DEBUG)
        transcriber = importlib.import_module('core.transcriber')
        assert Path(transcriber.__file__).resolve().is_relative_to(SOURCE_ROOT)
        hub = importlib.import_module('core.hub')
        monkeypatch.setattr(hub, 'model_weights_present', lambda path: True)
        worker = importlib.import_module('core.worker')
        assert Path(worker.__file__).resolve().is_relative_to(SOURCE_ROOT)
        monkeypatch.setattr(worker, 'setup_logging', lambda *a, **k: phase.update(logging_setup=True))
        monkeypatch.setattr(worker, 'worker_log_filename', lambda: 'mock-worker.log')
        monkeypatch.setattr(worker, '_on_pipe_closed', lambda *a: None)
        extras = importlib.import_module('core.optional_deps')
        monkeypatch.setattr(extras, 'activate', lambda: None)
        monkeypatch.delenv('WHISPER_LIVE_MODEL', raising=False)
        monkeypatch.setattr(sys, 'stdin', io.StringIO('{"action":"shutdown"}\n'))
        stream = io.StringIO()
        monkeypatch.setattr(sys, 'stdout', stream)
        if entrypoint == 'worker':
            original_emit = worker.emit
            def emit(event, **payload):
                if broken_warning and event == 'log' and str(payload.get('message', '')).startswith('GPU unavailable'):
                    raise RuntimeError('Warning observer failed')
                original_emit(event, **payload)
            monkeypatch.setattr(worker, 'emit', emit)
            try:
                assert worker._main() == 0
            finally:
                if worker._heartbeat_stop is not None:
                    worker._heartbeat_stop.set()
            events = [json.loads(line) for line in stream.getvalue().splitlines()]
            ready = next((e for e in events if e['event'] == 'ready'))
        elif entrypoint.startswith('legacy-'):
            phase['logging_setup'] = True
            monkeypatch.setattr(transcriber, 'ensure_model', lambda *a, **k: str(tmp_path))
            events = []
            def status_cb(message):
                events.append({'event': 'log', 'message': message})
            if entrypoint == 'legacy-download':
                method = transcriber.load_model
            elif entrypoint == 'legacy-lazy':
                def method(callback):
                    transcriber.MODEL = None
                    transcriber._ensure_default_backend_loaded(callback)
                    return transcriber.MODEL is not None
            elif entrypoint == 'legacy-language':
                slot = transcriber._WhisperLanguageModel('fake/model', str(tmp_path))
                method = slot.load
            else:
                raise AssertionError('Unknown legacy entrypoint: '+entrypoint)
            assert method(status_cb)
            ready = vars(transcriber.get_effective_device('faster_whisper'))
        else:
            phase['logging_setup'] = True
            real_backend = importlib.import_module('core.backends.faster_whisper_be')
            assert Path(real_backend.__file__).resolve().is_relative_to(SOURCE_ROOT)
            monkeypatch.setattr(real_backend, 'ensure_model', lambda *a, **k: str(tmp_path))
            engine = importlib.import_module('core.backends').get_backend('faster_whisper')
            events = []
            def status_cb(message):
                if broken_warning and message.startswith('GPU unavailable'):
                    raise RuntimeError('Warning observer failed')
                events.append({'event': 'log', 'message': message})
            method = engine.load_existing if entrypoint == 'backend-existing' else engine.load
            assert method(status_cb)
            ready = dict(device=engine.device, compute_type=engine.compute_type,
                         requested_device=engine.requested_device, downgraded=engine.downgraded,
                         fallback_reason=getattr(engine, 'fallback_reason', ''))
        result = dict(entrypoint=entrypoint, config_device=device, gpu_present=gpu_present,
                      ready=ready, events=events, records=records, model_loads=loads)
        if entrypoint == 'worker' or entrypoint.startswith('legacy-'):
            task = SimpleNamespace(_telemetry_recovery='none')
            transcriber._remember_task_device(task, whisper=True)
            result['telemetry_recovery'] = task._telemetry_recovery
            existing = SimpleNamespace(_telemetry_recovery='cpu_fallback')
            transcriber._remember_task_device(existing, whisper=True)
            result['existing_decode_recovery'] = existing._telemetry_recovery
        (tmp_path / f'observed-{device}-gpu{int(gpu_present)}.local.json').write_text(json.dumps(result, indent=2))
        assert loads and loads[-1] == ('cpu', 'int8'), 'Actual product loader must reach the CPU backend'
        if device == 'cpu' or not gpu_present:
            assert loads == [('cpu', 'int8')], 'CPU controls must not attempt a nonexistent/unrequested GPU'
        else:
            assert len(loads) <= 2 and all((d == 'cuda' for d, _ in loads[:-1]))
        assert 'ctranslate2' not in sys.modules or sys.modules['ctranslate2'] is None
        assert 'torch' not in sys.modules or sys.modules['torch'] is None
        result['model_loads'] = list(loads)
        if flip_after_cpu_model:
            result['later_probe_usable'] = hardware.cuda_status().usable
        if reconfigure_cpu:
            assert entrypoint != 'worker'
            mark = len(events)
            cfg['device'] = 'cpu'
            assert method(status_cb)
            result['after_cpu'] = dict(device=engine.device, requested_device=engine.requested_device,
                                       downgraded=engine.downgraded, fallback_reason=engine.fallback_reason)
            result['after_cpu_messages'] = events[mark:]
        if reload_gpu:
            assert entrypoint.startswith('legacy-')
            monkeypatch.setattr(hardware, 'cuda_status', lambda: hardware.CudaStatus(
                usable=True, gpu_present=True, compute_types={'float16'}))
            monkeypatch.setattr(hardware, 'warm_up_cuda_model', lambda model: None)
            mark = len(events)
            assert method(status_cb)
            result['after_gpu'] = vars(transcriber.get_effective_device('faster_whisper'))
            result['after_gpu_loads'] = list(loads)
            result['after_gpu_messages'] = events[mark:]
        return result
    return run

if __name__ == "__main__":
    with pytest.MonkeyPatch.context() as patches:
        run = boot(patches, Path(sys.argv[1]).resolve(), sys.argv[4] == '1', sys.argv[5],
                   sys.argv[6] == '1', sys.argv[7] == '1', sys.argv[8] == '1',
                   len(sys.argv) > 9 and sys.argv[9] == '1',
                   len(sys.argv) > 10 and sys.argv[10] == '1')
        observation = run(sys.argv[2], sys.argv[3] == "1")
    print(json.dumps(observation))
