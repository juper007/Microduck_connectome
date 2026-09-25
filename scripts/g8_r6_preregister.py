"""Build the prospective graph-v2 steering protocol from frozen P7 rules.

The P7 trial matrix supplies geometry/condition strata only. New seeds are
generated before any G8-R6 final outcome is observed.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import random


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "config/steering_experiment_v4.json"
DEST = ROOT / "config/g8_r6_steering_v1.json"
GRAPH = "c4160c42941163079b6b569d117bf67afcf8b45eaa128c444f7c96c2567593cc"


def generate() -> dict:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    protocol = copy.deepcopy(source)
    protocol.update(
        schema_version="g8-r6-steering-v1",
        experiment_version="g8-r6-graph-v2-steering-v1",
        scope="prospective graph-v2 official Thor steering recertification; graph-v1 G7 is historical",
        graph_key=GRAPH,
        graph_sha256=GRAPH,
        min_valid_target_trials=100,
        base_origin_main="9b9a147ac143db50d21ee04b361b9fb852402122",
        trial_order_randomization_seed=80601,
        seed_generation="Python random.Random(80601); unique 32-bit seeds assigned in listed trial order",
        source_matrix_sha256=hashlib.sha256(
            SOURCE.read_bytes().replace(b"\r\n", b"\n")
        ).hexdigest(),
        source_matrix_role="condition strata only; no G7 outcomes reused",
        final_result_policy="freeze this committed protocol and source before first final trial; retain all started failures and do not replace seeds",
    )
    rng = random.Random(80601)
    seeds = set()
    for label, key in (("target", "target_trials"), ("no-target", "no_target_trials")):
        for index, spec in enumerate(protocol[key], 1):
            spec["trial_id"] = f"g8-r6-{label}-{index:03d}"
            while True:
                seed = rng.randrange(2**32)
                if seed not in seeds:
                    break
            seeds.add(seed)
            spec["seed"] = seed
    return protocol


if __name__ == "__main__":
    DEST.write_text(json.dumps(generate(), sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(DEST)
