from pathlib import Path

import pytest

from microduck_connectome.perception_compositor import PerceptionPipeline
from microduck_connectome.target_scenario import (
    ECCENTRICITIES, TargetScenarioError, evaluator_truth,
    load_target_scenario_config, make_target_trial, pixels_sha256,
    render_camera_pixels,
)


CONFIG = load_target_scenario_config(Path(__file__).resolve().parents[1] / "config/target_scenario_v1.json")


def _trial(**overrides):
    values = dict(trial_id="target-1", seed=1234, target_present=True,
                  target_side="left", target_eccentricity="medium",
                  target_motion="static", visual_noise_level="clean",
                  initial_robot_heading_rad=0.2)
    values.update(overrides)
    return make_target_trial(CONFIG, **values)


def _perception(pixels, frame_id=1):
    now = 100_000_000 + frame_id * 40_000_000
    return PerceptionPipeline().process(
        pixels, camera_timestamp_ns=now, camera_frame_id=frame_id,
        tof_left_mm=CONFIG["tof_mm"], tof_center_mm=CONFIG["tof_mm"],
        tof_right_mm=CONFIG["tof_mm"], tof_timestamp_ns=now,
        tof_frame_id=frame_id, now_ns=now,
    )


def test_identical_seed_pose_and_time_replay_identical_pixels_and_perception():
    trial = _trial(visual_noise_level="moderate")
    args = dict(heading_rad=0.2, elapsed_s=0.9, frame_index=22)
    first = render_camera_pixels(CONFIG, trial, **args)
    second = render_camera_pixels(CONFIG, _trial(visual_noise_level="moderate"), **args)
    assert first == second and pixels_sha256(first) == pixels_sha256(second)
    assert _perception(first) == _perception(second)
    assert pixels_sha256(first) != pixels_sha256(render_camera_pixels(
        CONFIG, _trial(seed=1235, visual_noise_level="moderate"), **args))


@pytest.mark.parametrize("eccentricity", ECCENTRICITIES)
def test_left_right_labels_and_bins_reach_existing_perception_path(eccentricity):
    left = _trial(target_eccentricity=eccentricity, target_side="left")
    right = _trial(target_eccentricity=eccentricity, target_side="right")
    left_frame = _perception(render_camera_pixels(CONFIG, left, heading_rad=0.2, elapsed_s=1.0, frame_index=1))
    right_frame = _perception(render_camera_pixels(CONFIG, right, heading_rad=0.2, elapsed_s=1.0, frame_index=1))
    assert left_frame["valid"] and right_frame["valid"]
    assert left_frame["target_x"] < 0 < right_frame["target_x"]
    assert left.initial_target_bearing_rad > 0 > right.initial_target_bearing_rad


def test_eccentricity_magnitude_is_ordered_in_actual_detected_pixels():
    values = []
    for bin_name in ECCENTRICITIES:
        trial = _trial(target_eccentricity=bin_name)
        pixels = render_camera_pixels(CONFIG, trial, heading_rad=0.2, elapsed_s=1.0, frame_index=1)
        values.append(abs(_perception(pixels)["target_x"]))
    assert values[0] < values[1] < values[2]


def test_static_world_bearing_and_slow_crossing_are_deterministic():
    static = _trial()
    crossing = _trial(target_motion="slow_crossing")
    at_start = CONFIG["warmup_duration_s"]
    at_end = at_start + CONFIG["crossing_duration_s"]
    assert evaluator_truth(CONFIG, static, elapsed_s=at_start) == evaluator_truth(CONFIG, static, elapsed_s=at_end)
    first = _perception(render_camera_pixels(CONFIG, crossing, heading_rad=0.2, elapsed_s=at_start, frame_index=1))
    last = _perception(render_camera_pixels(CONFIG, crossing, heading_rad=0.2, elapsed_s=at_end, frame_index=2))
    assert first["target_x"] < 0 < last["target_x"]
    assert evaluator_truth(CONFIG, crossing, elapsed_s=at_start)["target_world_bearing_rad"] != evaluator_truth(CONFIG, crossing, elapsed_s=at_end)["target_world_bearing_rad"]


def test_no_target_is_valid_camera_frame_without_red_target():
    trial = _trial(target_present=False, target_side="none", target_eccentricity="none", target_motion="none")
    pixels = render_camera_pixels(CONFIG, trial, heading_rad=0.2, elapsed_s=1.0, frame_index=1)
    frame = _perception(pixels)
    assert frame["valid"] and frame["target_area"] == 0 and frame["confidence"] == 0
    assert evaluator_truth(CONFIG, trial, elapsed_s=1.0)["target_present"] is False


def test_warmup_has_no_target_then_moderate_noise_preserves_detectability():
    trial = _trial(visual_noise_level="moderate")
    warmup = _perception(render_camera_pixels(CONFIG, trial, heading_rad=0.2, elapsed_s=0.1, frame_index=1))
    active = _perception(render_camera_pixels(CONFIG, trial, heading_rad=0.2, elapsed_s=1.0, frame_index=2))
    assert warmup["valid"] and warmup["target_area"] == 0
    assert active["valid"] and active["target_area"] > 0


def test_evaluator_truth_is_absent_from_controller_pixel_observation():
    trial = _trial()
    pixels = render_camera_pixels(CONFIG, trial, heading_rad=0.2, elapsed_s=1.0, frame_index=1)
    assert isinstance(pixels, tuple)
    assert all(isinstance(pixel, tuple) and len(pixel) == 3 for row in pixels for pixel in row)
    assert "target_world_bearing_rad" in evaluator_truth(CONFIG, trial, elapsed_s=1.0)
    with pytest.raises(TargetScenarioError):
        _trial(target_present=False)
