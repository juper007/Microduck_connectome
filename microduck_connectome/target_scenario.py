"""Deterministic Phase-7 camera fixture with separate evaluator truth."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import random


class TargetScenarioError(ValueError):
    """A frozen visual scenario or trial parameter is invalid."""


SIDES = ("left", "right")
ECCENTRICITIES = ("near_center", "medium", "far")
MOTIONS = ("static", "slow_crossing")
NOISE_LEVELS = ("clean", "moderate")


def load_target_scenario_config(path: str | Path) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise TargetScenarioError("cannot load target scenario config") from error
    required = {
        "schema_version", "source", "image_width_px", "image_height_px",
        "target_square_width_px", "horizontal_fov_half_angle_rad",
        "eccentricity_center_rad", "eccentricity_jitter_rad",
        "crossing_duration_s", "warmup_duration_s", "trial_timeout_s",
        "tof_mm", "visual_noise", "initial_pose_tolerance", "scope",
    }
    if set(value) != required or value["schema_version"] != "target-scenario-v1":
        raise TargetScenarioError("target scenario schema mismatch")
    width, height, marker = (value[key] for key in ("image_width_px", "image_height_px", "target_square_width_px"))
    if any(type(item) is not int or item < 3 or item % 2 == 0 for item in (width, height, marker)):
        raise TargetScenarioError("image and marker sizes must be odd integers >=3")
    if marker > min(width, height):
        raise TargetScenarioError("marker does not fit image")
    half_fov = value["horizontal_fov_half_angle_rad"]
    if not isinstance(half_fov, (int, float)) or not 0 < half_fov < math.pi / 2:
        raise TargetScenarioError("invalid horizontal field of view")
    centers = value["eccentricity_center_rad"]
    if set(centers) != set(ECCENTRICITIES):
        raise TargetScenarioError("eccentricity bins mismatch")
    near, medium, far = (centers[name] for name in ECCENTRICITIES)
    jitter = value["eccentricity_jitter_rad"]
    if not (0 < jitter < near and near + jitter < medium - jitter < medium + jitter < far - jitter < far + jitter < half_fov):
        raise TargetScenarioError("eccentricity bins overlap or leave the field of view")
    if any(not isinstance(value[name], (int, float)) or value[name] <= 0 for name in ("crossing_duration_s", "warmup_duration_s", "trial_timeout_s")):
        raise TargetScenarioError("invalid trial timing")
    if value["trial_timeout_s"] <= value["warmup_duration_s"] + value["crossing_duration_s"]:
        raise TargetScenarioError("trial timeout must exceed the crossing interval")
    if type(value["tof_mm"]) is not int or value["tof_mm"] <= 0:
        raise TargetScenarioError("invalid ToF fixture distance")
    noise = value["visual_noise"]
    if set(noise) != set(NOISE_LEVELS):
        raise TargetScenarioError("noise levels mismatch")
    for level in NOISE_LEVELS:
        spec = noise[level]
        if set(spec) != {"target_pixel_dropout", "background_rgb_jitter"}:
            raise TargetScenarioError("noise rule fields mismatch")
        if not 0 <= spec["target_pixel_dropout"] < 1 or type(spec["background_rgb_jitter"]) is not int or not 0 <= spec["background_rgb_jitter"] < 128:
            raise TargetScenarioError("invalid visual noise rule")
    if set(value["initial_pose_tolerance"]) != {"heading_rad", "trunk_z_m"}:
        raise TargetScenarioError("initial pose tolerance fields mismatch")
    if any(not isinstance(item, (int, float)) or item <= 0 for item in value["initial_pose_tolerance"].values()):
        raise TargetScenarioError("initial pose tolerances must be positive")
    return value


def wrap_angle(angle: float) -> float:
    return (angle + math.pi) % (2 * math.pi) - math.pi


@dataclass(frozen=True)
class TargetTrial:
    trial_id: str
    seed: int
    target_present: bool
    target_side: str
    target_eccentricity: str
    target_motion: str
    visual_noise_level: str
    initial_robot_heading_rad: float
    initial_target_bearing_rad: float | None
    target_world_anchor_rad: float | None
    warmup_duration_s: float
    stimulus_start_s: float
    trial_timeout_s: float

    def metadata(self) -> dict:
        """Evaluator-only metadata; never pass this to the controller."""
        return asdict(self)


def make_target_trial(
    config: dict, *, trial_id: str, seed: int, target_present: bool,
    target_side: str = "none", target_eccentricity: str = "none",
    target_motion: str = "none", visual_noise_level: str = "clean",
    initial_robot_heading_rad: float,
) -> TargetTrial:
    if not isinstance(trial_id, str) or not trial_id or type(seed) is not int or not 0 <= seed < 2**32:
        raise TargetScenarioError("trial id or seed is invalid")
    if type(target_present) is not bool or visual_noise_level not in NOISE_LEVELS:
        raise TargetScenarioError("target presence or visual condition is invalid")
    if not math.isfinite(initial_robot_heading_rad):
        raise TargetScenarioError("initial robot heading must be finite")
    if target_present:
        if target_side not in SIDES or target_eccentricity not in ECCENTRICITIES or target_motion not in MOTIONS:
            raise TargetScenarioError("target class is invalid")
        rng = random.Random(seed)
        jitter = (2 * rng.random() - 1) * config["eccentricity_jitter_rad"]
        magnitude = config["eccentricity_center_rad"][target_eccentricity] + jitter
        initial_bearing = magnitude if target_side == "left" else -magnitude
        world_anchor = wrap_angle(initial_robot_heading_rad + initial_bearing)
    else:
        if (target_side, target_eccentricity, target_motion) != ("none", "none", "none"):
            raise TargetScenarioError("no-target trial cannot carry a target class")
        initial_bearing = world_anchor = None
    return TargetTrial(
        trial_id=trial_id, seed=seed, target_present=target_present,
        target_side=target_side, target_eccentricity=target_eccentricity,
        target_motion=target_motion, visual_noise_level=visual_noise_level,
        initial_robot_heading_rad=initial_robot_heading_rad,
        initial_target_bearing_rad=initial_bearing,
        target_world_anchor_rad=world_anchor,
        warmup_duration_s=config["warmup_duration_s"],
        stimulus_start_s=config["warmup_duration_s"],
        trial_timeout_s=config["trial_timeout_s"],
    )


def evaluator_truth(config: dict, trial: TargetTrial, *, elapsed_s: float) -> dict:
    """Ground truth for scoring, kept outside rendered controller input."""
    if not math.isfinite(elapsed_s) or elapsed_s < 0:
        raise TargetScenarioError("elapsed_s must be finite and non-negative")
    if not trial.target_present or elapsed_s < trial.stimulus_start_s:
        return {"target_present": False, "target_world_bearing_rad": None}
    if trial.target_motion == "static":
        world_bearing = trial.target_world_anchor_rad
    else:
        fraction = min(1.0, (elapsed_s - trial.stimulus_start_s) / config["crossing_duration_s"])
        relative_to_start = trial.initial_target_bearing_rad * (1.0 - 2.0 * fraction)
        world_bearing = wrap_angle(trial.initial_robot_heading_rad + relative_to_start)
    return {"target_present": True, "target_world_bearing_rad": world_bearing}


def render_camera_pixels(
    config: dict, trial: TargetTrial, *, heading_rad: float,
    elapsed_s: float, frame_index: int,
) -> tuple[tuple[tuple[int, int, int], ...], ...]:
    """Return RGB pixels only; no side/bearing/label enters perception."""
    if not math.isfinite(heading_rad) or type(frame_index) is not int or frame_index < 0:
        raise TargetScenarioError("heading or frame index is invalid")
    truth = evaluator_truth(config, trial, elapsed_s=elapsed_s)
    width, height = config["image_width_px"], config["image_height_px"]
    noise = config["visual_noise"][trial.visual_noise_level]
    seed_bytes = hashlib.sha256(f"target-scenario-v1:{trial.seed}:{frame_index}".encode("ascii")).digest()
    rng = random.Random(int.from_bytes(seed_bytes, "big"))
    jitter = noise["background_rgb_jitter"]
    pixels = [
        [(rng.randrange(jitter + 1), rng.randrange(jitter + 1), rng.randrange(jitter + 1))
         if jitter else (0, 0, 0) for _ in range(width)]
        for _ in range(height)
    ]
    if truth["target_present"]:
        relative = wrap_angle(truth["target_world_bearing_rad"] - heading_rad)
        half_fov = config["horizontal_fov_half_angle_rad"]
        if abs(relative) <= half_fov:
            # Positive simulator yaw is left. Image coordinates increase right,
            # so a positive/left bearing renders at negative detector target_x.
            center_x = round((1.0 - relative / half_fov) * (width - 1) / 2.0)
            center_y = height // 2
            radius = config["target_square_width_px"] // 2
            for y in range(max(0, center_y - radius), min(height, center_y + radius + 1)):
                for x in range(max(0, center_x - radius), min(width, center_x + radius + 1)):
                    if rng.random() >= noise["target_pixel_dropout"]:
                        pixels[y][x] = (255, 0, 0)
            # Preserve a detectable marker at every in-FOV target frame.
            pixels[center_y][center_x] = (255, 0, 0)
    return tuple(tuple(row) for row in pixels)


def pixels_sha256(pixels) -> str:
    payload = bytes(channel for row in pixels for pixel in row for channel in pixel)
    return hashlib.sha256(payload).hexdigest()
