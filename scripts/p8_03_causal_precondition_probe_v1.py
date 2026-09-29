"""One fresh, development-only Thor causal moving-precondition probe.

No behavioral controller, scored interval, or ARM path exists in this script.
The official simulator and robotd own all motion and safety behavior.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import threading
import time

from microduck_connectome.p8_03_causal_precondition_v1 import evaluate_causal_precondition
from microduck_connectome.robotd_client import RobotdClient
from microduck_connectome.robotd_diagnostic import RobotdDiagnosticRecorder
from scripts.p8_03_local_reference import RawBodyReader, acquire_local_reference


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_json(path, value):
    target = Path(path)
    temporary = target.with_suffix(target.suffix + ".tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(target)


class CommandSocket:
    def __init__(self, path):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(1.0)
        self.sock.connect(str(path))
        self.reader = self.sock.makefile("rb", buffering=0)
        self.next_id = 1

    def call(self, method, params, recorder=None):
        ident = self.next_id
        self.next_id += 1
        wire = (json.dumps({"jsonrpc": "2.0", "id": ident, "method": method,
                            "params": params}, separators=(",", ":")) + "\n").encode()
        sent_ns = time.clock_gettime_ns(time.CLOCK_MONOTONIC)
        if method == "robot.move":
            recorder.record_move_request(wire, sent_at_ns=sent_ns)
        self.sock.sendall(wire)
        while True:
            response = self.reader.readline()
            if not response:
                raise RuntimeError("robotd command socket closed")
            parsed = json.loads(response)
            if parsed.get("id") == ident:
                break
        received_ns = time.clock_gettime_ns(time.CLOCK_MONOTONIC)
        if method == "robot.move":
            recorder.record_move_ack(response, received_at_ns=received_ns)
        if "error" in parsed:
            raise RuntimeError(f"robotd {method}: {parsed['error']}")
        return parsed["result"], sent_ns, received_ns

    def close(self):
        self.reader.close()
        self.sock.close()


def run(args):
    root, upstream, rl, out = (Path(p).resolve() for p in
                               (args.root, args.upstream, args.microduck_rl, args.output))
    if out.exists():
        raise FileExistsError(out)
    out.mkdir(parents=True)
    config = json.loads((root / "config/p8_03_timing_probe_v2.json").read_text())
    gate = config["moving_gate"]
    master = json.loads((root / "config/p8_v2_final_protocol_v1.json").read_text())
    pre = master["scenario"]["moving_precondition"]
    if (platform.python_version_tuple()[:2] != ("3", "12") or
            not socket.gethostname().startswith("jetsonthor")):
        raise RuntimeError("Thor Python 3.12 required")
    if subprocess.check_output(["git", "-C", str(upstream), "rev-parse", "HEAD"],
                               text=True).strip() != "344925c9f8fa031f85428a305b1e8ec2eaae29c1":
        raise RuntimeError("upstream base mismatch")
    if subprocess.check_output(["git", "-C", str(upstream), "write-tree"],
                               text=True).strip() != "8118cb336af98fb0947f3de592843dc8b5434096":
        raise RuntimeError("reviewed candidate tree mismatch")
    patch = upstream / "diagnostic.patch"
    if sha(patch) != "828ff2619ee378d4fe49fe358944dcc9b5aa9b6583e7aef1afe43a353411655a":
        raise RuntimeError("reviewed patch mismatch")
    if subprocess.check_output(["git", "-C", str(rl), "rev-parse", "HEAD"],
                               text=True).strip() != "cb70b792312d559a4da09064d92009079671815f":
        raise RuntimeError("MuJoCo upstream mismatch")
    policy = Path(config["walking_policy_path"])
    if sha(policy) != config["walking_policy_sha256"]:
        raise RuntimeError("walking policy hash mismatch")
    simulator = upstream / "scripts/duck-sim"
    state_dir = Path(args.state_dir)
    sock = state_dir / "duck-a.sock"
    env = dict(os.environ, DUCK_SIM_VIEWER="0", DUCK_SIM_STATE=str(state_dir),
               DUCK_SIM_PORT=str(args.body_port), DUCK_SIM_RL=str(rl))
    env["PATH"] = "/home/juper007/.rustup/toolchains/stable-aarch64-unknown-linux-gnu/bin:" + env["PATH"]
    summary = {"schema_version": "p8-03-causal-probe-v1", "label": args.label,
               "result": "FAIL", "connectome_sha": subprocess.check_output(
                   ["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip(),
               "upstream_original_sha": "344925c9f8fa031f85428a305b1e8ec2eaae29c1",
               "upstream_candidate_sha": "c47085a57770c52ed4cd00d5960b17598df2d7af",
               "upstream_candidate_tree": "8118cb336af98fb0947f3de592843dc8b5434096",
               "patch_sha256": sha(patch)}
    recorder = command = None
    pose_stop = threading.Event()
    poses = []
    pose_error = []
    pose_thread = None
    try:
        with (out / "up.log").open("wb") as log:
            subprocess.run([str(simulator), "up"], env=env, stdout=log,
                           stderr=subprocess.STDOUT, check=True, timeout=120)
        up_ns = time.clock_gettime_ns(time.CLOCK_MONOTONIC)
        with (out / "policy-load.log").open("wb") as log:
            subprocess.run([str(simulator), "ctl", "policy", "load", "walk", str(policy)],
                           env=env, stdout=log, stderr=subprocess.STDOUT,
                           check=True, timeout=30)
        with (out / "policy-readback.json").open("wb") as log:
            subprocess.run([str(simulator), "ctl", "policy", "list", "--json"],
                           env=env, stdout=log, stderr=subprocess.STDOUT,
                           check=True, timeout=30)
        local = acquire_local_reference(str(sock), args.body_port,
                                        config["settled_gate"], up_ns)
        atomic_json(out / "local-reference.json", local)
        if local["result"] != "PASS":
            raise RuntimeError("local reference failed")
        recorder = RobotdDiagnosticRecorder(RobotdClient(str(sock), timeout_s=2),
                                             out / "diagnostic.jsonl")
        recorder.start()
        command = CommandSocket(sock)
        hello, _, _ = command.call("hello", {"api_version": 31})
        if hello["api_version"] != 32:
            raise RuntimeError("candidate robotd API mismatch")
        raw_rows = [json.loads(line) for line in (out / "diagnostic.jsonl").read_text().splitlines()]
        pre_move_tick = max(r["state"]["control_tick_sequence"] for r in raw_rows
                            if r["kind"] == "robot.state")
        body = RawBodyReader(args.body_port)
        def read_poses():
            try:
                while not pose_stop.is_set():
                    tick = time.clock_gettime_ns(time.CLOCK_MONOTONIC)
                    raw = body.read()
                    poses.append({"timestamp_ns": raw["response_ns"],
                                  "x_m": raw["x_m"], "y_m": raw["y_m"],
                                  "raw_body_packet": raw["raw_packet"]})
                    pose_stop.wait(max(0, .02 -
                                       (time.clock_gettime_ns(time.CLOCK_MONOTONIC) - tick) / 1e9))
            except BaseException as error:
                pose_error.append(f"{type(error).__name__}: {error}")
        pose_thread = threading.Thread(target=read_poses, daemon=True)
        pose_thread.start()
        period = int(gate["command_period_ms"] * 1e6)
        deadline = time.clock_gettime_ns(time.CLOCK_MONOTONIC)
        count = 91  # Provides >1.5 s after the first consumed tick.
        for i in range(count):
            remaining = (deadline + i * period - time.clock_gettime_ns(time.CLOCK_MONOTONIC)) / 1e9
            if remaining > 0:
                time.sleep(remaining)
            recorder.assert_healthy()
            result, sent, ack = command.call("robot.move", {
                "vx": pre["vx_mps"], "vy": pre["vy_mps"],
                "vyaw": pre["vyaw_radps"]}, recorder)
            if result.get("accepted") is not True or ack >= deadline + (i + 1) * period:
                raise RuntimeError("command ACK or cadence failed")
        eligibility_ns = deadline + count * period
        remaining = (eligibility_ns - time.clock_gettime_ns(time.CLOCK_MONOTONIC)) / 1e9
        if remaining > 0:
            time.sleep(remaining)
        recorder.assert_healthy()
        summary["pre_move_tick"] = pre_move_tick
        summary["eligibility_ns"] = eligibility_ns
        summary["pose_samples"] = len(poses)
        if pose_error:
            raise RuntimeError(f"official pose stream failed: {pose_error}")
        # Eligibility is assessed only after the entire causal window. No ARM follows.
        command.call("robot.stop", {})
        pose_stop.set()
        pose_thread.join(timeout=2)
        body.close()
        recorder.close()
        recorder = None
        atomic_json(out / "poses.json", poses)
        summary.update(evaluate_causal_precondition(
            out / "diagnostic.jsonl", poses, pre_move_tick=pre_move_tick,
            eligibility_ns=eligibility_ns, gate=gate))
    except BaseException as error:
        summary["error"] = f"{type(error).__name__}: {error}"
        if command is not None:
            try:
                command.call("robot.stop", {})
            except BaseException as stop_error:
                summary["stop_error"] = f"{type(stop_error).__name__}: {stop_error}"
    finally:
        pose_stop.set()
        if pose_thread is not None:
            pose_thread.join(timeout=2)
        if recorder is not None:
            try:
                recorder.close()
            except BaseException as error:
                summary["recorder_close_error"] = f"{type(error).__name__}: {error}"
        if command is not None:
            command.close()
        with (out / "down.log").open("wb") as log:
            result = subprocess.run([str(simulator), "down"], env=env, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=30)
        summary["final_down_exit"] = result.returncode
        summary["final_socket_absent"] = not sock.exists()
        probe = socket.socket()
        try:
            probe.bind(("127.0.0.1", args.body_port))
            summary["final_port_free"] = True
        except OSError:
            summary["final_port_free"] = False
        finally:
            probe.close()
        if not (summary["final_down_exit"] == 0 and summary["final_socket_absent"]
                and summary["final_port_free"]):
            summary["result"] = "FAIL"
        atomic_json(out / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser()
    for name in ("root", "upstream", "microduck-rl", "output", "state-dir", "label"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--body-port", required=True, type=int)
    args = parser.parse_args()
    report = run(args)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["result"] == "PASS" else 1)


if __name__ == "__main__":
    main()
