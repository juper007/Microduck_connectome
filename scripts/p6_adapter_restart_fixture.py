"""Exercise the P6-03 adapter across controller and actual robotd restarts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from microduck_connectome.control_contracts import make_behavior_intent
from microduck_connectome.motion_adapter import MotionAdapterError, RobotMotionAdapter
from microduck_connectome.robotd_client import RobotdClient, RobotdConnectionError
from microduck_connectome.watchdog import ControllerWatchdog


def output(watchdog_config, timestamp, sequence, *, stop=False, vx=0.0, vyaw=0.0):
    watchdog = ControllerWatchdog(watchdog_config)
    if stop:
        return watchdog.tick(now_ns=timestamp, output_sequence=sequence)
    neural = {
        "timestamp_ns": timestamp,
        "sequence": sequence,
        "steering_left": 0.0,
        "steering_right": 0.0,
        "escape": 0.0,
        "runtime_healthy": True,
    }
    behavior = make_behavior_intent(
        timestamp_ns=timestamp, sequence=sequence, vx=vx, vyaw=vyaw
    )
    assert watchdog.observe_neural(neural)
    assert watchdog.observe_behavior(behavior)
    return watchdog.tick(now_ns=timestamp + 1, output_sequence=sequence + 1)


def wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise RuntimeError("timed out waiting for restart condition")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--body-port", type=int, required=True)
    parser.add_argument("--params", type=Path, required=True)
    parser.add_argument("--pid-file", type=Path, required=True)
    parser.add_argument("--robotd", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--ort-dylib", type=Path, required=True)
    parser.add_argument("--adapter-config", type=Path, required=True)
    parser.add_argument("--watchdog-config", type=Path, required=True)
    parser.add_argument("--restart-log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    events = []
    client = RobotdClient(str(args.socket), timeout_s=1.0)
    first = client.connect()
    adapter = RobotMotionAdapter(client, args.adapter_config)

    events.append({"event": "initial_connect", "generation": first.generation})
    events.append({"event": "initial_move", "result": adapter.send(output(
        args.watchdog_config, 10, 10, vx=0.04, vyaw=0.2
    ))})
    events.append({"event": "stop_refresh_1", "result": adapter.send(output(
        args.watchdog_config, 20, 20, stop=True
    ))})
    events.append({"event": "stop_refresh_2", "result": adapter.send(output(
        args.watchdog_config, 30, 30, stop=True
    ))})

    client.disconnect()
    second = client.connect()
    events.append({"event": "controller_reconnect", "generation": second.generation})
    try:
        adapter.send(output(args.watchdog_config, 40, 40, vx=0.04, vyaw=-0.2))
        raise AssertionError("movement crossed controller reconnect without safe stop")
    except MotionAdapterError as error:
        events.append({"event": "controller_reconnect_move_blocked", "error": str(error)})
    events.append({"event": "controller_reconnect_safe_stop", "result": adapter.send(output(
        args.watchdog_config, 50, 50, stop=True
    ))})
    events.append({"event": "controller_reconnect_resume", "result": adapter.send(output(
        args.watchdog_config, 60, 60, vx=0.04, vyaw=-0.2
    ))})

    pid = int(args.pid_file.read_text(encoding="ascii").strip())
    cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
    if str(args.robotd) not in cmdline or str(args.socket) not in cmdline:
        raise RuntimeError(f"refusing to terminate unverified pid {pid}: {cmdline}")
    os.kill(pid, 15)
    wait_for(lambda: not Path(f"/proc/{pid}").exists())
    try:
        adapter.send(output(args.watchdog_config, 70, 70, stop=True))
        raise AssertionError("silent robotd loss was not detected")
    except RobotdConnectionError as error:
        events.append({"event": "robotd_loss_detected_by_stop_refresh", "error": str(error)})

    env = dict(os.environ)
    env.update({
        "DUCK_IDENTITY": "duck-a",
        "DUCK_RUNTIME_DIR": str(args.runtime_dir),
        "ORT_DYLIB_PATH": str(args.ort_dylib),
        "RUST_LOG": "info",
    })
    args.restart_log.parent.mkdir(parents=True, exist_ok=True)
    log = args.restart_log.open("wb")
    process = subprocess.Popen([
        str(args.robotd), "--sim", f"127.0.0.1:{args.body_port}",
        "--params", str(args.params), "--socket", str(args.socket),
    ], env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    args.pid_file.write_text(f"{process.pid}\n", encoding="ascii")
    wait_for(lambda: args.socket.exists() and process.poll() is None)
    for _ in range(20):
        try:
            third = client.reconnect()
            break
        except (RobotdConnectionError, OSError):
            time.sleep(0.1)
    else:
        raise RuntimeError("robotd did not accept reconnect")
    events.append({"event": "robotd_restart", "generation": third.generation,
                   "pid_before": pid, "pid_after": process.pid})
    enabled = client.enable(True)
    events.append({"event": "robotd_restart_enable", "result": enabled})
    try:
        adapter.send(output(args.watchdog_config, 80, 80, vx=0.04, vyaw=0.2))
        raise AssertionError("movement crossed robotd restart without safe stop")
    except MotionAdapterError as error:
        events.append({"event": "robotd_restart_move_blocked", "error": str(error)})
    events.append({"event": "robotd_restart_safe_stop", "result": adapter.send(output(
        args.watchdog_config, 90, 90, stop=True
    ))})
    for index in range(25):
        resume_result = adapter.send(output(
            args.watchdog_config, 100 + index, 100 + index, vx=0.04, vyaw=0.2
        ))
        time.sleep(0.02)
    observer = RobotdClient(str(args.socket), timeout_s=2.0)
    observer.connect()
    resumed_state = observer.state(hz=50)
    observer.close()
    events.append({"event": "robotd_restart_resume", "result": resume_result,
                   "requested": resumed_state["move"]["requested"],
                   "applied": resumed_state["move"]["applied"],
                   "policy": resumed_state["policy"]})
    events.append({"event": "final_safe_stop", "result": adapter.send(output(
        args.watchdog_config, 140, 140, stop=True
    ))})
    client.close()
    log.close()
    report = {
        "schema_version": "p6-03-adapter-restart-v1",
        "fixture_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "started_with_generation": first.generation,
        "ended_with_generation": third.generation,
        "robotd_restart_exit_before_relaunch": True,
        "events": events,
        "ended_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
