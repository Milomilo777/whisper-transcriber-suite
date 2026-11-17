"""Predictive GPU pacing uses a virtual clock and never stops decoding."""
from types import SimpleNamespace

import pytest

from core import gpu_temperature as gt


class Clock:
    def __init__(self):
        self.now = 0.0
        self.gaps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.gaps.append(seconds)
        self.now += seconds


def controller(temperatures, **kwargs):
    clock = Clock()
    values = iter(temperatures)
    logs = []
    control = gt.TemperatureController(83, probe=lambda: next(values),
                                       clock=clock, sleep=clock.sleep, log=logs.append,
                                       **kwargs)
    return control, clock, logs


def test_anticipates_rising_temperature_and_recovers_gradually():
    c, clock, logs = controller([65, 68, 71, 74, 78, 83] + [55] * 180)
    shares = []
    for _ in range(186):
        clock.now += 3
        c.before_step()
        shares.append(c.share)
    assert shares[2] < 1  # still twelve degrees below the ceiling
    assert min(shares) >= .25
    assert shares[-1] == 1
    assert len(logs) == 2


def test_paced_iterator_finishes_and_closes_without_long_sleeps():
    c, clock, _ = controller([90] * 100)
    closed = []
    def decode():
        try:
            for i in range(12):
                clock.now += .5
                yield i
        finally:
            closed.append(True)
    assert list(c.pace(decode())) == list(range(12))
    assert closed == [True]
    assert clock.gaps and max(clock.gaps) <= .1


def test_unreadable_probe_becomes_inactive_once():
    c, clock, logs = controller([None])
    assert list(c.pace(iter(range(10)))) == list(range(10))
    assert not c.active and c.share == 1
    assert len(logs) == 1 and "temperature limit inactive" in logs[0]
    assert clock.gaps == []


@pytest.mark.parametrize("value,want", [(20, 60), (200, 90), (83, 83),
                                         (None, 83), ("bad", 83), (float("nan"), 83)])
def test_config_ceiling_clamped(value, want):
    from core.config import gpu_temperature_ceiling
    assert gpu_temperature_ceiling({"gpu_temperature_limit_c": value}) == want


@pytest.mark.parametrize("device,enabled", [("cpu", True), ("mps", True), ("cuda", False)])
def test_off_and_non_cuda_never_probe(monkeypatch, device, enabled):
    monkeypatch.setattr(gt, "nvidia_temperature_probe", lambda *_: pytest.fail("probed"))
    assert gt.for_model(SimpleNamespace(device=device, device_index=0),
                        {"gpu_temperature_limit_enabled": enabled}) is None


def test_pause_and_cancel_during_cooling():
    task = SimpleNamespace(paused=False, cancelled=False)
    c, clock, _ = controller([90] * 10, task=task)
    def sleep(seconds):
        clock.sleep(seconds)
        task.paused = True
        task.cancelled = len(clock.gaps) >= 4
    c.sleep = sleep
    def decode():
        for i in range(20):
            clock.now += 1
            yield i
    assert list(c.pace(decode())) == [0]
    assert task.cancelled


def test_thermal_model_settles_below_ceiling():
    clock = Clock()
    temperature = 65.0
    def sleep(seconds):
        nonlocal temperature
        temperature += (35 - temperature) * seconds / 40
        clock.sleep(seconds)
    c = gt.TemperatureController(83, probe=lambda: temperature, clock=clock,
                                 sleep=sleep)
    samples = []
    def decode():
        nonlocal temperature
        for _ in range(1800):
            temperature += (105 - temperature) * .25 / 40
            clock.now += .25
            samples.append(temperature)
            yield temperature
    assert len(list(c.pace(decode()))) == 1800
    assert max(samples) < 83
    assert 77 < samples[-1] < 83
    assert max(samples[-200:]) - min(samples[-200:]) < 2


@pytest.mark.parametrize("batched,options", [
    (False, {}), (True, {"batch_size": 8}),
    (False, {"clip_timestamps": "20,40"}),
    (False, {"vad_filter": False, "condition_on_previous_text": False}),
])
def test_task_adapters_pace_plain_batched_range_and_rescue(monkeypatch, batched, options):
    from core import transcriber as tr
    from core.task import TranscriptionTask
    c, clock, _ = controller([90] * 100)
    created = []
    class Engine:
        model = SimpleNamespace(device="cuda", device_index=[1])
        def transcribe(self, audio, **kwargs):
            def decode():
                for i in range(4):
                    clock.now += .5
                    yield SimpleNamespace(end=i + 1)
            return decode(), SimpleNamespace(language="en")
    engine = Engine()
    monkeypatch.setattr(tr, "MODEL", engine)
    monkeypatch.setattr(tr, "PIPELINE", engine)
    monkeypatch.setattr(tr, "_CUDA_BATCH_SIZE", 0)
    def create(*args, **kwargs):
        created.append(args)
        return c
    monkeypatch.setattr(gt, "for_model", create)
    task = TranscriptionTask("fake.wav")
    for _ in range(2):
        runner = tr._whisper_runner(task, batched=batched)
        segments, _ = runner.transcribe("fake.wav", **options)
        assert len(list(segments)) == 4
    assert len(created) == 1  # rescue/restart shares the task's thermal state
    assert clock.gaps


