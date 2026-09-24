"""Generate the new P7 steering manifest after selecting a pinned walking policy."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
from itertools import product
import json
from pathlib import Path
import random
import subprocess

from scripts.p7_preregister import HASH_PATHS, ROOT


SEED = 7022402
V3_PATH = ROOT / "config/steering_experiment_v3.json"
HASH_PATHS_V4 = {**HASH_PATHS, "steering_temporal_p7":
                 "config/steering_temporal_p7_v1.json"}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate(*, policy: dict, controller_commit: str,
             committed_hashes: dict[str, str]) -> dict:
    required = {"sha256", "training_source_commit", "training_recipe_sha256",
                "checkpoint_sha256", "exporter_source_commit", "artifact_path"}
    if required - policy.keys():
        raise ValueError(f"missing policy provenance: {sorted(required - policy.keys())}")
    if set(committed_hashes) != set(HASH_PATHS_V4):
        raise ValueError("incomplete controller config hashes")
    base = json.loads(V3_PATH.read_text(encoding="utf-8"))
    manifest = deepcopy(base)
    rng = random.Random(SEED)
    combos = list(product(("left", "right"), ("near_center", "medium", "far"),
                          ("static", "slow_crossing"), ("clean", "moderate")))
    classes = combos * 5
    rng.shuffle(classes)
    target_trials = [{
        "trial_id": f"p7-v4-target-{index:03d}",
        "seed": rng.randrange(2**32), "target_present": True,
        "target_side": side, "target_eccentricity": eccentricity,
        "target_motion": motion, "visual_noise_level": noise,
    } for index, (side, eccentricity, motion, noise) in enumerate(classes, 1)]
    noises = ["clean"] * 20 + ["moderate"] * 20
    rng.shuffle(noises)
    no_target_trials = [{
        "trial_id": f"p7-v4-no-target-{index:03d}",
        "seed": rng.randrange(2**32), "target_present": False,
        "target_side": "none", "target_eccentricity": "none",
        "target_motion": "none", "visual_noise_level": noise,
    } for index, noise in enumerate(noises, 1)]
    if len({trial["seed"] for trial in target_trials + no_target_trials}) != 160:
        raise RuntimeError("duplicate trial seed")
    manifest.update({
        "schema_version": "steering-experiment-v4",
        "experiment_version": "p7-steering-v4",
        "controller_commit_before_preregistration": controller_commit,
        "trial_order_randomization_seed": SEED,
        "config_sha256": committed_hashes,
        "walking_policy": policy,
        "target_trial_count": len(target_trials),
        "no_target_trial_count": len(no_target_trials),
        "target_trials": target_trials,
        "no_target_trials": no_target_trials,
        "scope": "official Thor robotd/MuJoCo and full MaleCNS loop; v3 negative batch remains immutable",
    })
    manifest["validity"].update({
        "pretrial_pose_acquisition_max_attempts": 3,
        "pretrial_policy_settle_s": 1.0,
        "replacement_policy": "none after trial start; record every pretrial acquisition attempt and fail if all three fail",
        "reset_policy": ("before each trial, official duck-sim down/up; load hash-pinned walk policy; "
                         "settle 1 s; check frozen initial-pose tolerance; at most three "
                         "fully logged down/up attempts before trial start"),
    })
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy-metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "config/steering_experiment_v4.json")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    policy = json.loads(args.policy_metadata.read_text(encoding="utf-8"))
    policy_path = Path(policy["artifact_path"])
    if not policy_path.is_absolute() or sha256_file(policy_path) != policy["sha256"]:
        raise ValueError("policy path is not absolute or artifact hash differs")
    if subprocess.check_output(["git", "-C", str(ROOT), "status", "--porcelain"],
                               text=True).strip():
        raise RuntimeError("preregistration requires clean source checkout")
    head = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                   text=True).strip()
    hashes = {name: hashlib.sha256(subprocess.check_output(
        ["git", "-C", str(ROOT), "show", f"HEAD:{path}"])).hexdigest()
              for name, path in HASH_PATHS_V4.items()}
    args.output.write_text(json.dumps(generate(policy=policy, controller_commit=head,
                                              committed_hashes=hashes),
                                      sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
