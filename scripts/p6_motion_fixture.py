"""Bounded P6-03 yaw/stop fixture for the pinned official Thor simulator."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import socket
import threading
import time


def wrapped_delta(final: float, initial: float) -> float:
    return math.atan2(math.sin(final - initial), math.cos(final - initial))


def quaternion_yaw(wxyz) -> float:
    w, x, y, z = wxyz
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


class JsonLines:
    def __init__(self, path: str):
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket.settimeout(2.0)
        self.socket.connect(path)
        self.file = self.socket.makefile("rwb")
        self.next_id = 1

    def request(self, method: str, params: dict):
        request_id = self.next_id
        self.next_id += 1
        self.file.write((json.dumps({"jsonrpc": "2.0", "id": request_id,
                                     "method": method, "params": params}) + "\n").encode())
        self.file.flush()
        while True:
            reply = json.loads(self.file.readline())
            if reply.get("id") == request_id:
                if "error" in reply:
                    raise RuntimeError(reply["error"])
                return reply["result"]

    def notify(self, method: str, params: dict):
        self.file.write((json.dumps({"jsonrpc": "2.0", "method": method,
                                     "params": params}) + "\n").encode())
        self.file.flush()

    def close(self):
        self.file.close()
        self.socket.close()


class StateStream:
    def __init__(self, path: str):
        self.latest = None
        self.received_ns = None
        self.error = None
        self.stop_event = threading.Event()
        self.connection = JsonLines(path)
        self.connection.file.write(b'{"jsonrpc":"2.0","id":1,"method":"robot.subscribe","params":{"hz":50}}\n')
        self.connection.file.flush()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        try:
            while not self.stop_event.is_set():
                raw = self.connection.file.readline()
                if not raw:
                    raise RuntimeError("state stream closed")
                message = json.loads(raw)
                if message.get("method") == "robot.state":
                    self.latest = message["params"]
                    self.received_ns = time.monotonic_ns()
        except BaseException as error:
            self.error = repr(error)

    def state(self):
        deadline = time.monotonic() + 2.0
        while self.latest is None and time.monotonic() < deadline:
            time.sleep(0.01)
        if self.error or self.latest is None:
            raise RuntimeError(self.error or "no robot.state received")
        if time.monotonic_ns() - self.received_ns > 100_000_000:
            raise RuntimeError("stale robot.state")
        if self.latest["safety"]["fallen"] or self.latest["safety"]["limp"]:
            raise RuntimeError("simulator safety fault")
        return self.latest

    def close(self):
        self.stop_event.set()
        self.connection.close()
        self.thread.join(timeout=0.5)


class BodyReader:
    def __init__(self, port: int):
        self.socket = socket.create_connection(("127.0.0.1", port), timeout=2.0)
        self.file = self.socket.makefile("rwb")
        self.file.write(b'{"op":"hello","protocol":1,"joints":15}\n')
        self.file.flush()
        hello = json.loads(self.file.readline())
        if hello != {"protocol": 1}:
            raise RuntimeError(f"unexpected body hello: {hello!r}")

    def read(self):
        self.file.write(b'{"op":"read"}\n')
        self.file.flush()
        return json.loads(self.file.readline())

    def close(self):
        self.file.close()
        self.socket.close()


def sample(stream, body, label):
    state = stream.state()
    sensors = body.read()
    return {
        "label": label,
        "monotonic_ns": time.monotonic_ns(),
        "robot_t_ns": state.get("t_ns"),
        "requested": state["move"]["requested"],
        "applied": state["move"]["applied"],
        "limited_by": state["move"].get("limited_by", []),
        "policy": state["policy"],
        "odom_yaw": state.get("odom", {}).get("yaw"),
        "trunk_quaternion_wxyz": sensors["imu"]["quat"],
        "trunk_yaw": quaternion_yaw(sensors["imu"]["quat"]),
        "trunk_z": sensors["trunk_z"],
    }


def tick_move(command, stream, body, seconds, *, vx, vyaw, trace, label):
    ticks = round(seconds * 50)
    for index in range(ticks):
        begin = time.monotonic()
        command.notify("robot.move", {"vx": vx, "vy": 0.0, "vyaw": vyaw})
        if index % 5 == 0 or index == ticks - 1:
            trace.append(sample(stream, body, f"{label}:{index}"))
        time.sleep(max(0.0, 0.02 - (time.monotonic() - begin)))


def yaw_trial(args, command, stream, body):
    trace = []
    tick_move(command, stream, body, 1.0, vx=0.0, vyaw=0.0, trace=trace, label="settle")
    initial = sample(stream, body, "initial")
    tick_move(command, stream, body, args.seconds, vx=args.vx,
              vyaw=args.sign * 0.2, trace=trace, label="command")
    final = sample(stream, body, "final")
    command.request("robot.stop", {})
    time.sleep(2.0)
    stopped = sample(stream, body, "stopped")
    return {
        "mode": "yaw", "sign": args.sign, "vx_mps": args.vx,
        "vyaw_radps": args.sign * 0.2, "duration_s": args.seconds,
        "initial": initial, "final": final, "stopped": stopped,
        "wrapped_heading_delta_rad": wrapped_delta(final["trunk_yaw"], initial["trunk_yaw"]),
        "wrapped_post_stop_delta_rad": wrapped_delta(stopped["trunk_yaw"], final["trunk_yaw"]),
        "trace": trace,
    }


def wait_and_sample(stream, body, seconds, trace, label):
    for index in range(round(seconds * 50)):
        if index % 5 == 0:
            trace.append(sample(stream, body, f"{label}:{index}"))
        time.sleep(0.02)


def stop_trial(args, command, stream, body):
    trace = []
    tick_move(command, stream, body, 1.0, vx=0.04, vyaw=0.2, trace=trace, label="pre_stop")
    before = sample(stream, body, "before_robot_stop")
    robot_stop_result = command.request("robot.stop", {})
    robot_stop_at_ns = time.monotonic_ns()
    wait_and_sample(stream, body, 1.0, trace, "robot_stop_persistence")
    after_robot_stop = sample(stream, body, "after_robot_stop")
    tick_move(command, stream, body, 0.6, vx=0.04, vyaw=-0.2, trace=trace, label="resume_after_robot_stop")
    resumed_robot_stop = sample(stream, body, "resumed_after_robot_stop")

    command.notify("robot.move", {"vx": 0.0, "vy": 0.0, "vyaw": 0.0})
    zero_twist_at_ns = time.monotonic_ns()
    wait_and_sample(stream, body, 1.0, trace, "zero_twist_persistence")
    after_zero_twist = sample(stream, body, "after_zero_twist")
    tick_move(command, stream, body, 0.6, vx=0.04, vyaw=0.2, trace=trace, label="resume_after_zero_twist")
    resumed_zero_twist = sample(stream, body, "resumed_after_zero_twist")

    command.close()
    command = JsonLines(args.socket)
    hello = command.request("hello", {"api_version": 31})
    restart_stop_result = command.request("robot.stop", {})
    wait_and_sample(stream, body, 0.6, trace, "controller_restart_stop")
    after_restart_stop = sample(stream, body, "after_controller_restart_stop")
    return {
        "mode": "stop", "robot_stop_result": robot_stop_result,
        "restart_hello": hello, "restart_stop_result": restart_stop_result,
        "robot_stop_at_ns": robot_stop_at_ns, "zero_twist_at_ns": zero_twist_at_ns,
        "before": before, "after_robot_stop": after_robot_stop,
        "resumed_robot_stop": resumed_robot_stop,
        "after_zero_twist": after_zero_twist,
        "resumed_zero_twist": resumed_zero_twist,
        "after_controller_restart_stop": after_restart_stop,
        "trace": trace,
    }, command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--body-port", type=int, required=True)
    parser.add_argument("--mode", choices=("yaw", "stop"), required=True)
    parser.add_argument("--sign", type=int, choices=(-1, 1))
    parser.add_argument("--seconds", type=float, default=6.0)
    parser.add_argument("--vx", type=float, choices=(0.0, 0.04), default=0.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "yaw" and args.sign is None:
        parser.error("--sign is required for yaw mode")

    started_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    command = JsonLines(args.socket)
    hello = command.request("hello", {"api_version": 31})
    stream = StateStream(args.socket)
    body = BodyReader(args.body_port)
    try:
        if args.mode == "yaw":
            result = yaw_trial(args, command, stream, body)
        else:
            result, command = stop_trial(args, command, stream, body)
        result.update({"started_utc": started_utc,
                       "ended_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                       "robotd_hello": hello,
                       "fixture_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(json.dumps({key: value for key, value in result.items() if key != "trace"}, sort_keys=True))
    finally:
        try:
            command.request("robot.stop", {})
        finally:
            command.close()
            stream.close()
            body.close()


if __name__ == "__main__":
    main()
