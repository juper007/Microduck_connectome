"""Frozen Phase-4 perception-frame construction and validation."""

import math


class PerceptionFrameError(ValueError):
    """A perception frame violates the frozen interface contract."""


def _unit(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PerceptionFrameError(f"{label} must be numeric")
    value = float(value)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise PerceptionFrameError(f"{label} must be finite in [0, 1]")
    return value


def _signed_unit(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PerceptionFrameError(f"{label} must be numeric")
    value = float(value)
    if not math.isfinite(value) or not -1.0 <= value <= 1.0:
        raise PerceptionFrameError(f"{label} must be finite in [-1, 1]")
    return value


def make_perception_frame(
    *,
    timestamp_ns,
    frame_id,
    target_x=0.0,
    target_area=0.0,
    looming=0.0,
    proximity_left=0.0,
    proximity_center=0.0,
    proximity_right=0.0,
    confidence=0.0,
    valid=True,
):
    if type(timestamp_ns) is not int or timestamp_ns < 0:
        raise PerceptionFrameError("timestamp_ns must be a non-negative integer")
    if type(frame_id) is not int or frame_id < 0:
        raise PerceptionFrameError("frame_id must be a non-negative integer")
    if type(valid) is not bool:
        raise PerceptionFrameError("valid must be bool")
    return {
        "timestamp_ns": timestamp_ns,
        "frame_id": frame_id,
        "target_x": _signed_unit(target_x, "target_x"),
        "target_area": _unit(target_area, "target_area"),
        "looming": _unit(looming, "looming"),
        "proximity_left": _unit(proximity_left, "proximity_left"),
        "proximity_center": _unit(proximity_center, "proximity_center"),
        "proximity_right": _unit(proximity_right, "proximity_right"),
        "confidence": _unit(confidence, "confidence"),
        "valid": valid,
    }


def neutral_perception_frame(*, timestamp_ns, frame_id, valid):
    return make_perception_frame(timestamp_ns=timestamp_ns, frame_id=frame_id, valid=valid)
