"""P8-03-R1 crash-durable arm identity and evidence reconciliation.

Only the trial child may create an arm marker. The supervisor may inventory
partial artifacts after a crash, but may never create or remove an arm marker.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import uuid

from scripts.p8_02_r1_batch import fsync_directory, inventory, now


def load_protocol(root: Path) -> tuple[dict, dict, dict]:
    """Use the original scientific protocol with only R1 trial identity replaced."""
    master_path = root / "config/p8_v2_final_protocol_v1.json"
    r1_path = root / "config/p8_03_r1_protocol_v1.json"
    master_bytes = master_path.read_bytes()
    r1_bytes = r1_path.read_bytes()
    protocol = json.loads(r1_bytes)
    # Windows Git checkouts may expand LF to CRLF; the frozen identity is the
    # committed blob, which Thor checks byte-for-byte before execution.
    normalized_master = master_bytes.replace(b"\r\n", b"\n")
    if hashlib.sha256(normalized_master).hexdigest() != protocol["master_sha256"]:
        raise RuntimeError("normative P8-V2 master bytes changed")
    master = json.loads(master_bytes)
    for stage, key in (("S", "P8-03-static"), ("R", "P8-03-receding")):
        original = master["batches"][key]["runs"]
        frozen = protocol["final_matrix"][stage]
        if len(frozen) != 20 or len(original) != 20:
            raise RuntimeError("R1 matrix length mismatch")
        for old, new in zip(original, frozen):
            if set(new) != {"trial_id", "seed"}:
                raise RuntimeError("R1 identity schema mismatch")
            old["trial_id"], old["seed"] = new["trial_id"], new["seed"]
    master["p8_03_r1_matrix"] = protocol["final_matrix"]
    return master, protocol, {"master": hashlib.sha256(normalized_master).hexdigest(),
                              "r1": hashlib.sha256(r1_bytes).hexdigest()}


def atomic_json(path: Path, data: dict) -> None:
    """Write, fsync, rename and fsync parent; unique tmp survives crash safely."""
    payload = (json.dumps(data, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with tmp.open("xb") as out:
        out.write(payload)
        out.flush()
        os.fsync(out.fileno())
    os.replace(tmp, path)
    fsync_directory(path.parent)


def create_arm_marker(path: Path, *, task: str, trial_id: str, seed: int,
                      attempt: int, source_head: str, config_hash: str,
                      arm_ns: int) -> dict:
    if path.exists():
        raise FileExistsError(path)
    marker = {"schema_version": "p8-03-r1-arm-v1", "task": task,
              "trial_id": trial_id, "seed": seed, "attempt": attempt,
              "source_head": source_head, "config_sha256": config_hash,
              "armed_at_utc": now(), "armed_at_monotonic_ns": arm_ns,
              "state": "ARMED"}
    atomic_json(path, marker)
    return marker


def classify_attempt(folder: Path, attempt: dict, identity: dict,
                     *, child_alive: bool = False) -> str:
    """Conservative recovery; journal false never overrides a durable marker."""
    marker_path = folder / "armed.json"
    if child_alive:
        return "ACTIVE"
    if marker_path.exists():
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return "UNKNOWN_ARM"
        if any(marker.get(key) != value for key, value in identity.items()):
            return "UNKNOWN_ARM"
        if marker.get("schema_version") != "p8-03-r1-arm-v1" or marker.get("state") != "ARMED":
            return "UNKNOWN_ARM"
        if attempt.get("armed") is False and attempt.get("status") not in (
                "ACQUIRING", "TRIAL_CHILD_STARTED"):
            return "UNKNOWN_ARM"
        return "COMPLETED" if attempt.get("status") == "TRIAL_EXITED" and (
            folder / "summary.json").is_file() else "ARMED"
    if attempt.get("armed") is True or attempt.get("status") in (
            "NEURAL_OBSERVATION_ARMED", "TRIAL_EXITED", "ARMED_COMPLETE"):
        return "UNKNOWN_ARM"
    # R1 child source guarantees the marker is durable before any scored arm.
    # Missing marker is PRE_ARM only if no raw arm event or completion exists.
    try:
        events = (folder / "events.jsonl").read_text(encoding="utf-8") if (
            folder / "events.jsonl").exists() else ""
        progress = (folder / "progress.jsonl").read_text(encoding="utf-8") if (
            folder / "progress.jsonl").exists() else ""
    except OSError:
        return "UNKNOWN_ARM"
    if '"kind":"arm"' in events or '"kind": "arm"' in events or "NEURAL_OBSERVATION_ARMED" in progress:
        return "UNKNOWN_ARM"
    return "PRE_ARM"


def checkpoint(root: Path, journal: dict, *, artifact_state: str) -> None:
    journal["checkpoint_utc"] = now()
    journal["checkpoint_monotonic_ns"] = time.monotonic_ns()
    atomic_json(root / "batch-journal.json", journal)
    files = inventory(root)
    for row in files:
        rel = row["path"]
        parts = Path(rel).parts
        row["artifact_class"] = ("journal" if rel == "batch-journal.json" else
                                 "arm_marker" if rel.endswith("/armed.json") else
                                 "recovery" if rel.startswith("recovery-") else
                                 "trial" if len(parts) >= 3 else "batch")
        row["attempt"] = parts[1] if len(parts) >= 3 and parts[1].startswith("attempt-") else None
        row["state"] = artifact_state
    atomic_json(root / "raw-manifest.json", {
        "schema_version": "p8-03-r1-raw-manifest-v1",
        "task": "P8-03-R1", "stage": journal["stage"],
        "source_head": journal["source_head"], "files": files})


def run_child(command: list[str], log: Path, env: dict, *, progress=None,
              created=None) -> tuple[int, bool]:
    """Keep a durable log and stop the entire child process group on interruption."""
    with log.open("xb") as out:
        out.flush()
        os.fsync(out.fileno())
        fsync_directory(log.parent)
        if created is not None:
            created()
        child = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                 stdout=out, stderr=subprocess.STDOUT,
                                 env=env, start_new_session=True)
        try:
            while True:
                try:
                    code = child.wait(timeout=.05)
                    if progress is not None:
                        progress()
                    out.flush()
                    os.fsync(out.fileno())
                    if created is not None:
                        created()
                    return code, False
                except subprocess.TimeoutExpired:
                    if progress is not None:
                        progress()
        except BaseException:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGINT)
                try:
                    child.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGTERM)
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait()
            out.flush()
            os.fsync(out.fileno())
            if created is not None:
                created()
            raise


def reconcile(root: Path, journal: dict, *, child_alive: bool = False) -> dict:
    states = {}
    for item in journal["ids"]:
        for attempt in item["attempts"]:
            folder = root / item["trial_id"] / attempt["name"]
            identity = {"task": "P8-03-R1", "trial_id": item["trial_id"],
                        "seed": item["seed"], "attempt": int(attempt["name"].split("-")[-1]),
                        "source_head": journal["source_head"],
                        "config_sha256": journal["config_sha256"]}
            states[f"{item['trial_id']}/{attempt['name']}"] = classify_attempt(
                folder, attempt, identity, child_alive=child_alive)
    return {"schema_version": "p8-03-r1-recovery-v1",
            "source_journal_sha256": hashlib.sha256(
                (root / "batch-journal.json").read_bytes()).hexdigest(),
            "states": states,
            "retry_prohibited": [key for key, state in states.items()
                                 if state in ("ARMED", "COMPLETED", "UNKNOWN_ARM", "ACTIVE")],
            "result": "FAIL" if any(state in ("ARMED", "UNKNOWN_ARM", "ACTIVE")
                                    for state in states.values()) else "AUDIT_ONLY"}
