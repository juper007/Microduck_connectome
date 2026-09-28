"""Detached one-shot Thor launch and reconnect status for P8-03-R1.

Start once per immutable state root. A disconnect cannot launch a replacement.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from scripts.p8_03_r1_durability import atomic_json
from scripts.p8_02_r1_batch import fsync_directory, now


def proc_identity(pid: int) -> str | None:
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def start(state: Path, command: list[str]) -> dict:
    if state.exists():
        raise FileExistsError("one-shot supervisor state already exists")
    if os.name != "posix":
        raise RuntimeError("Thor POSIX host required")
    if (not command or not command[0].endswith("python3.12")
            or "--r1" not in command or "--output" not in command
            or "--reviewed-head" not in command):
        raise ValueError("start command must use pinned python3.12")
    state.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, P8_03_R1_LAUNCH_ROOT=str(state.resolve()))
    with (state / "supervisor.log").open("xb") as log:
        log.flush()
        os.fsync(log.fileno())
        child = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=subprocess.STDOUT,
                                 start_new_session=True, close_fds=True, env=env)
    identity = proc_identity(child.pid)
    record = {"schema_version": "p8-03-r1-launch-v1", "pid": child.pid,
              "proc_start_ticks": identity, "command": command,
              "source_head": command[command.index("--reviewed-head") + 1],
              "started_utc": now(), "started_monotonic_ns": time.monotonic_ns(),
              "state": "LAUNCHED"}
    atomic_json(state / "launch.json", record)
    fsync_directory(state)
    return record


def status(state: Path) -> dict:
    launch = json.loads((state / "launch.json").read_text())
    current_identity = proc_identity(launch["pid"])
    same_process = current_identity is not None and current_identity == launch["proc_start_ticks"]
    output = Path(launch["command"][launch["command"].index("--output") + 1])
    journal_path = output / "batch-journal.json"
    journal = json.loads(journal_path.read_text()) if journal_path.exists() else None
    exit_path = state / "exit-status.json"
    exit_status = json.loads(exit_path.read_text()) if exit_path.exists() else None
    result = {"schema_version": "p8-03-r1-status-v1", "pid": launch["pid"],
              "same_process_alive": same_process,
              "journal_result": journal.get("result") if journal else None,
              "exit_status": exit_status,
              "journal_path": str(journal_path), "log_path": str(state / "supervisor.log")}
    result["state"] = ("RUNNING" if same_process else
                       "COMPLETED" if exit_status is not None and journal and
                       journal.get("result") in ("PASS", "FAIL")
                       else "LOST_REQUIRES_RECOVERY")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "status", "interrupt"))
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.action == "start":
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        result = start(args.state, command)
    else:
        result = status(args.state)
        if args.action == "interrupt" and result["same_process_alive"]:
            os.kill(result["pid"], signal.SIGINT)
            result["interrupt_sent"] = True
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
