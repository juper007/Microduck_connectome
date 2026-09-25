"""Preregister paired P7-04 clean/moderate target trials without tuning outcomes."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
from itertools import product
import json
from pathlib import Path
import random

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "config/steering_no_target_p7_03_v1.json"
HISTORICAL = ROOT / "config/steering_experiment_v4.json"
OUTPUT = ROOT / "config/steering_noise_p7_04_v1.json"
SOURCE_SHA256 = "fccc4a08656c8b3a81db6b7c8bd0a0b724abadc87c36163ca052ffc77d63c75b"
HISTORICAL_SHA256 = "f24170521f049cec6a65a88285925343316f84ce9bdaf59a1a668257db5460cd"
BASE_COMMIT = "fcc2a77dade05d21a603ee887c4f28ee22401e37"
SCENARIO_SHA256 = "089af4f05b5158579f7f335232793ffff5056fa3ea868d40cf0631fa0b33d804"
TRIAL_ORDER_SEED = 7040401
BOOTSTRAP_SEED = 7040402
BOOTSTRAP_REPLICATES = 10000
NOISE_SEMANTICS = {
    "clean": {"target_pixel_dropout": 0.0, "background_rgb_jitter": 0},
    "moderate": {"target_pixel_dropout": 0.2, "background_rgb_jitter": 20},
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate(source: dict, historical: dict, *, source_sha256: str,
             historical_sha256: str, scenario_sha256: str) -> dict:
    if (source_sha256 != SOURCE_SHA256 or historical_sha256 != HISTORICAL_SHA256
            or scenario_sha256 != SCENARIO_SHA256
            or source["schema_version"] != "steering-experiment-v4"
            or source["experiment_version"] != "p7-03-no-target-v1"
            or len(source["target_trials"]) != 120
            or len(source["no_target_trials"]) != 40
            or historical["experiment_version"] != "p7-steering-v4"
            or source["config_sha256"]["scenario"] != SCENARIO_SHA256
            or source["walking_policy"]["sha256"] !=
            "98c3ea73fa6bb196bcf16586cf38b9fffb782787447d638fa1c1028df9082c1a"):
        raise ValueError("frozen P7 source, scenario, or policy mismatch")
    scenario = json.loads((ROOT / "config/target_scenario_v1.json").read_text())
    if scenario["visual_noise"] != NOISE_SEMANTICS:
        raise ValueError("P7-01 visual noise semantics changed")
    prior = (source["target_trials"] + source["no_target_trials"]
             + historical["target_trials"] + historical["no_target_trials"])
    prior_seeds = {row["seed"] for row in prior}
    prior_ids = {row["trial_id"] for row in prior}
    if len(prior_seeds) != 200:
        raise ValueError("P7-02/P7-03 seed history is not independent")
    rng = random.Random(TRIAL_ORDER_SEED)
    cells = list(product(("left", "right"), ("near_center", "medium", "far"),
                         ("static", "slow_crossing")))
    plan = [(side, eccentricity, motion, repetition)
            for side, eccentricity, motion in cells for repetition in range(1, 6)]
    rng.shuffle(plan)
    trials = []
    pairs = []
    used_seeds = set(prior_seeds)
    for index, (side, eccentricity, motion, repetition) in enumerate(plan, 1):
        seed = rng.randrange(2**32)
        while seed in used_seeds:
            seed = rng.randrange(2**32)
        used_seeds.add(seed)
        pair_id = f"p7-04-pair-{index:03d}"
        order = ["clean", "moderate"]
        rng.shuffle(order)
        names = {}
        for noise in order:
            trial_id = f"p7-04-target-{index:03d}-{noise}"
            names[noise] = trial_id
            trials.append({
                "trial_id": trial_id, "seed": seed, "target_present": True,
                "target_side": side, "target_eccentricity": eccentricity,
                "target_motion": motion, "visual_noise_level": noise,
            })
        pairs.append({
            "pair_id": pair_id, "seed": seed, "target_side": side,
            "target_eccentricity": eccentricity, "target_motion": motion,
            "repetition": repetition, "condition_order": order,
            "clean_trial_id": names["clean"], "moderate_trial_id": names["moderate"],
        })
    if len(trials) != 120 or len(pairs) != 60 or len(used_seeds) != 260:
        raise RuntimeError("paired trial generation failed")
    if {row["trial_id"] for row in trials} & prior_ids:
        raise RuntimeError("P7-04 trial ID reused")
    manifest = deepcopy(source)
    manifest["experiment_version"] = "p7-04-noise-paired-v1"
    manifest["trial_order_randomization_seed"] = TRIAL_ORDER_SEED
    manifest["target_trials"] = trials
    manifest["p7_04"] = {
        "task_id": "P7-04",
        "base_origin_main": BASE_COMMIT,
        "source_p7_03_manifest_sha256": SOURCE_SHA256,
        "historical_p7_02_manifest_sha256": HISTORICAL_SHA256,
        "scenario_config_sha256": SCENARIO_SHA256,
        "noise_semantics": NOISE_SEMANTICS,
        "trial_order_seed": TRIAL_ORDER_SEED,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "bootstrap_replicates": BOOTSTRAP_REPLICATES,
        "pair_count": len(pairs),
        "target_trials_per_noise": 60,
        "pairs": pairs,
        "primary_analysis": (
            "moderate minus clean correct-direction indicator averaged over "
            "60 matched base-seed pairs; percentile 95% paired bootstrap CI"
        ),
        "secondary_analysis": (
            "Wilson 95% condition rates; paired discordance; response latency "
            "among responses; terminal absolute target-relative bearing error "
            "at trial timeout for every valid trial; first-response heading "
            "magnitude; class breakdown; safety and raw timing"
        ),
        "performance_threshold": None,
        "status": "preregistered_before_official_batch",
    }
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--historical", type=Path, default=HISTORICAL)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    if (args.source.resolve() != SOURCE.resolve()
            or args.historical.resolve() != HISTORICAL.resolve()
            or sha256_file(args.source) != SOURCE_SHA256
            or sha256_file(args.historical) != HISTORICAL_SHA256
            or sha256_file(ROOT / "config/target_scenario_v1.json") != SCENARIO_SHA256):
        raise ValueError("preregistration requires exact merged source and scenario bytes")
    source = json.loads(args.source.read_text(encoding="utf-8"))
    historical = json.loads(args.historical.read_text(encoding="utf-8"))
    manifest = generate(source, historical, source_sha256=SOURCE_SHA256,
                        historical_sha256=HISTORICAL_SHA256,
                        scenario_sha256=SCENARIO_SHA256)
    args.output.write_text(json.dumps(manifest, sort_keys=True, indent=2,
                                      allow_nan=False) + "\n", encoding="utf-8")
    print(f"{args.output} sha256={sha256_file(args.output)}")


if __name__ == "__main__":
    main()

