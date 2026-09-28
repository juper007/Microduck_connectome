"""Independently reconstruct the pooled P8-03 decision from both raw roots."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.p8_03_score import manifest_check, score_batch, wilson_95
from scripts.p8_03_r1_durability import load_protocol


def finalize(static_root: Path, receding_root: Path, master: dict) -> dict:
    stage = {}
    for letter, root in (("S", static_root), ("R", receding_root)):
        score = score_batch(root, master, letter)
        manifest = manifest_check(root)
        journal = json.loads((root / "batch-journal.json").read_text(encoding="utf-8"))
        score["manifest"] = manifest
        score["journal_result"] = journal.get("result")
        score["source_head"] = journal.get("source_head")
        score["final_sim_down"] = journal.get("final_sim_down")
        stage[letter] = score
    false_count = stage["S"]["false_neural_stops"] + stage["R"]["false_neural_stops"]
    same_head = bool(stage["S"]["source_head"] and
                     stage["S"]["source_head"] == stage["R"]["source_head"])
    good = (same_head and false_count <= 2 and
            all(stage[k]["result"] == "PASS" and
                stage[k]["journal_result"] == "PASS" and
                stage[k]["manifest"]["result"] == "PASS" and
                stage[k]["final_sim_down"].get("state_probe_result") == "PASS"
                for k in ("S", "R")))
    return {"schema_version": "p8-03-final-score-v1",
            "result": "PASS" if good else "FAIL", "source_head": stage["S"]["source_head"]
            if same_head else None, "planned": 40, "false_neural_stops": false_count,
            "false_positive_rate": false_count / 40,
            "wilson_95": wilson_95(false_count, 40), "stages": stage}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--static-root", type=Path, required=True)
    ap.add_argument("--receding-root", type=Path, required=True)
    ap.add_argument("--master", type=Path, default=Path("config/p8_v2_final_protocol_v1.json"))
    ap.add_argument("--r1-root", type=Path,
                    help="R1 source root; binds the original master and frozen R1 matrix hashes")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    master = (load_protocol(args.r1_root)[0] if args.r1_root else
              json.loads(args.master.read_text(encoding="utf-8")))
    result = finalize(args.static_root, args.receding_root, master)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": result["result"], "false_neural_stops": result["false_neural_stops"]}))
    if result["result"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
