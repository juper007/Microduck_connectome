"""Acquire a valid official simulator pose before, never during, a P7 trial."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_loaded_walk_policy(readback: dict, expected_path: Path,
                                expected_sha256: str) -> dict:
    policies = readback["policies"]
    if policies["enabled"] is not True or policies["mode"] != "walk":
        raise ValueError("policy system is disabled or not in walk mode")
    slots = [item for item in policies["slots"] if item["slot"] == "walk"]
    if len(slots) != 1:
        raise ValueError("walk policy slot missing or duplicated")
    slot = slots[0]
    if slot["error"] is not None or slot["overridden"] is not True:
        raise ValueError("walk policy load failed or fell back")
    # The official loader may report a resolved release path rather than the
    # submitted source path. Verify the bytes of the path robotd actually uses.
    observed = Path(slot["path"]).resolve(strict=True)
    if not Path(slot["path"]).is_absolute() or slot["origin"] != "local":
        raise ValueError("walk policy is not an absolute local override")
    if sha256_file(expected_path.resolve(strict=True)) != expected_sha256:
        raise ValueError("submitted walk policy file hash mismatch")
    digest = sha256_file(observed)
    if digest != expected_sha256:
        raise ValueError("loaded walk policy file hash mismatch")
    return {"loaded_walk_path": str(observed), "loaded_walk_sha256": digest,
            "policy_mode": policies.get("mode")}


def run_logged(command: list[str], path: Path, *, env: dict,
               cwd: Path | None = None) -> int:
    result = subprocess.run(command, cwd=cwd, env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    path.write_text(result.stdout, encoding="utf-8")
    return result.returncode


def acquire(*, root: Path, experiment_path: Path, experiment: dict,
            trial_dir: Path, sim_script: Path, body_port: int,
            env: dict) -> dict:
    policy = experiment["walking_policy"]
    policy_path = Path(policy["artifact_path"])
    if not policy_path.is_absolute() or sha256_file(policy_path) != policy["sha256"]:
        raise ValueError("preregistered walking policy artifact mismatch")
    rule = experiment["validity"]
    attempts = []
    accepted = False
    for index in range(1, rule["pretrial_pose_acquisition_max_attempts"] + 1):
        folder = trial_dir / f"pretrial-{index:02d}"
        folder.mkdir()
        row = {"attempt": index}
        for name, command in (
            ("down", [str(sim_script), "down"]),
            ("up", [str(sim_script), "up"]),
            ("policy_load", [str(sim_script), "ctl", "policy", "load", "walk",
                             str(policy_path)]),
            ("policy_list", [str(sim_script), "ctl", "policy", "list", "--json"]),
        ):
            log = folder / f"{name}.log"
            row[f"{name}_exit"] = run_logged(command, log, env=env)
            row[f"{name}_log_sha256"] = sha256_file(log)
            if row[f"{name}_exit"] != 0:
                row["rejection"] = f"official_{name}_failed"
                break
            if name == "policy_list":
                try:
                    readback = json.loads(log.read_text(encoding="utf-8"))
                    row.update(validate_loaded_walk_policy(
                        readback, policy_path, policy["sha256"]))
                except (ValueError, KeyError, TypeError, OSError) as error:
                    row["rejection"] = f"policy_readback_mismatch: {error}"
                    break
        if "rejection" not in row:
            time.sleep(rule["pretrial_policy_settle_s"])
            pose_path = folder / "pose.json"
            pose_log = folder / "pose.log"
            row["pose_exit"] = run_logged([
                sys.executable, str(root / "scripts/p7_pose_check.py"),
                "--body-port", str(body_port), "--experiment", str(experiment_path),
                "--output", str(pose_path),
            ], pose_log, env=env, cwd=root)
            row["pose_log_sha256"] = sha256_file(pose_log)
            if pose_path.exists():
                row["pose_sha256"] = sha256_file(pose_path)
                row["pose"] = json.loads(pose_path.read_text(encoding="utf-8"))
            if row["pose_exit"] == 0 and row.get("pose", {}).get("accepted") is True:
                accepted = True
            else:
                row["rejection"] = "pose_outside_frozen_tolerance_or_unavailable"
        attempts.append(row)
        if accepted:
            break
    result = {"schema_version": "p7-pretrial-acquisition-v1",
              "accepted": accepted, "attempts": attempts,
              "attempts_used": len(attempts),
              "max_attempts": rule["pretrial_pose_acquisition_max_attempts"],
              "policy_sha256": policy["sha256"]}
    path = trial_dir / "pretrial-acquisition.json"
    path.write_text(json.dumps(result, sort_keys=True, indent=2,
                               allow_nan=False) + "\n", encoding="utf-8")
    return result
