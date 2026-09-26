"""Run the prospective P8-02 R1 operator/interrupt demonstrations without seeds."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import time

from scripts.p8_02_r1_batch import atomic_json, fsync_directory


CASES = {
    "wrong_operator_path": "test_wrong_operator_path_aborts_before_output_or_ids_and_audits",
    "wrong_audit_path": "test_correct_source_wrong_audit_inside_output_aborts_zero_ids",
    "sigint_checkpoint": "test_sigint_checkpoints_stop_then_down_and_probe_without_next_id",
    "sigkill_audit_only": "test_checkpoint_manifest_and_recovery_never_modify_raw",
}


def committed_bytes(root: Path, relative: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), "show", f"HEAD:{relative}"])


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(root: Path, reviewed_head: str) -> dict:
    root = root.resolve(strict=True)
    if (not socket.gethostname().startswith("jetsonthor")
            or platform.python_version_tuple()[:2] != ("3", "12")):
        raise RuntimeError("R1 no-seed gate requires Thor Python 3.12")
    if subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"],
                               text=True).strip() != reviewed_head:
        raise RuntimeError("R1 no-seed gate source differs from reviewed head")
    if subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"],
                               text=True).strip():
        raise RuntimeError("R1 no-seed gate requires clean source")
    protocol = json.loads((root / "config/p8_02_r1_protocol_v1.json").read_text())
    official = protocol["official_execution"]
    if (protocol.get("schema_version") != "p8-02-r1-remediation-protocol-v1"
            or root != Path(official["source_path"]).resolve()
            or (root / "scripts/p8_02_r1_no_seed_gate.py").resolve() != Path(__file__).resolve()):
        raise RuntimeError("R1 no-seed gate protocol/source path mismatch")
    gate_dir = Path(official["preflight_audit_log_path"]).parent / "p8-02-r1-no-seed-gate-v1"
    if gate_dir.exists():
        raise RuntimeError("R1 no-seed gate output exists; never overwrite demonstration evidence")
    gate_dir.mkdir(parents=True)
    fsync_directory(gate_dir.parent)
    cases = []
    for name, method in CASES.items():
        testcase = f"tests.test_p8_02_r1_harness.R1HarnessTests.{method}"
        command = [sys.executable, "-m", "unittest", testcase, "-v"]
        result = subprocess.run(command, cwd=root, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, check=False)
        log = gate_dir / f"{name}.log"
        with log.open("xb") as out:
            out.write(result.stdout)
            out.flush()
            os.fsync(out.fileno())
        fsync_directory(gate_dir)
        cases.append({"name": name, "testcase": testcase, "command": command,
                      "exit": result.returncode, "log": log.name,
                      "log_sha256": digest(result.stdout), "log_bytes": len(result.stdout),
                      "at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      "result": "PASS" if result.returncode == 0 else "FAIL"})
    source_hashes = {relative: digest(committed_bytes(root, relative)) for relative in (
        "config/p8_02_r1_protocol_v1.json", "scripts/p8_02_r1_batch.py",
        "scripts/p8_02_r1_trial.py", "scripts/p8_02_r1_score.py",
        "scripts/p8_02_r1_no_seed_gate.py", "tests/test_p8_02_r1_harness.py")}
    report = {"schema_version": "p8-02-r1-no-seed-gate-v1",
              "result": "PASS" if all(case["result"] == "PASS" for case in cases) else "FAIL",
              "source_head": reviewed_head, "source_path": str(root),
              "host": socket.gethostname(), "python": platform.python_version(),
              "python_executable": sys.executable, "committed_sha256": source_hashes,
              "cases": cases, "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "scope": "synthetic no-seed operator, SIGINT, and SIGKILL recovery demonstrations"}
    atomic_json(gate_dir / "gate.json", report)
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--reviewed-head", required=True)
    args = ap.parse_args()
    report = run(args.root, args.reviewed_head)
    print(json.dumps({"result": report["result"], "cases": len(report["cases"])}, sort_keys=True))
    if report["result"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
