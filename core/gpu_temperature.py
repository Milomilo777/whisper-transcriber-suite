"""Best-effort NVIDIA temperature pacing; no driver settings are changed."""
from __future__ import annotations

import math
import ctypes
import os
import shutil
import subprocess
import time
from collections.abc import Callable, Iterator, Mapping
from typing import Any


def _cuda_identity(index: int) -> str | None:
    # Ask the already-used CUDA driver for its physical PCI identity. CUDA
    # ordinals (including visibility masks) need not match nvidia-smi indices.
    try:
        driver = ctypes.WinDLL("nvcuda.dll") if os.name == "nt" else ctypes.CDLL("libcuda.so.1")
        device = ctypes.c_int()
        bus = ctypes.create_string_buffer(32)
        if (driver.cuInit(0) != 0 or driver.cuDeviceGet(ctypes.byref(device), index) != 0
                or driver.cuDeviceGetPCIBusId(bus, len(bus), device) != 0):
            return None
        return bus.value.decode("ascii") or None
    except (OSError, AttributeError, ValueError, UnicodeError):
        return None


def nvidia_temperature_probe(index: int) -> Callable[[], float | None]:
    identity = _cuda_identity(index)
    if identity is None:
        return lambda: None
    executable = shutil.which("nvidia-smi")
    if not executable:
        for path in (
            os.path.join(os.environ.get("SystemRoot", "C:/Windows"), "System32", "nvidia-smi.exe"),
            os.path.join(os.environ.get("ProgramFiles", "C:/Program Files"), "NVIDIA Corporation", "NVSMI", "nvidia-smi.exe"),
        ):
            if os.path.isfile(path):
                executable = path
                break

    def read() -> float | None:
        if not executable:
            return None
        try:
            result = subprocess.run(
                [executable, "-i", identity, "--query-gpu=temperature.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            value = float(result.stdout.strip())
            return value if result.returncode == 0 and math.isfinite(value) and 0 < value < 130 else None
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return None
    return read


class TemperatureController:
    """Predictive, bounded duty control around a two-degree thermal margin."""

    def __init__(self, ceiling: int, *, probe: Callable[[], float | None],
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 log: Callable[[str], None] = lambda _: None, task: Any = None,
                 cancelled: Callable[[], bool] | None = None,
                 paused: Callable[[], bool] | None = None) -> None:
        self.ceiling = ceiling
        self.probe, self.clock, self.sleep, self.log = probe, clock, sleep, log
        self.task = task
        self.cancelled = cancelled or (lambda: bool(task is not None and task.cancelled))
        self.paused = paused or (lambda: bool(task is not None and task.paused))
        self.share = 1.0
        self.active = True
        self._last: tuple[float, float] | None = None
        self._slope = 0.0
        self._reducing = False

    def before_step(self) -> None:
        now = self.clock()
        if not self.active or (self._last is not None and now - self._last[0] < 3):
            return
        try:
            temperature = self.probe()
        except Exception:
            temperature = None
        if temperature is None or not math.isfinite(temperature):
            self.active, self.share = False, 1.0
            self.log("GPU temperature limit inactive: temperature unavailable.")
            return
        if self._last is not None:
            slope = (temperature - self._last[1]) / max(.001, now - self._last[0])
            self._slope = .5 * self._slope + .5 * slope
        self._last = now, temperature
        # A smoothed 30-second lookahead eases load before the ceiling.
        # Integrate prediction error with a small gain; bound both duty and
        # its recovery rate. Negative slope cannot hide an already hot board.
        predicted = temperature + max(0.0, self._slope) * 30
        error = predicted - (self.ceiling - 2)
        if temperature >= self.ceiling:
            self.share = max(.25, self.share - .2)
        elif error > 0:
            self.share = max(.25, self.share - min(.15, .02 * error))
        elif temperature < self.ceiling - 4 and self._slope <= .02:
            self.share = min(1.0, self.share + .02)
        if self.share < 1 and not self._reducing:
            self._reducing = True
            self.log(f"GPU at {temperature:g} °C, ceiling {self.ceiling} °C: reducing GPU load to {self.share:.0%}")
        elif self.share == 1 and self._reducing:
            self._reducing = False
            self.log("GPU temperature cooled: full speed restored.")

    def _cancelled(self) -> bool:
        return self.cancelled()

    def _wait(self, gap: float) -> bool:
        # Pause/cancel are checked every 100 ms; worker heartbeats have their
        # own thread. The finite cooling budget never waits for a temperature.
        while gap > 1e-8 or self.paused():
            if self._cancelled():
                return False
            paused = self.paused()
            step = min(.1, gap) if gap > 1e-8 else .1
            self.sleep(step)
            self.before_step()
            if not paused:
                gap -= step
        return not self._cancelled()

    def pace(self, segments: Iterator[Any]) -> Iterator[Any]:
        iterator = iter(segments)
        try:
            while True:
                if not self._wait(0):
                    return
                self.before_step()
                started = self.clock()
                try:
                    segment = next(iterator)
                except StopIteration:
                    return
                work = max(0.0, self.clock() - started)
                yield segment  # deliver finished work before cooling
                if not self._wait(work * (1 / self.share - 1)):
                    return
        finally:
            close = getattr(iterator, "close", None)
            if close is not None:
                close()


def for_model(model: Any, config: Mapping[str, Any], *, task: Any = None,
              log: Callable[[str], None] = lambda _: None,
              cancelled: Callable[[], bool] | None = None,
              paused: Callable[[], bool] | None = None) -> TemperatureController | None:
    if not config.get("gpu_temperature_limit_enabled", True):
        return None
    inner = getattr(model, "model", model)
    if str(getattr(inner, "device", "")).split(":")[0] != "cuda":
        return None
    index = getattr(inner, "device_index", 0)
    if isinstance(index, (list, tuple)):
        if len(index) != 1:
            log("GPU temperature limit inactive: multiple decode devices.")
            return None
        index = index[0]
    from .config import gpu_temperature_ceiling
    return TemperatureController(gpu_temperature_ceiling(config),
                                 probe=nvidia_temperature_probe(int(index)), task=task, log=log,
                                 cancelled=cancelled, paused=paused)
