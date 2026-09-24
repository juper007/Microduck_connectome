"""Inject P6-06 faults against Thor's official robotd and MuJoCo body."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import select
import signal
import socket
import subprocess
import threading
import time
import sys

from microduck_connectome.control_contracts import make_behavior_intent
from microduck_connectome.dn_aggregator import DNActivityAggregator, load_dn_readout_config
from microduck_connectome.escape_decoder import EscapeDecoder, load_escape_decoder_config
from microduck_connectome.fault_evidence import REQUIRED_FAULTS, build_fault_matrix, make_fault_record, write_fault_matrix
from microduck_connectome.graph import ConnectomeGraph
from microduck_connectome.motion_adapter import MotionAdapterError, RobotMotionAdapter
from microduck_connectome.perception_compositor import PerceptionPipeline
from microduck_connectome.robotd_client import RobotdClient, RobotdConnectionError, RobotdTimeoutError
from microduck_connectome.safety_clamp import SafetyClamp, load_safety_envelope
from microduck_connectome.scheduler import ClosedLoopScheduler, NeuralUpdate, SchedulerWorkerError
from microduck_connectome.sensory_mapping import SensoryMapper, load_sensory_mapping_config
from microduck_connectome.sparse_runtime import SparseNeuralRuntime
from microduck_connectome.steering_decoder import SteeringDecoder, load_steering_decoder_config
from microduck_connectome.watchdog import ControllerWatchdog


def git_head(path: Path) -> str:
    return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()


def wait_for(predicate, timeout_s=12.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise RuntimeError("timed out waiting for scoped runtime lifecycle")


def process_exited(pid: int) -> bool:
    """Treat an unreaped child zombie as exited; it cannot own IPC or motion."""
    stat = Path(f"/proc/{pid}/stat")
    if not stat.exists():
        return True
    try:
        return stat.read_text(encoding="ascii").split()[2] == "Z"
    except (OSError, IndexError):
        return not stat.exists()


def quaternion_yaw(wxyz):
    w, x, y, z = wxyz
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


class BodyReader:
    def __init__(self, port):
        self.socket = socket.create_connection(("127.0.0.1", port), timeout=2.0)
        self.file = self.socket.makefile("rwb")
        self.file.write(b'{"op":"hello","protocol":1,"joints":15}\n')
        self.file.flush()
        if json.loads(self.file.readline()) != {"protocol": 1}:
            raise RuntimeError("unexpected MuJoCo body hello")

    def heading(self):
        self.file.write(b'{"op":"read"}\n')
        self.file.flush()
        return quaternion_yaw(json.loads(self.file.readline())["imu"]["quat"])

    def close(self):
        self.file.close()
        self.socket.close()


class WorkerFaultChain:
    """Real P4→MaleCNS→DN→decoder→safety worker with one injected fault."""

    def __init__(self, root: Path, graph: ConnectomeGraph, fault: str):
        self.fault = fault
        self.started_ns = time.monotonic_ns()
        self.injected_at_ns = None
        self.events = []
        self.lock = threading.Lock()
        self.pipeline = PerceptionPipeline()
        sensory_config = load_sensory_mapping_config(root / "config/sensory_mapping_v1.json")
        sensory_ids = tuple(sorted(x for spec in sensory_config["populations"].values() for x in spec["body_ids"]))
        self.mapper = SensoryMapper(sensory_ids, sensory_config)
        self.runtime = SparseNeuralRuntime(graph, json.loads((root / "config/neural_model_v1.json").read_text()))
        dn_config = load_dn_readout_config(root / "config/dn_readout_v1.json")
        self.dn_ids = tuple(sorted(x for spec in dn_config["populations"].values() for x in spec["body_ids"]))
        self.aggregator = DNActivityAggregator(self.dn_ids, dn_config)
        self.index = {body_id: index for index, body_id in enumerate(graph.body_ids)}
        self.steering = SteeringDecoder(load_steering_decoder_config(root / "config/steering_decoder_v1.json"))
        self.escape = EscapeDecoder(load_escape_decoder_config(root / "config/escape_decoder_v1.json"))
        self.safety = SafetyClamp(load_safety_envelope(root / "config/safety_envelope_v1.json"))
        self.frame_id = 0
        self.sequence = 0
        self.frozen_behavior = None
        self.frozen_safe = None
        self.completed_updates = 0
        self.fault_armed = False
        self.fault_active = False
        self.pre_fault_snapshot = None

    def inject(self, point, now_ns, **details):
        with self.lock:
            if self.injected_at_ns is None:
                self.injected_at_ns = now_ns
            self.events.append({"timestamp_ns": now_ns, "injected_point": point, **details})

    def perception(self, now_ns):
        self.frame_id += 1
        fault = self.fault
        sensor_fault = fault in ("camera_dropout", "tof_dropout", "stale_perception", "invalid_perception", "compositor_invalid", "extreme_target_position")
        if sensor_fault and self.fault_armed:
            self.fault_active = True
        stale = self.fault_active and fault == "stale_perception"
        camera_valid = not (self.fault_active and fault == "camera_dropout")
        tof_valid = not (self.fault_active and fault == "tof_dropout")
        camera_ns = now_ns - 100_000_001 if stale else now_ns
        tof_ns = now_ns - 100_000_001 if stale else now_ns
        if self.fault_active and fault == "compositor_invalid":
            tof_ns = now_ns - 100_000_001
        # A sustained, strong left observation establishes non-neutral motion
        # through the pinned MaleCNS graph before sensor loss is injected.
        red, black = (255, 0, 0), (0, 0, 0)
        frame = self.pipeline.process(
            ((red, red, black),), camera_timestamp_ns=camera_ns,
            camera_frame_id=self.frame_id, tof_left_mm=500, tof_center_mm=500,
            tof_right_mm=500, tof_timestamp_ns=tof_ns, tof_frame_id=self.frame_id,
            now_ns=now_ns, camera_source_valid=camera_valid,
            tof_source_valid=tof_valid,
        )
        if self.fault_active and fault in ("invalid_perception", "extreme_target_position"):
            frame = dict(frame); frame["target_x"] = 1e9 if fault == "extreme_target_position" else 2.0
            self.inject("PerceptionFrame output", now_ns, observed_reason="out_of_range_target_x", frame_valid=frame["valid"])
        elif fault == "maximal_looming_stimulus":
            frame = dict(frame); frame["looming"] = 1.0
            self.inject("PerceptionFrame looming stimulus", now_ns, value=1.0, frame_valid=frame["valid"])
        elif self.fault_active and sensor_fault:
            self.inject("PerceptionCompositor", now_ns, compositor_reasons=list(self.pipeline.compositor.last_reasons), frame_valid=frame["valid"])
        return frame

    def neural(self, frame, now_ns):
        self.sequence += 1
        channels = self.mapper.map_channels(frame, now_ns=now_ns) if frame is not None else {}
        sensor_fault = self.fault in ("camera_dropout", "tof_dropout", "stale_perception", "invalid_perception", "compositor_invalid", "extreme_target_position")
        if self.fault_active and sensor_fault:
            self.events.append({"timestamp_ns": now_ns, "observed_point": "SensoryMapper", "channels": channels})
            return None
        mapped = {} if frame is None else self.mapper.build_external(frame, now_ns=now_ns)
        external = {key: value for key, value in mapped.items() if key in self.index}
        if self.fault == "neural_unavailable":
            self.inject("MaleCNS Runtime", now_ns, action="raise unavailable")
            raise RuntimeError("injected neural runtime unavailable")
        snapshot = self.runtime.step(external)
        if self.fault == "neural_freeze" and self.completed_updates >= 2:
            self.inject("MaleCNS Runtime", now_ns, action="freeze updates")
            return None
        projected = tuple(snapshot["spikes"][self.index[x]] if x in self.index else False for x in self.dn_ids)
        healthy = snapshot["healthy"]
        if self.fault == "runtime_unhealthy":
            self.inject("MaleCNS Runtime", now_ns, action="runtime_healthy=false")
            healthy = False
        readout = self.aggregator.update(projected, timestamp_ns=now_ns, sequence=self.sequence, runtime_healthy=healthy)
        if self.fault == "malformed_neural":
            self.inject("DNActivityAggregator output", now_ns, action="NaN activity")
            readout = dict(readout); readout["steering_left"] = float("nan")
        if self.fault == "decoder_crash":
            self.inject("SteeringDecoder", now_ns, action="raise crash")
            raise RuntimeError("injected decoder crash")
        decoded = self.escape.apply(readout, self.steering.decode(readout))
        if self.fault == "decoder_stale":
            if self.frozen_safe is not None and self.completed_updates >= 2:
                self.inject("decoder output", now_ns, action="freeze behavior")
                self.completed_updates += 1
                return NeuralUpdate(readout, self.frozen_safe["intent"], {"channels": channels, "safety_reasons": self.frozen_safe["reasons"]})
        safe = self.safety.apply(decoded, now_ns=now_ns, fallback_sequence=self.sequence)
        self.frozen_safe = safe
        self.completed_updates += 1
        if sensor_fault and self.pre_fault_snapshot is None and any(abs(safe["intent"][key]) > 0.0 for key in ("vx", "vy", "vyaw")):
            self.pre_fault_snapshot = {
                "timestamp_ns": now_ns, "frame": dict(frame), "stimulus_channels": channels,
                "dn_readout": dict(readout), "robot_facing_intent": dict(safe["intent"]),
            }
            self.events.append({"timestamp_ns": now_ns, "observed_point": "healthy_non_neutral_full_chain", "snapshot": self.pre_fault_snapshot})
            self.fault_armed = True
        return NeuralUpdate(readout, safe["intent"], {"channels": channels, "safety_reasons": safe["reasons"]})


class Session:
    def __init__(self, args, raw):
        self.args = args
        self.raw = raw
        self.sequence = 0
        self.client = RobotdClient(str(args.socket), timeout_s=args.timeout_s)
        self.client.connect()
        self.client.enable(True)
        self.adapter = RobotMotionAdapter(self.client, args.root / "config/motion_adapter_v1.json")
        self.body = BodyReader(args.body_port)

    def next_meta(self):
        self.sequence += 2
        return time.monotonic_ns(), self.sequence

    def output(self, *, stop=False, vx=0.0, vyaw=0.0, mode="healthy"):
        timestamp, sequence = self.next_meta()
        watchdog = ControllerWatchdog(self.args.root / "config/watchdog_v1.json")
        if mode == "decoder_crash":
            watchdog.mark_decoder_crashed(1)
        elif mode == "missing":
            pass
        else:
            neural_time = timestamp
            behavior_time = timestamp
            healthy = True
            if mode in ("stale_neural", "stale_behavior"):
                if mode == "stale_neural": neural_time -= 100_000_001
                else: behavior_time -= 100_000_001
            if mode == "runtime_unhealthy": healthy = False
            neural = {
                "timestamp_ns": neural_time, "sequence": sequence,
                "steering_left": 0.0, "steering_right": 0.2,
                "escape": 0.0, "runtime_healthy": healthy,
            }
            if mode == "malformed_neural": neural["steering_left"] = float("nan")
            watchdog.observe_neural(neural)
            watchdog.observe_behavior(make_behavior_intent(
                timestamp_ns=behavior_time, sequence=sequence,
                vx=vx, vyaw=vyaw, stop=stop,
            ))
        output = watchdog.tick(now_ns=time.monotonic_ns(), output_sequence=sequence + 1)
        return output

    def motion(self):
        output = self.output(vyaw=0.2)
        self.adapter.send(output)
        time.sleep(0.06)
        return output

    def safe_state(self, *, require_deadman=False):
        observer = RobotdClient(str(self.args.socket), timeout_s=2.0)
        observer.connect()
        # robot.stop changes policy immediately, while the official policy's
        # applied velocity converges through its own bounded smoothing.
        deadline = time.monotonic() + 3.0
        state = None
        while time.monotonic() < deadline:
            state = observer.state(hz=50)
            requested = state["move"]["requested"]
            applied = state["move"]["applied"]
            stopped = all(abs(float(v)) <= 1e-6 for v in applied)
            source = "deadman" in state["move"]["limited_by"] if require_deadman else all(abs(float(v)) <= 1e-6 for v in requested)
            if stopped and source:
                break
        else:
            raise RuntimeError(f"official robot.state did not reach rest: {state['move']!r}")
        # Require five consecutive actual robot/body windows at rest. A single
        # zero command or one coincidentally small heading delta is insufficient.
        heading_deadline = time.monotonic() + 5.0
        headings = [self.body.heading()]
        heading_times = [time.monotonic_ns()]
        rates = []
        command_samples = []
        while len(rates) < 5:
            time.sleep(0.10)
            sample = observer.state(hz=50)
            sample_ns = time.monotonic_ns()
            heading = self.body.heading()
            requested = list(sample["move"]["requested"])
            applied = list(sample["move"]["applied"])
            rate = (heading - headings[-1]) / ((sample_ns - heading_times[-1]) / 1e9)
            if (
                all(abs(float(v)) <= 1e-6 for v in applied)
                and ("deadman" in sample["move"]["limited_by"] if require_deadman else all(abs(float(v)) <= 1e-6 for v in requested))
                and abs(rate) <= 0.01
            ):
                headings.append(heading); heading_times.append(sample_ns); rates.append(rate)
                command_samples.append({"timestamp_ns": sample_ns, "requested": requested, "applied": applied, "limited_by": list(sample["move"]["limited_by"])})
            else:
                headings = [heading]; heading_times = [sample_ns]; rates = []; command_samples = []
            if time.monotonic() >= heading_deadline:
                raise RuntimeError(f"MuJoCo/robot.state did not settle for five windows: rate={rate}, move={sample['move']!r}")
        observer.close()
        before, after = headings[0], headings[-1]
        delta = abs(after - before)
        return {
            "requested": list(state["move"]["requested"]),
            "applied": list(state["move"]["applied"]),
            "limited_by": list(state["move"]["limited_by"]),
            "heading_before_rad": before, "heading_after_rad": after,
            "heading_delta_rad": delta,
            "settled_windows": 5, "heading_samples": headings,
            "angular_rate_samples_radps": rates,
            "max_abs_angular_rate_radps": max(abs(value) for value in rates),
            "command_samples": command_samples,
        }

    def recover(self, old_output):
        try:
            self.adapter.send(old_output)
            raise AssertionError("pre-fault command replay was accepted")
        except MotionAdapterError:
            pass
        fresh = self.output(vyaw=-0.2)
        self.adapter.send(fresh)
        time.sleep(0.04)
        self.adapter.send(self.output(mode="missing"))
        self.safe_state()
        return time.monotonic_ns()

    def assert_fresh_stop_gate(self):
        """A new post-reconnect motion must fail before any fresh safe stop."""
        fresh_motion = self.output(vyaw=0.2)
        try:
            self.adapter.send(fresh_motion)
        except MotionAdapterError as error:
            if str(error) != "reconnect requires a fresh watchdog safe-stop output":
                raise AssertionError(f"wrong reconnect rejection: {error}") from error
            return str(error)
        raise AssertionError("fresh motion crossed reconnect boundary before safe stop")

    def close(self):
        try: self.client.close()
        finally: self.body.close()


def observe_perception(root, fault):
    pipeline = PerceptionPipeline()
    now = time.monotonic_ns()
    timestamp = now - 100_000_001 if fault == "stale_perception" else now
    camera_valid = fault not in ("camera_dropout", "invalid_perception", "compositor_invalid")
    tof_valid = fault != "tof_dropout"
    frame = pipeline.process(
        (((255, 0, 0),),), camera_timestamp_ns=timestamp, camera_frame_id=1,
        tof_left_mm=500, tof_center_mm=500, tof_right_mm=500,
        tof_timestamp_ns=timestamp, tof_frame_id=1, now_ns=now,
        camera_source_valid=camera_valid, tof_source_valid=tof_valid,
    )
    if frame["valid"]:
        raise AssertionError(f"{fault} did not neutralize perception")
    return {"valid": frame["valid"], "reasons": list(pipeline.compositor.last_reasons)}


def scheduler_fault(session, graph, name, raw):
    chain = WorkerFaultChain(session.args.root, graph, name)
    observations = []
    pre_fault_transport = {}

    def publish(output):
        result = session.adapter.send(output)
        observations.append({
            "timestamp_ns": time.monotonic_ns(),
            "watchdog_state": output["watchdog_state"],
            "stale_reason": output["stale_reason"],
            "stop": output["intent"]["stop"],
            "vx": output["intent"]["vx"], "vy": output["intent"]["vy"],
            "vyaw": output["intent"]["vyaw"],
            "intent_timestamp_ns": output["intent"]["timestamp_ns"],
            "intent_sequence": output["intent"]["sequence"],
            "transport_result": result,
        })
        if chain.injected_at_ns is None and any(abs(output["intent"][key]) > 0.0 for key in ("vx", "vy", "vyaw")):
            pre_fault_transport["output"] = output
            pre_fault_transport["snapshot"] = dict(observations[-1])
        return result

    scheduler = ClosedLoopScheduler(
        config=session.args.root / "config/scheduler_v1.json",
        watchdog=ControllerWatchdog(session.args.root / "config/watchdog_v1.json"),
        perception_step=chain.perception, neural_step=chain.neural,
        publisher=publish,
    )
    scheduler._output_sequence = session.sequence + 100
    expected_worker_error = name in ("invalid_perception", "extreme_target_position", "malformed_neural", "neural_unavailable", "decoder_crash")
    sensor_fault = name in ("camera_dropout", "tof_dropout", "stale_perception", "invalid_perception", "compositor_invalid", "extreme_target_position")
    try:
        scheduler.run(1.50 if sensor_fault else 0.45)
        if expected_worker_error:
            raise AssertionError(f"{name} worker fault did not propagate")
    except SchedulerWorkerError as error:
        if not expected_worker_error:
            raise
        chain.events.append({"timestamp_ns": time.monotonic_ns(), "observed_point": "scheduler_exception", "error": str(error)})
    session.sequence = max(session.sequence, scheduler._output_sequence + 2)
    injected = chain.injected_at_ns
    if injected is None:
        raise AssertionError(f"{name} injection point was not reached")
    if sensor_fault and chain.pre_fault_snapshot is None:
        raise AssertionError(f"{name} lacked a healthy non-neutral full-chain pre-fault command")
    if sensor_fault and "output" not in pre_fault_transport:
        raise AssertionError(f"{name} lacked an actual non-neutral robot-facing transport")
    causal = next((item for item in observations if item["timestamp_ns"] >= injected and item["stop"]), None)
    if causal is None:
        raise AssertionError(f"{name} did not propagate to a robot-facing stop")
    detected = causal["timestamp_ns"]
    safe_at = detected
    state = session.safe_state()
    stopped = time.monotonic_ns()
    old = pre_fault_transport.get("output")
    if old is None:
        # Non-sensor faults need only an authentic previously published output
        # for replay rejection; use the latest live scheduler output.
        old = next((item for item in reversed(getattr(session, "_published_outputs", []))), None)
    if old is None:
        old = session.output(mode="missing")
        session.adapter.send(old)
    recovered = session.recover(old)
    pre_transport = pre_fault_transport.get("snapshot")
    replayed = [] if pre_transport is None else [
        item for item in observations if item["timestamp_ns"] >= injected
        and item["intent_timestamp_ns"] == pre_transport["intent_timestamp_ns"]
        and item["intent_sequence"] == pre_transport["intent_sequence"]
    ]
    if replayed:
        raise AssertionError(f"{name} replayed the pre-fault autonomous command")
    raw.append({
        "fault": name,
        "injected_at_ns": injected,
        "injection_and_propagation": chain.events,
        "robot_facing_observations": observations,
        "causal_stale_reason": causal["stale_reason"],
        "causal_transport_result": causal["transport_result"],
        "pre_fault_snapshot": chain.pre_fault_snapshot,
        "pre_fault_robot_transport": pre_fault_transport.get("snapshot"),
        "old_command_replay_matches": replayed,
    })
    return make_fault_record(
        fault=name, injected_at_ns=injected, detected_at_ns=detected,
        safe_command_at_ns=safe_at, motion_stopped_at_ns=stopped,
        recovery_at_ns=recovered, state_evidence=state,
    )


def standard_fault(session, name, mode, raw, perception=False):
    old = session.motion()
    injected = time.monotonic_ns()
    if mode in ("stale_neural", "stale_behavior") or name == "stale_perception":
        # A freeze/stale fault begins when updates cease. Let the frozen 100 ms
        # TTL elapse in monotonic wall time instead of fabricating zero latency.
        time.sleep(0.101)
    condition = observe_perception(session.args.root, name) if perception else {"mode": mode}
    output = session.output(mode=mode)
    if output["watchdog_state"] != "safe_stop" or not output["intent"]["stop"]:
        raise AssertionError(f"{name} did not reach watchdog safe stop")
    detected = time.monotonic_ns()
    session.adapter.send(output)
    safe_at = time.monotonic_ns()
    state = session.safe_state()
    stopped = time.monotonic_ns()
    recovered = session.recover(old)
    raw.append({"fault": name, "condition": condition, "stale_reason": output["stale_reason"]})
    return make_fault_record(
        fault=name, injected_at_ns=injected, detected_at_ns=detected,
        safe_command_at_ns=safe_at, motion_stopped_at_ns=stopped,
        recovery_at_ns=recovered, state_evidence=state,
    )


def maximal_looming_fault(session, graph, raw):
    """Hold a maximal bounded looming frame through the full chain, then stop."""
    name = "maximal_looming_stimulus"
    chain = WorkerFaultChain(session.args.root, graph, name)
    observations = []
    outputs = []

    def publish(output):
        result = session.adapter.send(output)
        intent = output["intent"]
        values = (intent["vx"], intent["vy"], intent["vyaw"])
        if not all(math.isfinite(value) for value in values) or abs(values[0]) > 0.08 or values[1] != 0.0 or abs(values[2]) > 0.50:
            raise AssertionError("maximal looming escaped the post-watchdog motion envelope")
        outputs.append(output)
        observations.append({"timestamp_ns": time.monotonic_ns(), "watchdog_state": output["watchdog_state"],
                             "intent": dict(intent), "transport_result": result})
        return result

    scheduler = ClosedLoopScheduler(
        config=session.args.root / "config/scheduler_v1.json",
        watchdog=ControllerWatchdog(session.args.root / "config/watchdog_v1.json"),
        perception_step=chain.perception, neural_step=chain.neural, publisher=publish,
    )
    scheduler._output_sequence = session.sequence + 100
    summary = scheduler.run(1.0)
    session.sequence = scheduler._output_sequence + 2
    injected = chain.injected_at_ns
    if injected is None or len(chain.events) < 20 or not all(item["frame_valid"] for item in chain.events):
        raise AssertionError("continuous maximal looming stimulus did not traverse valid perception frames")
    if len(observations) < 30 or not outputs[-1]["intent"]["stop"]:
        raise AssertionError("maximal looming lacked continuous bounded publishing and shutdown stop")
    causal = next((item for item in observations if item["timestamp_ns"] >= injected), None)
    safe = observations[-1]
    if safe["transport_result"] != "robot_stop_refreshed":
        raise AssertionError("maximal looming shutdown did not use frozen stop transport")
    state = session.safe_state()
    stopped = time.monotonic_ns()
    recovered = session.recover(outputs[-1])
    raw.append({"fault": name, "injection_and_propagation": chain.events,
                "robot_facing_observations": observations, "scheduler_summary": summary})
    return make_fault_record(fault=name, injected_at_ns=injected, detected_at_ns=causal["timestamp_ns"],
                             safe_command_at_ns=safe["timestamp_ns"], motion_stopped_at_ns=stopped,
                             recovery_at_ns=recovered, state_evidence=state)


def process_worker(args, graph):
    """Run the real scheduler in a separate OS process until externally stopped."""
    session = Session(args, [])
    chain = WorkerFaultChain(args.root, graph, "none")
    ready = False

    def publish(output):
        nonlocal ready
        result = session.adapter.send(output)
        intent = output["intent"]
        if not ready and output["watchdog_state"] == "healthy" and any(abs(intent[key]) > 0.0 for key in ("vx", "vy", "vyaw")):
            print(json.dumps({"kind": "motion_ready", "pid": os.getpid(), "timestamp_ns": time.monotonic_ns(),
                              "intent_timestamp_ns": intent["timestamp_ns"], "intent_sequence": intent["sequence"],
                              "transport_result": result}), flush=True)
            ready = True
        return result

    scheduler = ClosedLoopScheduler(
        config=args.root / "config/scheduler_v1.json",
        watchdog=ControllerWatchdog(args.root / "config/watchdog_v1.json"),
        perception_step=chain.perception, neural_step=chain.neural, publisher=publish,
    )
    try:
        scheduler.run(30.0)
    finally:
        session.close()
    if not ready:
        raise AssertionError("separate controller process never produced healthy motion")


def process_fault(session, name, args, raw):
    """Kill or freeze the actual connectome worker and observe robotd deadman."""
    args.raw_artifact.parent.mkdir(parents=True, exist_ok=True)
    worker_log = args.raw_artifact.parent / f"{name}-worker.log"
    with worker_log.open("wb") as log:
        worker = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--worker-fault", name],
            stdout=subprocess.PIPE, stderr=log, text=True, bufsize=1, start_new_session=True,
        )
        try:
            if not select.select([worker.stdout], [], [], 12.0)[0]:
                raise RuntimeError(f"{name} worker did not establish healthy full-chain motion")
            marker = json.loads(worker.stdout.readline())
            if marker.get("kind") != "motion_ready" or marker.get("pid") != worker.pid or worker.poll() is not None:
                raise RuntimeError(f"{name} worker readiness was invalid: {marker!r}")
            observer = RobotdClient(str(args.socket), timeout_s=2.0)
            observer.connect()
            try:
                wait_for(lambda: any(abs(float(v)) > 1e-6 for v in observer.state(hz=50)["move"]["applied"]), timeout_s=4.0)
                before = observer.state(hz=50)["move"]
                injected = time.monotonic_ns()
                os.kill(worker.pid, signal.SIGKILL if name == "connectome_process_crash" else signal.SIGSTOP)
                if name == "connectome_process_crash":
                    worker.wait(timeout=3.0)
                    if worker.returncode is None:
                        raise AssertionError("controller process did not crash")
                else:
                    wait_for(lambda: Path(f"/proc/{worker.pid}/stat").read_text().split()[2] == "T", timeout_s=2.0)
                detected = time.monotonic_ns()
                deadline = time.monotonic() + 3.0
                while time.monotonic() < deadline:
                    move = observer.state(hz=50)["move"]
                    if "deadman" in move["limited_by"] and all(abs(float(v)) <= 1e-6 for v in move["applied"]):
                        safe_at = time.monotonic_ns()
                        break
                else:
                    raise RuntimeError(f"{name} did not reach official robotd deadman: {move!r}")
                state = session.safe_state(require_deadman=True)
                stopped = time.monotonic_ns()
            finally:
                observer.close()
            if worker.poll() is None:
                worker.kill()
                worker.wait(timeout=5.0)
            stop = session.output(mode="missing")
            session.adapter.send(stop)
            session.safe_state()
            recovered = session.recover(stop)
            raw.append({"fault": name, "injected_point": "separate full-chain controller process",
                        "worker_pid": worker.pid, "worker_marker": marker, "pre_fault_move": before,
                        "observed_deadman_move": move, "worker_log": str(worker_log),
                        "worker_log_sha256": hashlib.sha256(worker_log.read_bytes()).hexdigest()})
            return make_fault_record(
                fault=name, injected_at_ns=injected, detected_at_ns=detected,
                safe_command_at_ns=safe_at, motion_stopped_at_ns=stopped,
                recovery_at_ns=recovered, state_evidence=state,
            )
        finally:
            if worker.poll() is None:
                worker.kill()
                worker.wait(timeout=5.0)
            if worker.stdout is not None:
                worker.stdout.close()


def verified_pid(pid_file: Path, expected: Path, socket_path: Path):
    pid = int(pid_file.read_text(encoding="ascii").strip())
    cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
    if str(expected) not in cmdline or str(socket_path) not in cmdline:
        raise RuntimeError(f"refusing to signal unverified pid {pid}: {cmdline}")
    return pid


def restart_robotd(args):
    env = dict(os.environ)
    env.update({"DUCK_IDENTITY": "duck-a", "DUCK_RUNTIME_DIR": str(args.runtime_dir),
                "ORT_DYLIB_PATH": str(args.ort_dylib), "RUST_LOG": "info"})
    log = args.runtime_dir / "p6-06-robotd-restart.log"
    handle = log.open("ab")
    process = subprocess.Popen([
        str(args.robotd), "--sim", f"127.0.0.1:{args.body_port}",
        "--params", str(args.params), "--socket", str(args.socket),
    ], env=env, stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
    args.pid_file.write_text(f"{process.pid}\n", encoding="ascii")
    wait_for(lambda: args.socket.exists() and process.poll() is None)
    handle.close()
    return process.pid


def reconnect_and_stop(session):
    wait_for(lambda: session.args.socket.exists())
    session.client.reconnect()
    session.client.enable(True)
    gate_rejection = session.assert_fresh_stop_gate()
    stop = session.output(mode="missing")
    session.adapter.send(stop)
    safe_at = time.monotonic_ns()
    session.body.close()
    session.body = BodyReader(session.args.body_port)
    state = session.safe_state()
    return safe_at, state, time.monotonic_ns(), gate_rejection


def lifecycle_fault(session, name, args, raw, action):
    old = session.motion()
    injected = time.monotonic_ns()
    action()
    try:
        session.adapter.send(session.output(mode="missing"))
        raise AssertionError(f"{name} was not detected")
    except (RobotdConnectionError, RobotdTimeoutError, OSError):
        detected = time.monotonic_ns()
    restart_robotd(args)
    safe_at, state, stopped, gate_rejection = reconnect_and_stop(session)
    recovered = session.recover(old)
    raw.append({"fault": name, "actual_lifecycle": True, "fresh_stop_gate_rejection": gate_rejection})
    return make_fault_record(
        fault=name, injected_at_ns=injected, detected_at_ns=detected,
        safe_command_at_ns=safe_at, motion_stopped_at_ns=stopped,
        recovery_at_ns=recovered, state_evidence=state,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--graph-cache", type=Path, required=True)
    parser.add_argument("--graph-key", required=True)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--body-port", type=int, required=True)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--pid-file", type=Path, required=True)
    parser.add_argument("--robotd", type=Path, required=True)
    parser.add_argument("--params", type=Path, required=True)
    parser.add_argument("--ort-dylib", type=Path, required=True)
    parser.add_argument("--duck-sim", type=Path, required=True)
    parser.add_argument("--microduck", type=Path, required=True)
    parser.add_argument("--microduck-rl", type=Path, required=True)
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--raw-artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-s", type=float, default=0.15)
    parser.add_argument("--worker-fault", choices=("connectome_process_crash", "connectome_process_freeze"))
    args = parser.parse_args()
    if not socket.gethostname().startswith("jetsonthor") or platform.python_version_tuple()[:2] != ("3", "12"):
        raise RuntimeError("P6-06 runtime authority requires Thor and Python 3.12")
    if re.fullmatch(r"[0-9a-f]{40}", args.source_head) is None:
        raise ValueError("source-head must be a full SHA")
    if git_head(args.root) != args.source_head:
        raise RuntimeError("runtime checkout HEAD does not match declared source-head")

    raw = []
    records = []
    graph = ConnectomeGraph.from_cache(args.graph_cache, args.graph_key)
    if args.worker_fault is not None:
        process_worker(args, graph)
        return
    session = Session(args, raw)
    try:
        for name in REQUIRED_FAULTS[:12]:
            records.append(scheduler_fault(session, graph, name, raw))
        records.append(standard_fault(session, "delayed_command", "stale_behavior", raw))
        records.append(maximal_looming_fault(session, graph, raw))
        for name in ("connectome_process_crash", "connectome_process_freeze"):
            records.append(process_fault(session, name, args, raw))

        def kill_current():
            pid = verified_pid(args.pid_file, args.robotd, args.socket)
            os.kill(pid, signal.SIGTERM)
            wait_for(lambda: process_exited(pid))
            return pid

        # Peer-side disconnect is detected by an actual read on the active client.
        old = session.motion(); injected = time.monotonic_ns(); pid = kill_current()
        try: session.client.health(); raise AssertionError("peer disconnect not detected")
        except RobotdConnectionError as error: detected = time.monotonic_ns(); observed_error = repr(error)
        restart_robotd(args); safe_at, state, stopped, gate_rejection = reconnect_and_stop(session); recovered = session.recover(old)
        raw.append({"fault": "ipc_disconnect", "injected_point": "active robotd peer", "pid": pid, "observed_read_exception": observed_error, "fresh_stop_gate_rejection": gate_rejection})
        records.append(make_fault_record(fault="ipc_disconnect", injected_at_ns=injected, detected_at_ns=detected,
            safe_command_at_ns=safe_at, motion_stopped_at_ns=stopped, recovery_at_ns=recovered, state_evidence=state))

        # The active publisher is redirected to an absent endpoint, not a side probe.
        old = session.motion(); injected = time.monotonic_ns(); real_socket = session.client.socket_path
        refused_path = args.runtime_dir / "refused-p6-06.sock"
        refused_path.unlink(missing_ok=True)
        tombstone = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        tombstone.bind(str(refused_path)); tombstone.close()
        session.client.disconnect(); session.client.socket_path = str(refused_path)
        try: session.client.connect(); raise AssertionError("connection unexpectedly accepted")
        except RobotdConnectionError as error:
            if "Errno 111" not in str(error) and "refused" not in str(error).lower():
                raise AssertionError(f"expected actual connection refusal, got {error}") from error
            detected = time.monotonic_ns(); observed_error = repr(error)
        finally:
            refused_path.unlink(missing_ok=True)
        session.client.socket_path = real_socket
        safe_at, state, stopped, gate_rejection = reconnect_and_stop(session); recovered = session.recover(old)
        raw.append({"fault": "connection_refused", "injected_point": "active publisher endpoint", "observed_connect_exception": observed_error, "fresh_stop_gate_rejection": gate_rejection})
        records.append(make_fault_record(fault="connection_refused", injected_at_ns=injected, detected_at_ns=detected,
            safe_command_at_ns=safe_at, motion_stopped_at_ns=stopped, recovery_at_ns=recovered, state_evidence=state))

        # SIGSTOP is scoped to the verified robotd PID and causes an actual bounded read timeout.
        old = session.motion(); injected = time.monotonic_ns(); pid = verified_pid(args.pid_file, args.robotd, args.socket); os.kill(pid, signal.SIGSTOP)
        try:
            try: session.client.health(); raise AssertionError("read timeout not detected")
            except RobotdTimeoutError as error: detected = time.monotonic_ns(); observed_error = repr(error)
        finally: os.kill(pid, signal.SIGCONT)
        safe_at, state, stopped, gate_rejection = reconnect_and_stop(session); recovered = session.recover(old)
        raw.append({"fault": "read_timeout", "injected_point": "active robotd SIGSTOP", "observed_read_exception": observed_error, "fresh_stop_gate_rejection": gate_rejection})
        records.append(make_fault_record(fault="read_timeout", injected_at_ns=injected, detected_at_ns=detected,
            safe_command_at_ns=safe_at, motion_stopped_at_ns=stopped, recovery_at_ns=recovered, state_evidence=state))

        # Write failure: terminate the peer, then observe the active publisher's write.
        old = session.motion(); injected = time.monotonic_ns(); pid = kill_current()
        try: session.adapter.send(session.output(mode="missing")); raise AssertionError("write failure not detected")
        except RobotdConnectionError as error: detected = time.monotonic_ns(); observed_error = repr(error)
        restart_robotd(args); safe_at, state, stopped, gate_rejection = reconnect_and_stop(session); recovered = session.recover(old)
        raw.append({"fault": "write_failure", "injected_point": "active publisher send after peer exit", "pid": pid, "observed_write_exception": observed_error, "fresh_stop_gate_rejection": gate_rejection})
        records.append(make_fault_record(fault="write_failure", injected_at_ns=injected, detected_at_ns=detected,
            safe_command_at_ns=safe_at, motion_stopped_at_ns=stopped, recovery_at_ns=recovered, state_evidence=state))

        # Local active socket close is distinct from peer loss and connect refusal.
        old = session.motion(); injected = time.monotonic_ns(); session.client.disconnect()
        try: session.adapter.send(session.output(mode="missing")); raise AssertionError("closed socket publish not detected")
        except RobotdConnectionError as error: detected = time.monotonic_ns(); observed_error = repr(error)
        safe_at, state, stopped, gate_rejection = reconnect_and_stop(session); recovered = session.recover(old)
        raw.append({"fault": "socket_close", "injected_point": "active client socket close", "observed_publish_exception": observed_error, "fresh_stop_gate_rejection": gate_rejection})
        records.append(make_fault_record(fault="socket_close", injected_at_ns=injected, detected_at_ns=detected,
            safe_command_at_ns=safe_at, motion_stopped_at_ns=stopped, recovery_at_ns=recovered, state_evidence=state))

        # Restart lifecycle is tested without conflating it with the failed write.
        old = session.motion(); injected = time.monotonic_ns(); before_pid = kill_current(); after_pid = restart_robotd(args)
        session.client.reconnect(); session.client.enable(True)
        gate_rejection = session.assert_fresh_stop_gate()
        try: session.adapter.send(old); raise AssertionError("old command crossed robotd restart")
        except MotionAdapterError as error: detected = time.monotonic_ns(); observed_error = repr(error)
        stop = session.output(mode="missing"); session.adapter.send(stop); safe_at = time.monotonic_ns(); state = session.safe_state(); stopped = time.monotonic_ns(); recovered = session.recover(old)
        raw.append({"fault": "robotd_restart", "injected_point": "verified robotd lifecycle", "pid_before": before_pid, "pid_after": after_pid, "observed_replay_rejection": observed_error, "fresh_stop_gate_rejection": gate_rejection})
        records.append(make_fault_record(fault="robotd_restart", injected_at_ns=injected, detected_at_ns=detected,
            safe_command_at_ns=safe_at, motion_stopped_at_ns=stopped, recovery_at_ns=recovered, state_evidence=state))

        # Full official simulator lifecycle. Old adapter/session survives to prove generation gating.
        old = session.motion(); injected = time.monotonic_ns()
        env = dict(os.environ)
        env.update({
            "DUCK_SIM_STATE": str(args.runtime_dir),
            "DUCK_SIM_RL": str(args.microduck_rl),
            "DUCK_SIM_PORT": str(args.body_port),
            "DUCK_SIM_VIEWER": "0",
        })
        down = subprocess.run([str(args.duck_sim), "down"], env=env, timeout=30, check=False, capture_output=True, text=True)
        if down.returncode != 0: raise RuntimeError(f"duck-sim down failed: {down.stderr}")
        try: session.client.health(); raise AssertionError("simulator restart loss not detected")
        except (RobotdConnectionError, RobotdTimeoutError): detected = time.monotonic_ns()
        up = subprocess.run([str(args.duck_sim)], env=env, timeout=120, check=False, capture_output=True, text=True)
        if up.returncode != 0: raise RuntimeError(f"duck-sim up failed: {up.stderr}")
        safe_at, state, stopped, gate_rejection = reconnect_and_stop(session); recovered = session.recover(old)
        raw.append({"fault": "simulator_restart", "down_stdout": down.stdout[-1000:], "up_stdout": up.stdout[-1000:], "fresh_stop_gate_rejection": gate_rejection})
        records.append(make_fault_record(fault="simulator_restart", injected_at_ns=injected, detected_at_ns=detected,
            safe_command_at_ns=safe_at, motion_stopped_at_ns=stopped, recovery_at_ns=recovered, state_evidence=state))
    finally:
        try: session.adapter.send(session.output(mode="missing"))
        except Exception: pass
        session.close()

    if [record["fault"] for record in records] != list(REQUIRED_FAULTS):
        raise AssertionError("runtime did not execute canonical complete fault set")
    args.raw_artifact.parent.mkdir(parents=True, exist_ok=True)
    args.raw_artifact.write_text("".join(json.dumps(item, sort_keys=True, allow_nan=False) + "\n" for item in raw), encoding="utf-8")
    raw_hash = hashlib.sha256(args.raw_artifact.read_bytes()).hexdigest()
    identities = {
        "microduck_commit": git_head(args.microduck), "microduck_rl_commit": git_head(args.microduck_rl),
        "steering_yaw_sign": -1, "stop_transport": "robot_stop",
        "perception_ttl_ms": 100, "neural_ttl_ms": 100, "behavior_ttl_ms": 100,
        "robotd_interface": "official JSON-RPC high-level intent",
        "fixture_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    matrix = build_fault_matrix(
        execution_target="Thor", source_head=args.source_head, identities=identities,
        records=records, artifact={"path": str(args.raw_artifact), "sha256": raw_hash, "record_count": len(raw)},
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_fault_matrix(args.output, matrix)
    print(json.dumps(matrix, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