def test_probe_targets_physical_cuda_board(monkeypatch):
    seen = []
    class Driver:
        def cuInit(self, flags):
            return 0
        def cuDeviceGet(self, pointer, ordinal):
            seen.append(ordinal)
            pointer._obj.value = 7
            return 0
        def cuDeviceGetPCIBusId(self, buffer, size, device):
            assert device.value == 7
            buffer.value = b"0000:09:00.0"
            return 0
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "2,0")
    monkeypatch.setattr(gt.ctypes, "WinDLL", lambda _: Driver(), raising=False)
    monkeypatch.setattr(gt.ctypes, "CDLL", lambda _: Driver())
    monkeypatch.setattr(gt.shutil, "which", lambda _: "nvidia-smi")
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="79\n")
    monkeypatch.setattr(gt.subprocess, "run", run)
    assert gt.nvidia_temperature_probe(1)() == 79
    assert seen == [1]
    assert calls[0][0][2] == "0000:09:00.0"
    assert calls[0][1]["timeout"] == 1
    assert "creationflags" in calls[0][1]


def test_pause_resumes_decoding_without_a_temperature_stop():
    task = SimpleNamespace(paused=True, cancelled=False)
    c, clock, _ = controller([90] * 100, task=task)
    def sleep(seconds):
        clock.sleep(seconds)
        if len(clock.gaps) == 3:
            task.paused = False
    c.sleep = sleep
    assert list(c.pace(iter([1, 2, 3]))) == [1, 2, 3]
    assert len(clock.gaps) == 3


def test_nvidia_chunk_path_paces_and_cpu_fallback_does_not(monkeypatch):
    from core.backends import nvidia_asr as nv
    backend = nv.NvidiaAsrBackend(config={})
    backend._device = "cuda"
    backend._cuda_max_samples = 2
    c, clock, _ = controller([90] * 100)
    backend._temperature_controller = c
    monkeypatch.setattr(nv.time, "monotonic", clock)
    def run(audio):
        clock.now += .5
        return audio
    assert len(list(backend._decode_audio_parts(list(range(10)), run, None))) == 5
    assert clock.gaps
    backend._device = "cpu"
    clock.gaps.clear()
    assert len(list(backend._decode_audio_parts(list(range(10)), run, None))) == 5
    assert clock.gaps == []


def test_temperature_settings_reach_the_next_worker_task(monkeypatch):
    from core import task_settings, transcriber as tr
    from core.task import TranscriptionTask
    monkeypatch.setitem(tr.config, "gpu_temperature_limit_enabled", True)
    monkeypatch.setitem(tr.config, "gpu_temperature_limit_c", 83)
    task = TranscriptionTask("fake.wav")
    task.task_settings = task_settings.snapshot({"gpu_temperature_limit_enabled": False,
                                                "gpu_temperature_limit_c": 70})
    with tr._runtime_overrides_scope(task):
        assert tr.config["gpu_temperature_limit_enabled"] is False
        assert tr.config["gpu_temperature_limit_c"] == 70
    assert tr.config["gpu_temperature_limit_enabled"] is True
    assert tr.config["gpu_temperature_limit_c"] == 83

@pytest.mark.parametrize("fallback", [False, True])
def test_language_detection_paces_cuda_and_bypasses_cpu(fallback):
    from core.backends.faster_whisper_be import WhisperDecode
    c, clock, _ = controller([90] * 100)
    state = {"cuda": True, "calls": 0}
    result = ("en", .9, [("en", .9)])
    def detect(**kwargs):
        state["calls"] += 1
        clock.now += 3
        if fallback and state["cuda"]:
            raise RuntimeError("CUDA out of memory")
        return result
    def recover(options, oom):
        assert oom
        state["cuda"] = False
    model = SimpleNamespace(detect_language=detect)
    decode = WhisperDecode(lambda options: model, lambda: state["cuda"], recover, None,
                           temperature=lambda runner: c if state["cuda"] else None)
    for _ in range(5):
        assert decode.detect_language(audio="fake") == result
    if fallback:
        assert state["calls"] == 6
        assert clock.gaps == []
    else:
        assert clock.gaps and max(clock.gaps) <= .1


def test_language_detection_cancelled_before_gpu_work():
    from core.backends.faster_whisper_be import WhisperDecode
    c, _, _ = controller([90], cancelled=lambda: True)
    def detect(**kwargs):
        pytest.fail("cancelled detection reached the GPU")
    decode = WhisperDecode(lambda options: SimpleNamespace(detect_language=detect),
                           lambda: True, lambda options, oom: None, None, temperature=lambda runner: c)
    with pytest.raises(RuntimeError, match="cancel"):
        decode.detect_language(audio="fake")
