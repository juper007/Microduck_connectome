"""Deterministic target-area-rate looming estimator for P4-02."""

import math
from dataclasses import dataclass


class LoomingError(ValueError):
    """Looming input/configuration violates the P4-02 contract."""


@dataclass(frozen=True)
class LoomingConfig:
    full_scale_area_rate_per_s: float = 1.0
    max_gap_ms: int = 100

    def __post_init__(self):
        rate = self.full_scale_area_rate_per_s
        if isinstance(rate, bool) or not isinstance(rate, (int, float)):
            raise LoomingError("full_scale_area_rate_per_s must be numeric")
        rate = float(rate)
        if not math.isfinite(rate) or rate <= 0.0:
            raise LoomingError("full_scale_area_rate_per_s must be finite and > 0")
        if type(self.max_gap_ms) is not int or self.max_gap_ms <= 0:
            raise LoomingError("max_gap_ms must be a positive integer")


class LoomingEstimator:
    """Convert target-area growth rate into a bounded looming feature."""

    def __init__(self, config=None):
        self.config = config or LoomingConfig()
        self.reset()

    def reset(self):
        self._previous_area = None
        self._previous_timestamp_ns = None

    def _validate_area(self, target_area):
        if isinstance(target_area, bool) or not isinstance(target_area, (int, float)):
            raise LoomingError("target_area must be numeric")
        target_area = float(target_area)
        if not math.isfinite(target_area) or not 0.0 <= target_area <= 1.0:
            raise LoomingError("target_area must be finite in [0,1]")
        return target_area

    def update(self, target_area, *, timestamp_ns, valid=True):
        if type(timestamp_ns) is not int or timestamp_ns < 0:
            raise LoomingError("timestamp_ns must be a non-negative integer")
        if type(valid) is not bool:
            raise LoomingError("valid must be bool")

        if not valid:
            self.reset()
            return 0.0

        target_area = self._validate_area(target_area)
        if self._previous_timestamp_ns is None:
            self._previous_timestamp_ns = timestamp_ns
            self._previous_area = target_area
            return 0.0

        if timestamp_ns <= self._previous_timestamp_ns:
            self.reset()
            raise LoomingError("valid timestamps must increase strictly")

        delta_ns = timestamp_ns - self._previous_timestamp_ns
        max_gap_ns = self.config.max_gap_ms * 1_000_000
        previous_area = self._previous_area
        self._previous_timestamp_ns = timestamp_ns
        self._previous_area = target_area

        if delta_ns > max_gap_ns:
            return 0.0

        delta_area = target_area - previous_area
        if delta_area <= 0.0:
            return 0.0

        area_rate = delta_area / (delta_ns / 1_000_000_000.0)
        strength = area_rate / float(self.config.full_scale_area_rate_per_s)
        return max(0.0, min(1.0, strength))
