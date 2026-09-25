"""Deterministic virtual visual obstacle driven by official MuJoCo robot pose.

The virtual sphere has no MuJoCo collision geom. Evaluator truth is deliberately
separate from the RGB-only perception interface.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import random

MOTIONS = ("approaching", "static", "receding")


class LoomingScenarioError(ValueError):
    pass


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def load_config(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    required = {
        "schema_version", "representation", "image_width_px", "image_height_px",
        "horizontal_fov_half_angle_rad", "virtual_sphere_radius_m",
        "nominal_robot_planar_extent_m", "robot_extent_allowance_m",
        "additional_boundary_margin_m", "safety_boundary_center_distance_m",
        "initial_center_distance_m", "approach_speed_m_s", "warmup_duration_s",
        "trial_duration_s", "frame_period_s", "tof_mm", "initial_pose_tolerance",
        "geometry_provenance",
    }
    if set(value) != required or value["schema_version"] not in {
        "looming-scenario-v1", "looming-scenario-rgb-v2"
    }:
        raise LoomingScenarioError("scenario schema mismatch")
    if value["representation"] != "virtual/synthetic visual obstacle; no MuJoCo obstacle contact":
        raise LoomingScenarioError("representation mismatch")
    if any(type(value[k]) is not int or value[k] < 3 or value[k] % 2 == 0 for k in ("image_width_px", "image_height_px")):
        raise LoomingScenarioError("invalid image dimensions")
    if value["schema_version"] == "looming-scenario-rgb-v2" and (
        value["image_width_px"], value["image_height_px"]
    ) != (129, 65):
        raise LoomingScenarioError("RGB v2 resolution must remain 129x65")
    numeric = ("horizontal_fov_half_angle_rad", "virtual_sphere_radius_m",
               "nominal_robot_planar_extent_m", "robot_extent_allowance_m",
               "additional_boundary_margin_m", "safety_boundary_center_distance_m",
               "initial_center_distance_m", "approach_speed_m_s",
               "warmup_duration_s", "trial_duration_s", "frame_period_s")
    if any(not _finite(value[k]) or value[k] <= 0 for k in numeric):
        raise LoomingScenarioError("invalid numeric parameter")
    if not 0 < value["horizontal_fov_half_angle_rad"] < math.pi / 2:
        raise LoomingScenarioError("invalid FOV")
    expected = (value["virtual_sphere_radius_m"] + value["nominal_robot_planar_extent_m"]
                + value["robot_extent_allowance_m"] + value["additional_boundary_margin_m"])
    if not math.isclose(expected, value["safety_boundary_center_distance_m"], abs_tol=1e-12):
        raise LoomingScenarioError("boundary decomposition mismatch")
    if value["initial_center_distance_m"] <= expected or value["trial_duration_s"] <= value["warmup_duration_s"]:
        raise LoomingScenarioError("invalid geometry or duration")
    if type(value["tof_mm"]) is not int or value["tof_mm"] <= 0:
        raise LoomingScenarioError("invalid ToF fixture")
    if set(value["initial_pose_tolerance"]) != {"x_m", "y_m", "heading_rad", "trunk_z_m"}:
        raise LoomingScenarioError("pose tolerance mismatch")
    if any(not _finite(v) or v <= 0 for v in value["initial_pose_tolerance"].values()):
        raise LoomingScenarioError("invalid pose tolerance")
    return value


def validate_pose(pose):
    if not isinstance(pose, dict) or set(pose) != {"x_m", "y_m", "heading_rad", "trunk_z_m"}:
        raise LoomingScenarioError("official pose fields mismatch")
    if any(not _finite(v) for v in pose.values()):
        raise LoomingScenarioError("official pose is nonfinite")
    return pose


@dataclass(frozen=True)
class VirtualTrial:
    trial_id: str
    seed: int
    motion: str
    anchor_x_m: float
    anchor_y_m: float
    axis_x: float
    axis_y: float


def make_trial(config, *, trial_id, seed, motion, initial_pose):
    validate_pose(initial_pose)
    if not isinstance(trial_id, str) or not trial_id or type(seed) is not int or not 0 <= seed < 2**32 or motion not in MOTIONS:
        raise LoomingScenarioError("trial spec invalid")
    # Seed is frozen in manifest; <=1 cm axial jitter, independent of frame rate.
    jitter = (random.Random(seed).random() * 2 - 1) * 0.01
    axis_x, axis_y = math.cos(initial_pose["heading_rad"]), math.sin(initial_pose["heading_rad"])
    distance = config["initial_center_distance_m"] + jitter
    return VirtualTrial(trial_id, seed, motion,
                        initial_pose["x_m"] + distance * axis_x,
                        initial_pose["y_m"] + distance * axis_y, axis_x, axis_y)


def sphere_center(config, trial, elapsed_s):
    if not _finite(elapsed_s) or elapsed_s < 0:
        raise LoomingScenarioError("invalid elapsed time")
    dt = max(0.0, elapsed_s - config["warmup_duration_s"])
    direction = {"approaching": -1, "static": 0, "receding": 1}[trial.motion]
    displacement = direction * config["approach_speed_m_s"] * dt
    return trial.anchor_x_m + displacement * trial.axis_x, trial.anchor_y_m + displacement * trial.axis_y


def evaluator_truth(config, trial, *, pose, elapsed_s):
    """Evaluator-only distance. Never pass this mapping to PerceptionPipeline."""
    validate_pose(pose)
    x, y = sphere_center(config, trial, elapsed_s)
    distance = math.hypot(x - pose["x_m"], y - pose["y_m"])
    relative_speed = config["approach_speed_m_s"] if trial.motion == "approaching" else 0.0
    margin = distance - config["safety_boundary_center_distance_m"]
    return {
        "virtual_sphere_world_x_m": x, "virtual_sphere_world_y_m": y,
        "center_distance_m": distance, "distance_to_boundary_m": margin,
        "time_to_boundary_s_if_robot_stationary": max(0.0, margin) / relative_speed if relative_speed else None,
        "crossed_virtual_boundary": margin <= 0,
        "representation": config["representation"],
    }


def render_pixels(config, trial, *, pose, elapsed_s):
    """RGB pixels only; caller passes this array, never trial/truth, to perception."""
    validate_pose(pose)
    cx, cy = sphere_center(config, trial, elapsed_s)
    dx, dy = cx - pose["x_m"], cy - pose["y_m"]
    distance = math.hypot(dx, dy)
    bearing = (math.atan2(dy, dx) - pose["heading_rad"] + math.pi) % (2 * math.pi) - math.pi
    width, height = config["image_width_px"], config["image_height_px"]
    pixels = [[(0, 0, 0) for _ in range(width)] for _ in range(height)]
    half_fov = config["horizontal_fov_half_angle_rad"]
    if distance <= config["virtual_sphere_radius_m"]:
        raise LoomingScenarioError("virtual camera entered sphere")
    if abs(bearing) <= half_fov:
        center_x = round((1 - bearing / half_fov) * (width - 1) / 2)
        center_y = height // 2
        radius_px = max(1, round(math.asin(config["virtual_sphere_radius_m"] / distance) / half_fov * (width - 1) / 2))
        for y in range(max(0, center_y - radius_px), min(height, center_y + radius_px + 1)):
            for x in range(max(0, center_x - radius_px), min(width, center_x + radius_px + 1)):
                if (x - center_x) ** 2 + (y - center_y) ** 2 <= radius_px ** 2:
                    pixels[y][x] = (255, 0, 0)
    return tuple(tuple(row) for row in pixels)


def pixels_sha256(pixels):
    return hashlib.sha256(bytes(component for row in pixels for pixel in row for component in pixel)).hexdigest()
