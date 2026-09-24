"""Generate the immutable Phase-7 trial manifest before final Thor trials."""

from __future__ import annotations

from itertools import product
import hashlib
import json
from pathlib import Path
import random
import subprocess


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER_COMMIT = "c3914df14a7dab844667a4f1ee816f125b5199c6"
SEED = 7022401
HASH_PATHS = {
    "scenario": "config/target_scenario_v1.json",
    "target_drive": "config/target_stimulus_drive_v3.json",
    "steering_decoder_p7": "config/steering_decoder_p7_v1.json",
    "sensory_mapping_p6": "config/sensory_mapping_v1.json",
    "dn_readout": "config/dn_readout_v1.json",
    "neural_model": "config/neural_model_v1.json",
    "safety": "config/safety_envelope_v1.json",
    "watchdog": "config/watchdog_v1.json",
    "motion_adapter": "config/motion_adapter_v1.json",
    "scheduler": "config/scheduler_v1.json",
    "telemetry": "config/telemetry_v1.json",
}


def generate() -> dict:
    rng = random.Random(SEED)
    combos = list(product(
        ("left", "right"), ("near_center", "medium", "far"),
        ("static", "slow_crossing"), ("clean", "moderate"),
    ))
    target_classes = combos * 4 + [combos[index] for index in (0, 6, 12, 18)]
    rng.shuffle(target_classes)
    targets = [
        {
            "trial_id": f"p7-target-{index:03d}",
            "seed": rng.randrange(2**32),
            "target_present": True,
            "target_side": side,
            "target_eccentricity": eccentricity,
            "target_motion": motion,
            "visual_noise_level": noise,
        }
        for index, (side, eccentricity, motion, noise) in enumerate(target_classes, 1)
    ]
    noises = ["clean"] * 20 + ["moderate"] * 20
    rng.shuffle(noises)
    no_targets = [
        {
            "trial_id": f"p7-no-target-{index:03d}",
            "seed": rng.randrange(2**32),
            "target_present": False,
            "target_side": "none",
            "target_eccentricity": "none",
            "target_motion": "none",
            "visual_noise_level": noise,
        }
        for index, noise in enumerate(noises, 1)
    ]
    return {
        "schema_version": "steering-experiment-v2",
        "experiment_version": "p7-steering-v2",
        "controller_commit_before_preregistration": CONTROLLER_COMMIT,
        "microduck_commit": "344925c9f8fa031f85428a305b1e8ec2eaae29c1",
        "microduck_rl_commit": "cb70b792312d559a4da09064d92009079671815f",
        "dataset": "male-cns:v1.0",
        "graph_key": "340f6a3180026f6c61f19ebc016ae8610ec9f4a07af2af589e4d6d89e5b31f70",
        "scenario_version": "target-scenario-v1",
        "trial_order_randomization_seed": SEED,
        # Hash committed Git bytes: Windows core.autocrlf must not change the
        # preregistered identities later observed on Thor's Linux checkout.
        "config_sha256": {name: hashlib.sha256(subprocess.check_output(
            ["git", "-C", str(ROOT), "show", f"HEAD:{path}"])).hexdigest()
                          for name, path in HASH_PATHS.items()},
        "target_response": {
            "heading_source": "read-only official MuJoCo body IMU quaternion via BodyReader",
            "direction_reference": "evaluator-only target bearing relative to robot heading at first response onset",
            "first_sustained_window_s": 0.2,
            "min_abs_heading_delta_rad": 0.02,
            "min_same_sign_increment_fraction": 0.8,
            "correct_direction_rate_min": 0.90,
            "center_tolerance_rad": 0.05,
        },
        "no_target_false_turn": {
            "warmup_excluded_s": 0.6,
            "min_abs_robot_facing_vyaw_radps": 0.10,
            "min_sustained_duration_s": 0.2,
            "false_turn_rate_max": 0.05,
        },
        "safety_limit_violations_max": 0,
        "reset_reference": {
            "heading_rad": 0.11884765359676912,
            "trunk_z_m": 0.1158945287893718,
            "heading_tolerance_rad": 0.02,
            "trunk_z_tolerance_m": 0.01,
            "source": "docs/evidence/p7-01/scenario-smoke-first-v1.json initial_poses[0]",
            "source_sha256": "3a0e88bb078b64c649d7b3c284ed7d228721bf4c9040141139ced879585ebaf6",
        },
        "validity": {
            "invalid_only_for": ["official simulator down/up reset failure",
                                 "initial pose outside preregistered tolerance",
                                 "official simulator/robotd unavailable before stimulus",
                                 "camera fixture or scenario invariant failure",
                                 "missing post-command robot state or MuJoCo heading",
                                 "unhealthy official runtime, missed control deadline, or scheduler exception"],
            "wrong_turn_and_no_response_are_evaluated_failures": True,
            "replacement_policy": "none; report all invalid trials and fail the trial-count floor",
            "reset_policy": "require successful official duck-sim down then up before every trial; verify initial pose against frozen P7-01 reference; initialize controller/runtime afresh",
        },
        "target_trial_count": len(targets),
        "no_target_trial_count": len(no_targets),
        "target_trials": targets,
        "no_target_trials": no_targets,
        "scope": "official Thor robotd/MuJoCo and full MaleCNS loop; development smoke and interrupted v1 batch excluded",
    }


if __name__ == "__main__":
    destination = ROOT / "config/steering_experiment_v2.json"
    destination.write_text(json.dumps(generate(), sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(destination)
