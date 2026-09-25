"""Deterministically preregister independent P7-03 no-target controls."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "config/steering_experiment_v4.json"
OUTPUT = ROOT / "config/steering_no_target_p7_03_v1.json"
SOURCE_SHA256 = "f24170521f049cec6a65a88285925343316f84ce9bdaf59a1a668257db5460cd"
BASE_COMMIT = "41a9849325e2a52714ecd23fd75c2a394c28c658"
SEED = 7030301
TARGET_SUMMARY_PATH = (
    "/home/juper007/projects/microduck-connectome-thor/evidence/p7-02/"
    "final-target-v4-model1250-fdde4578/batch-summary.json"
)
TARGET_SUMMARY_SHA256 = "8f2e7d797b1bf01a4249f9cad9e17ca8c57e4574750e653d7d56a438347192ca"
TARGET_JOURNAL_PATH = (
    "/home/juper007/projects/microduck-connectome-thor/evidence/p7-02/"
    "final-target-v4-model1250-fdde4578/trial-results.jsonl"
)
TARGET_JOURNAL_SHA256 = "f9379d4911cc2075d28e09f579c583dca87403dd1617e0bde487adf79f54225b"
EARLY_CONTROL_SUMMARY_SHA256 = "90284a8d680892ed5a77f25635b561b7e1dbe726188c78c8be8640f0400d78be"
EARLY_CONTROL_JOURNAL_SHA256 = "ce90c78c62340b50c191b3910c15a98fa3f7fcb38ceaf2bb1820db89e7b4e7e1"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate(source: dict, *, source_sha256: str) -> dict:
    if (source_sha256 != SOURCE_SHA256
            or source["schema_version"] != "steering-experiment-v4"
            or source["experiment_version"] != "p7-steering-v4"
            or source["target_trial_count"] != 120
            or source["no_target_trial_count"] != 40
            or len(source["target_trials"]) != 120
            or len(source["no_target_trials"]) != 40
            or source["walking_policy"]["sha256"] !=
            "98c3ea73fa6bb196bcf16586cf38b9fffb782787447d638fa1c1028df9082c1a"
            or source["no_target_false_turn"] != {
                "false_turn_rate_max": .05,
                "min_abs_robot_facing_vyaw_radps": .1,
                "min_sustained_duration_s": .2,
                "warmup_excluded_s": .6,
            }):
        raise ValueError("P7-02 frozen source manifest or policy mismatch")
    old_ids = {row["trial_id"] for row in source["target_trials"] + source["no_target_trials"]}
    old_seeds = {row["seed"] for row in source["target_trials"] + source["no_target_trials"]}
    if len(old_ids) != 160 or len(old_seeds) != 160:
        raise ValueError("P7-02 trial identity collision")
    rng = random.Random(SEED)
    noises = ["clean"] * 20 + ["moderate"] * 20
    rng.shuffle(noises)
    seeds = set(old_seeds)
    controls = []
    for index, noise in enumerate(noises, 1):
        seed = rng.randrange(2**32)
        while seed in seeds:
            seed = rng.randrange(2**32)
        seeds.add(seed)
        controls.append({
            "trial_id": f"p7-03-no-target-{index:03d}",
            "seed": seed,
            "target_present": False,
            "target_side": "none",
            "target_eccentricity": "none",
            "target_motion": "none",
            "visual_noise_level": noise,
        })
    if {row["trial_id"] for row in controls} & old_ids:
        raise ValueError("P7-03 trial ID reused")
    manifest = deepcopy(source)
    manifest["experiment_version"] = "p7-03-no-target-v1"
    manifest["no_target_trials"] = controls
    manifest["p7_03"] = {
        "task_id": "P7-03",
        "source_manifest_sha256": SOURCE_SHA256,
        "base_origin_main": BASE_COMMIT,
        "control_order_seed": SEED,
        "target_evidence_reused": {
            "summary_path": TARGET_SUMMARY_PATH,
            "summary_sha256": TARGET_SUMMARY_SHA256,
            "journal_path": TARGET_JOURNAL_PATH,
            "journal_sha256": TARGET_JOURNAL_SHA256,
            "valid_target_trials": 120,
            "correct_target_trials": 108,
        },
        "early_control_diagnostic_excluded": {
            "summary_sha256": EARLY_CONTROL_SUMMARY_SHA256,
            "journal_sha256": EARLY_CONTROL_JOURNAL_SHA256,
            "reuse_seed_or_trial_id": False,
        },
        "status": "preregistered_before_p7_03_final_control_run",
    }
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    if args.source.resolve() != SOURCE.resolve() or sha256_file(args.source) != SOURCE_SHA256:
        raise ValueError("source must be the exact committed P7-02 v4 manifest")
    source = json.loads(args.source.read_text(encoding="utf-8"))
    manifest = generate(source, source_sha256=sha256_file(args.source))
    args.output.write_text(json.dumps(manifest, sort_keys=True, indent=2,
                                      allow_nan=False) + "\n", encoding="utf-8")
    print(f"{args.output} sha256={sha256_file(args.output)}")


if __name__ == "__main__":
    main()
