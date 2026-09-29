"""Verify and package three prospective P8-03 causal qualification probes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tarfile


LABELS = ("CPDEV-002", "CPDEV-003", "CPDEV-004")
REVIEWED_HEAD = "7d89438731e5eb2c81e2163e33babbe69e1f7a08"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package(root: Path, output: Path) -> dict:
    root = root.resolve()
    if output.exists():
        raise FileExistsError(output)
    manifest = {
        "schema_version": "p8-03-causal-qualification-evidence-r1",
        "reviewed_probe_head": REVIEWED_HEAD,
        "historical_cpdev001_result": "IMMUTABLE_FAIL",
        "labels": [],
    }
    for label in LABELS:
        directory = root / label
        summary = json.loads((directory / "summary.json").read_text())
        if (summary["label"] != label or summary["result"] != "PASS" or
                summary["connectome_sha"] != REVIEWED_HEAD or
                summary["duration_start"] != "FIRST_CAUSAL_TICK" or
                summary["causal_window_duration_s"] < 1.5 or
                summary["physical_displacement_m"] < .01 or
                summary["deadman_count_in_window"] != 0 or
                summary["fault_count_in_window"] != 0 or
                summary["tick_gap_count"] != 0 or
                not summary["final_prearm_eligibility"] or
                summary["final_down_exit"] != 0 or
                not summary["final_socket_absent"] or
                not summary["final_port_free"]):
            raise ValueError(f"{label}: summary gate failed")
        rows = [json.loads(line) for line in
                (directory / "diagnostic.jsonl").read_text().splitlines()]
        states = [row["state"] for row in rows if row.get("kind") == "robot.state"]
        requests = [row for row in rows if row.get("kind") == "robot.move.request"]
        acks = [row for row in rows if row.get("kind") == "robot.move.ack"]
        if (len(requests) != 91 or len(acks) != 91 or
                any(b["control_tick_sequence"] != a["control_tick_sequence"] + 1
                    for a, b in zip(states, states[1:])) or
                any(row.get("kind") == "diagnostic.failure" for row in rows)):
            raise ValueError(f"{label}: raw ledger discontinuity")
        first = next(s for s in states
                     if s["control_tick_sequence"] == summary["first_causal_tick"])
        qualifying = next(s for s in states
                          if s["control_tick_sequence"] == summary["first_qualifying_tick"])
        if (first["consumed_move_generation"] != summary["first_consumed_generation"] or
                qualifying["consumed_move_generation"] !=
                summary["first_qualifying_generation"] or
                first["move"]["applied"][0] >= .04 or
                qualifying["move"]["applied"][0] < .04 or
                qualifying["policy"] != "walk"):
            raise ValueError(f"{label}: raw first-tick identity mismatch")
        files = sorted(p for p in directory.iterdir() if p.is_file())
        manifest["labels"].append({
            "label": label,
            "result": "PASS",
            "first_causal_tick": summary["first_causal_tick"],
            "first_qualifying_tick": summary["first_qualifying_tick"],
            "ramp_duration_ms": summary["ramp_duration_ms"],
            "causal_duration_s": summary["causal_window_duration_s"],
            "qualifying_duration_s": summary["qualifying_window_duration_s"],
            "postqualification_displacement_m": summary["physical_displacement_m"],
            "state_count": len(states),
            "request_count": len(requests),
            "ack_count": len(acks),
            "files": [{"path": p.name, "bytes": p.stat().st_size,
                       "sha256": digest(p)} for p in files],
        })
    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        raise FileExistsError(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    with tarfile.open(output, "w:gz") as archive:
        archive.add(manifest_path, arcname="manifest.json")
        for label in LABELS:
            archive.add(root / label, arcname=label)
    return {"archive": str(output), "sha256": digest(output),
            "manifest_sha256": digest(manifest_path), "labels": manifest["labels"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(package(args.root, args.output), indent=2))


if __name__ == "__main__":
    main()
