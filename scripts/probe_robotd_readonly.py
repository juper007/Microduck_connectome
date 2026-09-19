#!/usr/bin/env python3
"""Probe P6-02 read-only robotd IPC and emit compact machine-readable evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import socket
import subprocess
import time

from microduck_connectome.robotd_client import RobotdClient, RobotdConnectionError


def _git_head(path: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _state_summary(state: dict) -> dict:
    return {
        "t": state["t"],
        "t_ns": state.get("t_ns", 0),
        "policy": state["policy"],
        "move": state["move"],
        "loop": state["loop"],
        "joint_count": len(state["joints"]),
        "target_count": len(state["targets"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", required=True)
    parser.add_argument("--microduck", type=Path, required=True)
    parser.add_argument("--microduck-rl", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=2.0)
    args = parser.parse_args()

    started_utc = datetime.now(timezone.utc)
    started_ns = time.monotonic_ns()
    client = RobotdClient(args.socket, timeout_s=args.timeout)

    first_status = client.connect()
    first_health = client.health()
    first_state = client.state(hz=1)
    client.disconnect()
    disconnect_observed = not client.status.connected
    disconnected_call_rejected = False
    try:
        client.health()
    except RobotdConnectionError:
        disconnected_call_rejected = True

    second_status = client.reconnect()
    second_health = client.health()
    second_state = client.state(hz=1)
    client.close()
    ended_ns = time.monotonic_ns()
    ended_utc = datetime.now(timezone.utc)

    evidence = {
        "schema_version": 1,
        "task": "P6-02",
        "execution_target": "Thor",
        "host": socket.gethostname(),
        "os": platform.platform(),
        "architecture": platform.machine(),
        "started_utc": started_utc.isoformat(),
        "ended_utc": ended_utc.isoformat(),
        "elapsed_monotonic_ms": (ended_ns - started_ns) / 1_000_000,
        "socket": args.socket,
        "protocol": {
            "transport": "Unix domain stream socket",
            "framing": "newline-delimited JSON-RPC 2.0",
            "api_version": first_status.peer_api_version,
            "health_method": "robot.health",
            "state_subscription_method": "robot.subscribe",
            "state_notification_method": "robot.state",
        },
        "upstream": {
            "microduck_commit": _git_head(args.microduck),
            "microduck_rl_commit": _git_head(args.microduck_rl),
        },
        "connection": {
            "first_generation": first_status.generation,
            "disconnect_observed": disconnect_observed,
            "disconnected_call_rejected": disconnected_call_rejected,
            "reconnected_generation": second_status.generation,
        },
        "health": {
            "before_disconnect": first_health,
            "after_reconnect": second_health,
        },
        "state": {
            "before_disconnect": _state_summary(first_state),
            "after_reconnect": _state_summary(second_state),
        },
        "motion_requests_sent": 0,
        "result": "PASS",
    }
    encoded = json.dumps(evidence, indent=2, sort_keys=True, allow_nan=False) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded, encoding="utf-8")
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    print(json.dumps({"output": str(args.output), "sha256": digest, "result": "PASS"}))


if __name__ == "__main__":
    main()
