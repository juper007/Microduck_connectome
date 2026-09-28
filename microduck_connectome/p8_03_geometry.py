"""Pose-relative P8-03 virtual center; evaluator truth stays outside perception."""

from __future__ import annotations

import math

from .looming_scenario import VirtualTrial, validate_pose


def relative_trial(*, pose: dict, trial_id: str, seed: int, mode: str,
                   elapsed_after_arm_s: float) -> tuple[VirtualTrial, float]:
    """Place the visual sphere ahead of the measured trunk for one RGB frame."""
    validate_pose(pose)
    if mode not in ("static", "receding"):
        raise ValueError("P8-03 mode must be static or receding")
    if not math.isfinite(elapsed_after_arm_s) or elapsed_after_arm_s < 0:
        raise ValueError("invalid post-arm elapsed time")
    distance = 0.85 + (0.20 * elapsed_after_arm_s if mode == "receding" else 0.0)
    axis_x = math.cos(pose["heading_rad"])
    axis_y = math.sin(pose["heading_rad"])
    return (VirtualTrial(trial_id, seed, "static",
                         pose["x_m"] + distance * axis_x,
                         pose["y_m"] + distance * axis_y,
                         axis_x, axis_y), distance)
