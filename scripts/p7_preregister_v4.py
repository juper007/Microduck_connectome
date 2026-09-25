"""Generate the new P7 steering manifest after selecting a pinned walking policy."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
from itertools import product
import json
import math
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


def validate_selection_metrics(summary: dict, policy: dict) -> None:
    if (summary["schema_version"] != "p7-02-model1250-policy-selection-v1"
            or summary["status"] != "preliminary_candidate_pending_full_p6_recert"
            or summary["diagnostic_only_not_g7"] is not True
            or policy["training_seed"] != 70202
            or policy["training_num_envs"] != 4096
            or policy["checkpoint_iteration"] != 1250
            or summary["checkpoint_sha256"] != policy["checkpoint_sha256"]
            or summary["onnx_sha256"] != policy["sha256"]):
        raise ValueError("candidate diagnostic provenance mismatch")
    runs = {row["trial"]: row for row in summary["runs"]}
    expected = {f"{side}05-r{index}" for side in ("plus", "minus")
                for index in range(1, 6)}
    if set(runs) != expected or len(summary["runs"]) != 10:
        raise ValueError("candidate diagnostic requires five fresh runs per sign")
    for name, row in runs.items():
        sign = 1 if name.startswith("plus") else -1
        first = row["first_qualifying_200ms"]
        if (sign * row["net_trunk_heading_rad"] <= 0
                or sign * first["heading_delta_rad"] < .02
                or not .2 <= first["duration_s"] <= .27
                or not math.isfinite(first["start_s"])
                or abs(row["external_yaw_rad_s"] - sign * .5) > 1e-6
                or row["loaded_policy_sha256"] != policy["sha256"]
                or row["fault_or_fall"]):
            raise ValueError(f"candidate diagnostic failed: {name}")


def validate_development_smoke(summary: dict) -> None:
    if summary["status"] != "completed" or len(summary["runs"]) != 5:
        raise ValueError("full-chain development smoke incomplete")
    expected = {("left", "static", True), ("right", "static", True),
                ("left", "slow_crossing", True), ("right", "slow_crossing", True),
                ("none", "none", False)}
    observed = {(row["target_side"], row["target_motion"], row["target_present"])
                for row in summary["runs"]}
    if observed != expected:
        raise ValueError("full-chain development classes incomplete")
    for row in summary["runs"]:
        target = row["target_present"]
        if (row["outcome"] != ("correct" if target else "no_target")
                or row["trial_exit"] != 0 or row["invalid_reasons"]
                or row["safety_limit_violations"] != 0):
            raise ValueError(f"full-chain development smoke failed: {row['trial_id']}")
        if target and (row["response"] is None
                       or row["response"]["heading_delta_rad"] *
                       (1 if row["target_side"] == "left" else -1) < .02):
            raise ValueError(f"full-chain first response failed: {row['trial_id']}")


def generate(*, policy: dict, validation: dict, controller_commit: str,
             committed_hashes: dict[str, str]) -> dict:
    required = {"sha256", "training_source_commit", "training_recipe_sha256",
                "checkpoint_sha256", "exporter_source_commit", "artifact_path",
                "checkpoint_path", "training_resume_manifest_path",
                "training_resume_manifest_sha256",
                "diagnostic_summary_path", "diagnostic_summary_sha256",
                "p7_development_smoke_summary_path",
                "p7_development_smoke_summary_sha256",
                "p6_recert_summary_path", "p6_recert_summary_sha256",
                "training_seed", "training_num_envs", "checkpoint_iteration"}
    if required - policy.keys():
        raise ValueError(f"missing policy provenance: {sorted(required - policy.keys())}")
    if set(committed_hashes) != set(HASH_PATHS_V4):
        raise ValueError("incomplete controller config hashes")
    if set(validation) != {"selection_summary_path", "selection_summary_sha256",
                           "development_smoke_summary_path", "development_smoke_summary_sha256",
                           "policy_metadata_path", "policy_metadata_sha256",
                           "affected_p6_summary_path", "affected_p6_summary_sha256"}:
        raise ValueError("incomplete policy validation evidence")
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
        "walking_policy_validation": validation,
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
    parser.add_argument("--selection-summary", type=Path, required=True)
    parser.add_argument("--development-smoke-summary", type=Path, required=True)
    parser.add_argument("--affected-p6-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "config/steering_experiment_v4.json")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    policy = json.loads(args.policy_metadata.read_text(encoding="utf-8"))
    policy_path = Path(policy["artifact_path"])
    if not policy_path.is_absolute() or sha256_file(policy_path) != policy["sha256"]:
        raise ValueError("policy path is not absolute or artifact hash differs")
    for path_key, hash_key in (("checkpoint_path", "checkpoint_sha256"),
                               ("training_resume_manifest_path", "training_resume_manifest_sha256")):
        path = Path(policy[path_key])
        if not path.is_absolute() or sha256_file(path) != policy[hash_key]:
            raise ValueError(f"policy provenance mismatch: {path_key}")
    selection = json.loads(args.selection_summary.read_text(encoding="utf-8"))
    if (args.selection_summary.resolve() != Path(policy["diagnostic_summary_path"]).resolve()
            or sha256_file(args.selection_summary) != policy["diagnostic_summary_sha256"]):
        raise ValueError("policy metadata is not bound to the selected diagnostic")
    validate_selection_metrics(selection, policy)
    for row in selection["runs"]:
        for name in ("raw", "readback"):
            if sha256_file(Path(row[f"{name}_path"])) != row[f"{name}_sha256"]:
                raise ValueError(f"candidate {name} artifact hash mismatch")
    smoke = json.loads(args.development_smoke_summary.read_text(encoding="utf-8"))
    if (args.development_smoke_summary.resolve() !=
            Path(policy["p7_development_smoke_summary_path"]).resolve()
            or sha256_file(args.development_smoke_summary) !=
            policy["p7_development_smoke_summary_sha256"]
            or selection["p7_development_smoke_summary_sha256"] !=
            policy["p7_development_smoke_summary_sha256"]):
        raise ValueError("policy metadata is not bound to P7 development smoke")
    validate_development_smoke(smoke)
    for row in smoke["runs"]:
        for name, digest in (("trace", "trace_sha256"),
                             ("trial_summary", "trial_summary_sha256"),
                             ("readback", "readback_sha256"),
                             ("trial_spec", "spec_sha256")):
            if sha256_file(Path(row[f"{name}_path"])) != row[digest]:
                raise ValueError(f"development {name} artifact hash mismatch")
    p6 = json.loads(args.affected_p6_summary.read_text(encoding="utf-8"))
    if (args.affected_p6_summary.resolve() != Path(policy["p6_recert_summary_path"]).resolve()
            or sha256_file(args.affected_p6_summary) != policy["p6_recert_summary_sha256"]):
        raise ValueError("policy metadata is not bound to the affected P6 evidence")
    if p6["result"] != "PASS" or p6["walking_policy_sha256"] != policy["sha256"]:
        raise ValueError("affected P6 recertification has not passed for this policy")
    validation = {
        "policy_metadata_path": str(args.policy_metadata.resolve()),
        "policy_metadata_sha256": sha256_file(args.policy_metadata),
        "selection_summary_path": str(args.selection_summary.resolve()),
        "selection_summary_sha256": sha256_file(args.selection_summary),
        "development_smoke_summary_path": str(args.development_smoke_summary.resolve()),
        "development_smoke_summary_sha256": sha256_file(args.development_smoke_summary),
        "affected_p6_summary_path": str(args.affected_p6_summary.resolve()),
        "affected_p6_summary_sha256": sha256_file(args.affected_p6_summary),
    }
    if subprocess.check_output(["git", "-C", str(ROOT), "status", "--porcelain"],
                               text=True).strip():
        raise RuntimeError("preregistration requires clean source checkout")
    head = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                   text=True).strip()
    hashes = {name: hashlib.sha256(subprocess.check_output(
        ["git", "-C", str(ROOT), "show", f"HEAD:{path}"])).hexdigest()
              for name, path in HASH_PATHS_V4.items()}
    args.output.write_text(json.dumps(generate(policy=policy, validation=validation,
                                              controller_commit=head,
                                              committed_hashes=hashes),
                                      sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
