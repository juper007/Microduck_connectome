"""Stateless loss-safe ToF proximity encoder for P4-03."""

import math
from dataclasses import dataclass

from .perception_frame import make_perception_frame, neutral_perception_frame


class ToFError(ValueError):
    """ToF configuration or distance input violates the P4-03 contract."""


@dataclass(frozen=True)
class ToFConfig:
    near_mm: float = 100.0
    far_mm: float = 1000.0

    def __post_init__(self):
        near = self.near_mm
        far = self.far_mm
        for value, label in ((near, "near_mm"), (far, "far_mm")):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ToFError(f"{label} must be numeric")
            if not math.isfinite(float(value)) or float(value) <= 0.0:
                raise ToFError(f"{label} must be finite and > 0")
        if float(near) >= float(far):
            raise ToFError("near_mm must be < far_mm")


class ToFProximityEncoder:
    """Map explicit L/C/R distances to bounded proximity without retained state."""

    def __init__(self, config=None):
        self.config = config or ToFConfig()

    def _distance(self, value, label):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ToFError(f"{label} must be numeric")
        value = float(value)
        if not math.isfinite(value) or value <= 0.0:
            raise ToFError(f"{label} must be finite and > 0")
        return value

    def _proximity(self, distance_mm):
        near = float(self.config.near_mm)
        far = float(self.config.far_mm)
        if distance_mm <= near:
            return 1.0
        if distance_mm >= far:
            return 0.0
        return (far - distance_mm) / (far - near)

    def encode(
        self,
        *,
        left_mm,
        center_mm,
        right_mm,
        timestamp_ns,
        frame_id,
        source_valid=True,
    ):
        if type(source_valid) is not bool:
            raise ToFError("source_valid must be bool")
        readings = (left_mm, center_mm, right_mm)
        if not source_valid or any(value is None for value in readings):
            return neutral_perception_frame(
                timestamp_ns=timestamp_ns,
                frame_id=frame_id,
                valid=False,
            )

        left = self._distance(left_mm, "left_mm")
        center = self._distance(center_mm, "center_mm")
        right = self._distance(right_mm, "right_mm")
        return make_perception_frame(
            timestamp_ns=timestamp_ns,
            frame_id=frame_id,
            proximity_left=self._proximity(left),
            proximity_center=self._proximity(center),
            proximity_right=self._proximity(right),
            confidence=1.0,
            valid=True,
        )
