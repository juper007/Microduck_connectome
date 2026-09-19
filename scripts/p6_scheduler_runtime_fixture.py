"""Measure the full P4/P3/P5 scheduler against official robotd on Thor."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path
import re
import socket
import subprocess
import time

from microduck_connectome.dn_aggregator import DNActivityAggregator, load_dn_readout_config
from microduck_connectome.escape_decoder import EscapeDecoder, load_escape_decoder_config
from microduck_connectome.graph import ConnectomeGraph
from microduck_connectome.motion_adapter import RobotMotionAdapter
from microduck_connectome.perception_compositor import PerceptionPipeline
from microduck_connectome.robotd_client import RobotdClient
from microduck_connectome.safety_clamp import SafetyClamp, load_safety_envelope
from microduck_connectome.scheduler import ClosedLoopScheduler, NeuralUpdate
from microduck_connectome.sensory_mapping import SensoryMapper, load_sensory_mapping_config
from microduck_connectome.sparse_runtime import SparseNeuralRuntime
from microduck_connectome.steering_decoder import SteeringDecoder, load_steering_decoder_config
from microduck_connectome.watchdog import ControllerWatchdog


def git_head(path: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(path), "rev-parse", "HEAD"], text=True
    ).strip()


def missed_ticks(health) -> int:
    """Extract the upstream missed-loop counter without guessing absence as zero."""
    candidates = (health.get("loop"), health.get("control_loop"))
    for candidate in candidates:
        if isinstance(candidate, dict):
            for name in ("missed", "missed_ticks"):
                value = candidate.get(name)
                if type(value) is int:
                    return value
    raise RuntimeError("robot.health did not expose a missed-loop counter")


class FullChain:
    def __init__(self, root: Path, graph: ConnectomeGraph):
        self.pipeline = PerceptionPipeline()
        sensory_config = load_sensory_mapping_config(
            root / "config" / "sensory_mapping_v1.json"
        )
        sensory_ids = tuple(sorted(
            body_id
            for spec in sensory_config["populations"].values()
            for body_id in spec["body_ids"]
        ))
        self.mapper = SensoryMapper(
            sensory_ids, sensory_config,
        )
        self.runtime = SparseNeuralRuntime(
            graph,
            json.loads((root / "config" / "neural_model_v1.json").read_text()),
        )
        dn_config = load_dn_readout_config(root / "config" / "dn_readout_v1.json")
        self.dn_ids = tuple(sorted(
            body_id
            for spec in dn_config["populations"].values()
            for body_id in spec["body_ids"]
        ))
        self.aggregator = DNActivityAggregator(self.dn_ids, dn_config)
        self.runtime_index = {body_id: index for index, body_id in enumerate(graph.body_ids)}
        self.graph_sensory_count = len(set(sensory_ids) & set(graph.body_ids))
        self.graph_dn_count = len(set(self.dn_ids) & set(graph.body_ids))
        self.steering = SteeringDecoder(
            load_steering_decoder_config(root / "config" / "steering_decoder_v1.json")
        )
        self.escape = EscapeDecoder(
            load_escape_decoder_config(root / "config" / "escape_decoder_v1.json")
        )
        self.safety = SafetyClamp(
            load_safety_envelope(root / "config" / "safety_envelope_v1.json")
        )
        self.frame_id = 0
        self.neural_sequence = 0

    def perception(self, now_ns: int):
        self.frame_id += 1
        # Bounded deterministic visual fixture: left, center, right, neutral.
        black = (0, 0, 0)
        red = (255, 0, 0)
        pixels = (
            ((red, black, black),),
            ((black, red, black),),
            ((black, black, red),),
            ((black, black, black),),
        )[(self.frame_id // 25) % 4]
        return self.pipeline.process(
            pixels,
            camera_timestamp_ns=now_ns,
            camera_frame_id=self.frame_id,
            tof_left_mm=500,
            tof_center_mm=500,
            tof_right_mm=500,
            tof_timestamp_ns=now_ns,
            tof_frame_id=self.frame_id,
            now_ns=now_ns,
        )

    def neural(self, frame, now_ns: int):
        self.neural_sequence += 1
        mapped = {} if frame is None else self.mapper.build_external(frame, now_ns=now_ns)
        # The frozen pathway graph can omit evidence-independent sensory/escape
        # populations. Never invent edges or neurons: absent configured IDs are
        # neutral and the coverage counts are recorded in evidence.
        external = {body_id: value for body_id, value in mapped.items()
                    if body_id in self.runtime_index}
        snapshot = self.runtime.step(external)
        projected_spikes = tuple(
            snapshot["spikes"][self.runtime_index[body_id]]
            if body_id in self.runtime_index else False
            for body_id in self.dn_ids
        )
        readout = self.aggregator.update(
            projected_spikes,
            timestamp_ns=now_ns,
            sequence=self.neural_sequence,
            runtime_healthy=snapshot["healthy"],
        )
        decoded = self.escape.apply(readout, self.steering.decode(readout))
        safe = self.safety.apply(
            decoded, now_ns=now_ns, fallback_sequence=self.neural_sequence
        )
        return NeuralUpdate(readout, safe["intent"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--graph-cache", type=Path, required=True)
    parser.add_argument("--graph-key", required=True)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--duration-s", type=float, default=30.0)
    parser.add_argument("--microduck", type=Path, required=True)
    parser.add_argument("--microduck-rl", type=Path, required=True)
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if re.fullmatch(r"[0-9a-f]{40}", args.source_head) is None:
        raise ValueError("source-head must be a full lowercase Git SHA")
    if platform.python_version_tuple()[:2] != ("3", "12"):
        raise RuntimeError("Thor runtime evidence requires Python 3.12")
    hostname = socket.gethostname()
    if not hostname.startswith("jetsonthor"):
        raise RuntimeError(f"runtime authority must be Thor, got {hostname!r}")

    graph = ConnectomeGraph.from_cache(args.graph_cache, args.graph_key)
    chain = FullChain(args.root, graph)
    client = RobotdClient(str(args.socket), timeout_s=2.0)
    client.connect()
    client.enable(True)
    health_before = client.health()
    adapter = RobotMotionAdapter(client, args.root / "config" / "motion_adapter_v1.json")
    watchdog = ControllerWatchdog(args.root / "config" / "watchdog_v1.json")
    scheduler = ClosedLoopScheduler(
        config=args.root / "config" / "scheduler_v1.json",
        watchdog=watchdog,
        perception_step=chain.perception,
        neural_step=chain.neural,
        publisher=adapter.send,
    )
    started_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    summary = scheduler.run(args.duration_s)
    ended_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    health_after = client.health()
    state_after = client.state(hz=50)
    client.close()

    before_missed = missed_ticks(health_before)
    after_missed = missed_ticks(health_after)
    result = "PASS" if (
        summary["perception_hz"] >= 25.0
        and summary["neural_hz"] >= 20.0
        and summary["watchdog_hz"] >= 48.0
        and summary["publish_hz"] >= 48.0
        and summary["scheduler_exceptions"] == 0
        and after_missed == before_missed
    ) else "FAIL"
    report = {
        "schema_version": "p6-04-scheduler-runtime-v1",
        "execution_target": "Thor",
        "hostname": hostname,
        "started_utc": started_utc,
        "ended_utc": ended_utc,
        "source_head": args.source_head,
        "microduck_commit": git_head(args.microduck),
        "microduck_rl_commit": git_head(args.microduck_rl),
        "graph_cache_key": graph.root_key,
        "graph_node_count": len(graph.body_ids),
        "configured_sensory_ids_in_graph": chain.graph_sensory_count,
        "configured_dn_ids_in_graph": chain.graph_dn_count,
        "python_version": platform.python_version(),
        "fixture_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        **summary,
        "period_ms_p50": summary["watchdog_period_ms_p50"],
        "period_ms_p95": summary["watchdog_period_ms_p95"],
        "period_ms_p99": summary["watchdog_period_ms_p99"],
        "jitter_ms_p95": summary["watchdog_jitter_ms_p95"],
        "robotd_missed_ticks_before": before_missed,
        "robotd_missed_ticks_after": after_missed,
        "robot_state_policy": state_after.get("policy"),
        "steering_yaw_sign": -1,
        "stop_transport": "robot_stop",
        "result": result,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    if result != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
