"""Read-only hash/index of retained Thor P8 fault-stop development attempts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact(path):
    return {
        "path": str(path), "bytes": path.stat().st_size,
        "record_count": (sum(1 for _ in path.open("rb")) if path.suffix == ".jsonl" else None),
        "sha256": sha(path),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roots", nargs="+", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    batches = []
    attempts = []
    for root in args.roots:
        batch_path = root / "batch-summary.json"
        batch = json.loads(batch_path.read_text())
        files = [artifact(batch_path)]
        observed = set()
        for row in batch["rows"]:
            fault = row["fault"]
            observed.add(fault)
            folder = root / f'trial-{row["index"] + 1:02d}-{fault}'
            if not row["started"]:
                attempts.append({"fault": fault, "status": "NOT_STARTED",
                                 "raw_root": str(root), "development_seed": row.get("development_seed")})
                continue
            summary_path = folder / "summary.json"
            summary = json.loads(summary_path.read_text()) if summary_path.is_file() else None
            trial_files = [artifact(path) for path in sorted(folder.iterdir()) if path.is_file()]
            for name, metadata in (summary or {}).get("artifacts", {}).items():
                actual = next((item for item in trial_files if item["path"] == metadata["path"]), None)
                if actual is None or any(actual[key] != metadata[key]
                                         for key in ("bytes", "record_count", "sha256")):
                    raise ValueError(f"artifact integrity mismatch: {folder}/{name}")
            if summary and row.get("summary_sha256") != sha(summary_path):
                raise ValueError(f"batch summary hash mismatch: {summary_path}")
            attempts.append({
                "fault": fault, "status": (summary or {}).get("result", row["result"]),
                "failure": (summary or {}).get("failure", row.get("failure")),
                "development_seed": row.get("development_seed"),
                "source_head": (summary or {}).get("source_head"),
                "first_stop_source": (summary or {}).get("first_stop_source"),
                "stop_ack_count": (summary or {}).get("stop_ack_count"),
                "stop_ack_gap_max_ms": (summary or {}).get("stop_ack_gap_max_ms"),
                "injection_to_first_stop_ack_ms": (summary or {}).get("injection_to_first_stop_ack_ms"),
                "fault_to_first_stop_ack_ms": (summary or {}).get("fault_to_first_stop_ack_ms"),
                "first_stop_ack_to_pose_stop_ms": (summary or {}).get("first_stop_ack_to_pose_stop_ms"),
                "scheduler_exceptions": (summary or {}).get("scheduler_exceptions"),
                "safety_limit_violations": (summary or {}).get("safety_limit_violations"),
                "raw_root": str(folder), "files": trial_files,
            })
        # The first version predated explicit unstarted rows.  Preserve that
        # immutable batch and reconstruct the omitted planned case here.
        for fault in batch["planned_faults"]:
            if fault not in observed:
                attempts.append({"fault": fault, "status": "NOT_STARTED",
                                 "raw_root": str(root),
                                 "reason": "batch stopped after prior retained failure"})
        batches.append({"raw_root": str(root), "source_head": batch["source_head"],
                        "result": batch["result"], "files": files})
    index = {"schema_version": "p8-v2-fault-stop-development-index-v1",
             "evidence_role": "development_only_not_final_p8_04",
             "batches": batches, "attempts": attempts}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(index, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"index": str(args.output), "sha256": sha(args.output),
                      "batches": len(batches), "attempts": len(attempts)}))


if __name__ == "__main__":
    main()
