"""Verify the immutable P8-02-R1 release extraction without changing its files."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_stage(root: Path, prefix: str, count: int, first_seed: int) -> dict:
    manifest = read(root / "raw-manifest.json")
    journal = read(root / "batch-journal.json")
    score = read(root / "score.json")
    expected = {f"{prefix}{i:02d}" for i in range(count)}
    present = {p.name for p in root.iterdir() if p.is_dir()}
    checks = {"hash": 0, "bytes": 0, "records": 0}
    problems: list[str] = []
    listed: set[str] = set()
    for entry in manifest["files"]:
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts or relative.as_posix() in listed:
            problems.append(f"invalid/duplicate manifest path: {relative}")
            continue
        listed.add(relative.as_posix())
        path = root / relative
        if not path.is_file():
            problems.append(f"missing: {relative}")
            continue
        data = path.read_bytes()
        for key, actual in (("hash", digest(data)), ("bytes", len(data)),
                            ("records", len(data.splitlines()))):
            named = {"hash": "sha256", "bytes": "bytes", "records": "record_count"}[key]
            if entry.get(named) == actual:
                checks[key] += 1
            else:
                problems.append(f"{key} mismatch: {relative}")
    actual_files = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    extra = actual_files - listed - {"raw-manifest.json"}
    if extra:
        problems.extend(f"unlisted: {name}" for name in sorted(extra))
    if expected != present:
        problems.append(f"ID directories missing={sorted(expected-present)} extra={sorted(present-expected)}")
    ids = journal.get("ids", [])
    if len(ids) != count:
        problems.append(f"journal IDs: {len(ids)}")
    attempt_count = 0
    for i, row in enumerate(ids):
        trial = f"{prefix}{i:02d}"
        seed = first_seed + i
        if (row.get("trial_id"), row.get("seed")) != (trial, seed):
            problems.append(f"journal ID/seed: {trial}")
        attempts = row.get("attempts", [])
        attempt_count += len(attempts)
        if len(attempts) != 1 or row.get("status") != "ARMED_COMPLETE":
            problems.append(f"attempt count/status: {trial}")
            continue
        attempt = attempts[0]
        states = [event.get("state") for event in attempt.get("progress", [])]
        needed = ("MOTION_CONFIRMED", "NEURAL_OBSERVATION_ARMED", "ROBOT_STOP_SENT",
                  "ROBOT_STOP_ACK", "MOTION_STOPPED", "COMPLETE")
        ordered = all(state in states for state in needed) and [states.index(state) for state in needed] == sorted(states.index(state) for state in needed)
        step_names = {step.get("name") for step in attempt.get("steps", [])}
        if (attempt.get("name") != "attempt-01" or attempt.get("armed") is not True
                or attempt.get("status") != "TRIAL_EXITED" or attempt.get("trial_exit") != 0
                or not ordered
                or not {"down", "up", "policy_load", "policy_readback"} <= step_names):
            problems.append(f"attempt state: {trial}")
        folder = root / trial / "attempt-01"
        if not folder.is_dir() or any(p.name != "attempt-01" for p in (root / trial).iterdir() if p.is_dir()):
            problems.append(f"attempt directory: {trial}")
            continue
        summary = read(folder / "summary.json")
        if (summary.get("trial_id"), summary.get("seed"), summary.get("validity_class")) != (
                f"p8-02-r1-{trial}", seed, "ARMED"):
            problems.append(f"summary identity: {trial}")
        if digest((folder / "summary.json").read_bytes()) != attempt.get("summary_sha256"):
            problems.append(f"journal summary hash: {trial}")
    if journal.get("result") != "PASS" or score.get("planned") != count:
        problems.append("journal or historical score status")
    return {"expected_ids": count, "present_ids": len(expected & present),
            "manifest_entries": len(manifest["files"]), "hash_match": checks["hash"],
            "byte_match": checks["bytes"], "record_match": checks["records"],
            "attempts": attempt_count, "missing": len(expected - present),
            "extra": len(extra) + len(present - expected), "mismatches": problems,
            "journal_result": journal.get("result"), "historical_score": score.get("result"),
            "source_head": journal.get("source_head"),
            "protocol_sha256": journal.get("protocol_sha256"),
            "preflight_hashes": journal.get("preflight_hashes"),
            "preflight_commits": journal.get("preflight_commits")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive_root", type=Path)
    args = parser.parse_args()
    root = args.archive_root
    result = {
        "D": verify_stage(root / "p8-02-r1-development-v1", "D", 3, 886020),
        "B": verify_stage(root / "p8-02-r1-approach-v1", "B", 20, 880020),
    }
    gate_root = root / "p8-02-r1-no-seed-gate-v1"
    gate = read(gate_root / "gate.json")
    gate_problems = []
    expected_cases = {"wrong_operator_path", "wrong_audit_path", "sigint_checkpoint",
                      "sigkill_audit_only"}
    testcase_terms = {"wrong_operator_path": "wrong_operator_path_aborts",
                      "wrong_audit_path": "wrong_audit_inside_output_aborts_zero_ids",
                      "sigint_checkpoint": "sigint_checkpoints_stop_then_down",
                      "sigkill_audit_only": "recovery_never_modify_raw"}
    for case in gate.get("cases", []):
        path = gate_root / case["log"]
        if (not path.is_file() or digest(path.read_bytes()) != case.get("log_sha256")
                or path.stat().st_size != case.get("log_bytes")
                or case.get("exit") != 0 or case.get("result") != "PASS"
                or testcase_terms.get(case.get("name"), "__unknown__")
                not in case.get("testcase", "")):
            gate_problems.append(case.get("name"))
    result["no_seed"] = {"result": gate.get("result"), "cases": len(gate.get("cases", [])),
                         "missing": sorted(expected_cases - {c.get("name") for c in gate.get("cases", [])}),
                         "problems": gate_problems}
    for key, stage in (("D", "development"), ("B", "approach")):
        probe = read(root / f"p8-02-r1-{stage}-v1" / "final-state-probe.json")
        result[key]["final_probe"] = probe
    print(json.dumps(result, indent=2, sort_keys=True))
    if (any(result[key]["mismatches"] for key in ("D", "B"))
            or gate_problems or result["no_seed"]["missing"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
