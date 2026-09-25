"""Versioned, bounded relative-expansion estimators for P8-R3 development.

The output is an engineering visual feature, not a biological firing rate.
The v1 absolute-area estimator remains in ``looming.py`` unchanged.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math

from .looming import LoomingError


METHODS = ("log_area", "relative_radius", "log_area_regression")


@dataclass(frozen=True)
class LoomingV2Config:
    method: str = "log_area"
    full_scale_rate_per_s: float = 0.5
    area_epsilon: float = 1e-6
    max_gap_ms: int = 150
    window_ms: int = 200

    def __post_init__(self):
        if self.method not in METHODS:
            raise LoomingError("method must be a V2 expansion method")
        for name in ("full_scale_rate_per_s", "area_epsilon"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise LoomingError(f"{name} must be finite and > 0")
        if self.area_epsilon >= 1:
            raise LoomingError("area_epsilon must be < 1")
        if type(self.max_gap_ms) is not int or self.max_gap_ms <= 0:
            raise LoomingError("max_gap_ms must be a positive integer")
        if type(self.window_ms) is not int or self.window_ms <= 0:
            raise LoomingError("window_ms must be a positive integer")
        if self.method == "log_area_regression" and self.window_ms < self.max_gap_ms:
            raise LoomingError("regression window must cover the maximum valid frame gap")


class LoomingEstimatorV2:
    """Map relative target expansion to [0, 1] with explicit temporal semantics.

    A uses a two-frame log-area derivative. B uses relative apparent-radius
    expansion. C fits the log-area slope over a short, trailing time window.
    A and B are zero when the current observation does not grow. C can retain
    an earlier growth measurement within its configured window.
    """

    def __init__(self, config: LoomingV2Config | None = None):
        self.config = config if config is not None else LoomingV2Config()
        if not isinstance(self.config, LoomingV2Config):
            raise LoomingError("config must be LoomingV2Config")
        self.reset()

    def reset(self):
        self._samples: deque[tuple[int, float]] = deque()

    def update(self, target_area, *, timestamp_ns: int, valid: bool = True) -> float:
        if type(timestamp_ns) is not int or timestamp_ns < 0:
            raise LoomingError("timestamp_ns must be a non-negative integer")
        if type(valid) is not bool:
            raise LoomingError("valid must be bool")
        if not valid:
            self.reset()
            return 0.0
        if type(target_area) not in (int, float) or not math.isfinite(target_area) or not 0 <= target_area <= 1:
            raise LoomingError("target_area must be finite in [0,1]")
        area = float(target_area)
        if area == 0:
            self.reset()
            return 0.0

        if self._samples:
            previous_ns, previous_area = self._samples[-1]
            if timestamp_ns <= previous_ns:
                self.reset()
                raise LoomingError("valid timestamps must increase strictly")
            if timestamp_ns - previous_ns > self.config.max_gap_ms * 1_000_000:
                self.reset()

        if not self._samples:
            self._samples.append((timestamp_ns, area))
            return 0.0

        previous_ns, previous_area = self._samples[-1]
        delta_s = (timestamp_ns - previous_ns) / 1e9
        method = self.config.method
        epsilon = self.config.area_epsilon
        if method == "log_area":
            rate = (math.log(area + epsilon) - math.log(previous_area + epsilon)) / delta_s
        elif method == "relative_radius":
            previous_radius = math.sqrt(previous_area + epsilon)
            radius = math.sqrt(area + epsilon)
            rate = (radius - previous_radius) / (previous_radius * delta_s)
        else:
            rate = 0.0

        self._samples.append((timestamp_ns, area))
        if method == "log_area_regression":
            cutoff = timestamp_ns - self.config.window_ms * 1_000_000
            while self._samples[0][0] < cutoff:
                self._samples.popleft()
            if len(self._samples) >= 2:
                origin_ns = self._samples[0][0]
                times = [(ns - origin_ns) / 1e9 for ns, _ in self._samples]
                logs = [math.log(value + epsilon) for _, value in self._samples]
                mean_t = sum(times) / len(times)
                mean_log = sum(logs) / len(logs)
                denominator = sum((t - mean_t) ** 2 for t in times)
                if denominator > 0:
                    rate = sum((t - mean_t) * (y - mean_log) for t, y in zip(times, logs)) / denominator
        else:
            self._samples.popleft()

        return min(1.0, max(0.0, rate / self.config.full_scale_rate_per_s))
