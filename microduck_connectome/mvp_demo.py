"""Minimal MaleCNS -> MicroDuck motion demo.

This is an iteration/demo path, not a replacement for P8 scientific validation.
It reuses the frozen P3-P6 controller components and the official robotd boundary.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import socket
import time

from .dn_aggregator import DNActivityAggregator, load_dn_readout_config
from .escape_decoder import EscapeDecoder, load_escape_decoder_config
from .graph import ConnectomeGraph
from .motion_adapter import RobotMotionAdapter
from .perception_compositor import PerceptionPipeline
from .robotd_client import RobotdClient
from .safety_clamp import SafetyClamp, load_safety_envelope
from .scheduler import ClosedLoopScheduler, NeuralUpdate
from .sensory_mapping import SensoryMapper, load_sensory_mapping_config
from .sparse_runtime import SparseNeuralRuntime
from .steering_decoder import SteeringDecoder, load_steering_decoder_config
from .watchdog import ControllerWatchdog

SCENARIOS = ("neutral", "left", "right", "center", "stop")
FRAMES_PER_SCENARIO = 30
DEFAULT_DURATION_S = 6.4
DEFAULT_SOCKET = "/run/robotd.sock"
TURN_EPSILON = 0.01


class MvpChain:
    """Small vertical slice over the existing MaleCNS controller components."""

    def __init__(self, root: Path, graph: ConnectomeGraph):
        self.pipeline = PerceptionPipeline()
        sensory_config = load_sensory_mapping_config(
            root / "config" / "sensory_mapping_v1.json"
        )
        sensory_ids = tuple(
            sorted(
                body_id
                for spec in sensory_config["populations"].values()
                for body_id in spec["body_ids"]
            )
        )
        self.mapper = SensoryMapper(sensory_ids, sensory_config)
        self.runtime = SparseNeuralRuntime(
            graph,
            json.loads((root / "config" / "neural_model_v1.json").read_text()),
        )
        dn_config = load_dn_readout_config(root / "config" / "dn_readout_v1.json")
        self.dn_ids = tuple(
            sorted(
                body_id
                for spec in dn_config["populations"].values()
                for body_id in spec["body_ids"]
            )
        )
        self.aggregator = DNActivityAggregator(self.dn_ids, dn_config)
        self.runtime_index = {
            body_id: index for index, body_id in enumerate(graph.body_ids)
        }
        self.steering = SteeringDecoder(
            load_steering_decoder_config(
                root / "config" / "steering_decoder_v1.json"
            )
        )
        self.escape = EscapeDecoder(
            load_escape_decoder_config(root / "config" / "escape_decoder_v1.json")
        )
        self.safety = SafetyClamp(
            load_safety_envelope(root / "config" / "safety_envelope_v1.json")
        )
        self.frame_id = 0
        self.neural_sequence = 0
        self.scenario = "neutral"

    @staticmethod
    def _pixels(scenario: str, phase: int):
        black, red = (0, 0, 0), (255, 0, 0)
        if scenario == "left":
            return ((red, black, black),)
        if scenario == "right":
            return ((black, black, red),)
        if scenario == "center":
            return ((black, red, black),)
        if scenario == "stop":
            # Alternating apparent area produces a simple looming stimulus while
            # remaining entirely inside the existing perception path.
            return ((red, red, red),) if phase % 2 else ((black, red, black),)
        return ((black, black, black),)

    def perception(self, now_ns: int):
        self.frame_id += 1
        segment = min((self.frame_id - 1) // FRAMES_PER_SCENARIO, len(SCENARIOS) - 1)
        self.scenario = SCENARIOS[segment]
        pixels = self._pixels(self.scenario, self.frame_id)
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
        if frame is None:
            return None
        channels = self.mapper.map_channels(frame, now_ns=now_ns)
        mapped = self.mapper.build_external(frame, now_ns=now_ns)
        external = {
            body_id: value
            for body_id, value in mapped.items()
            if body_id in self.runtime_index
        }
        snapshot = self.runtime.step(external)
        projected_spikes = tuple(
            snapshot["spikes"][self.runtime_index[body_id]]
            if body_id in self.runtime_index
            else False
            for body_id in self.dn_ids
        )
        readout = self.aggregator.update(
            projected_spikes,
            timestamp_ns=now_ns,
            sequence=self.neural_sequence,
            runtime_healthy=snapshot["healthy"],
        )
        pre_safety = self.escape.apply(readout, self.steering.decode(readout))
        safe = self.safety.apply(
            pre_safety,
            now_ns=now_ns,
            fallback_sequence=self.neural_sequence,
        )
        trace = {
            "perception_frame": dict(frame),
            "stimulus_channels": channels,
            "male_cns": {
                "runtime_step": self.neural_sequence,
                "healthy": snapshot["healthy"],
                "spike_count": sum(bool(value) for value in snapshot["spikes"]),
                "external_input_count": len(external),
                "scenario_fixture": self.scenario,
            },
            "dn_readout": readout,
            "pre_safety_intent": pre_safety,
            "safety_result": safe,
        }
        return NeuralUpdate(readout, safe["intent"], trace)


class DemoObserver:
    """Print only meaningful transitions and keep lightweight demo checks."""

    def __init__(self):
        self.left_yaw: list[float] = []
        self.right_yaw: list[float] = []
        self.escape_seen = False
        self._scenario = None
        self._reported_turn: set[str] = set()
        self._reported_escape = False

    def __call__(self, update, output, transport_result):
        if update is None or update.trace is None:
            return
        trace = update.trace
        scenario = trace["male_cns"]["scenario_fixture"]
        readout = trace["dn_readout"]
        pre_safety = trace["pre_safety_intent"]
        intent = output["intent"]

        if scenario == "left" and not intent["stop"]:
            self.left_yaw.append(float(intent["vyaw"]))
        elif scenario == "right" and not intent["stop"]:
            self.right_yaw.append(float(intent["vyaw"]))

        neural_escape = (
            scenario == "stop"
            and bool(pre_safety["stop"])
            and float(readout["escape"]) >= 0.5
        )
        self.escape_seen = self.escape_seen or neural_escape

        if scenario != self._scenario:
            self._scenario = scenario
            print(
                json.dumps(
                    {
                        "event": "scenario",
                        "scenario": scenario,
                        "dn": {
                            "left": round(float(readout["steering_left"]), 3),
                            "right": round(float(readout["steering_right"]), 3),
                            "escape": round(float(readout["escape"]), 3),
                        },
                    },
                    sort_keys=True,
                ),
                flush=True,
            )

        if (
            scenario in ("left", "right")
            and scenario not in self._reported_turn
            and not intent["stop"]
            and abs(float(intent["vyaw"])) >= TURN_EPSILON
        ):
            self._reported_turn.add(scenario)
            print(
                json.dumps(
                    {
                        "event": "turn",
                        "scenario": scenario,
                        "vyaw": round(float(intent["vyaw"]), 3),
                        "transport": transport_result,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )

        if neural_escape and not self._reported_escape:
            self._reported_escape = True
            print(
                json.dumps(
                    {
                        "event": "neural_escape",
                        "escape": round(float(readout["escape"]), 3),
                        "robot_stop": bool(intent["stop"]),
                        "transport": transport_result,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )

    @staticmethod
    def _peak(values: list[float]) -> float:
        return max(values, key=abs, default=0.0)

    def summary(self) -> dict:
        left_peak = self._peak(self.left_yaw)
        right_peak = self._peak(self.right_yaw)
        opposite_turns = (
            abs(left_peak) >= TURN_EPSILON
            and abs(right_peak) >= TURN_EPSILON
            and left_peak * right_peak < 0.0
        )
        complete = opposite_turns and self.escape_seen
        return {
            "demo_result": "PASS" if complete else "INCOMPLETE",
            "left_peak_vyaw": left_peak,
            "right_peak_vyaw": right_peak,
            "opposite_left_right_turns": opposite_turns,
            "connectome_escape_stop_seen": self.escape_seen,
            "scope": "interactive MVP only; not P8 scientific evidence",
        }


def resolve_graph(root: Path, graph_cache: Path | None, graph_key: str | None):
    manifest = json.loads(
        (root / "data" / "manifests" / "controller-graph-v2.json").read_text(
            encoding="utf-8"
        )
    )
    key = graph_key or manifest["graph_sha256"]
    cache = graph_cache or Path(manifest["thor_artifact"]).parent
    artifact = cache / f"{key}.json"
    if not artifact.is_file():
        raise FileNotFoundError(
            f"MaleCNS graph artifact not found: {artifact}; "
            "override with --graph-cache/--graph-key if needed"
        )
    return cache, key


def build_parser() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Run the minimal MaleCNS -> MicroDuck MuJoCo motion demo."
    )
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--graph-cache", type=Path)
    parser.add_argument("--graph-key")
    parser.add_argument("--socket", default=DEFAULT_SOCKET)
    parser.add_argument("--duration-s", type=float, default=DEFAULT_DURATION_S)
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="load the real MaleCNS graph/config chain without commanding robotd",
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    graph_cache, graph_key = resolve_graph(root, args.graph_cache, args.graph_key)
    graph = ConnectomeGraph.from_cache(graph_cache, graph_key)
    chain = MvpChain(root, graph)

    if args.check_only:
        print(
            json.dumps(
                {
                    "check": "PASS",
                    "graph_key": graph.root_key,
                    "node_count": len(graph.body_ids),
                    "scenarios": list(SCENARIOS),
                },
                sort_keys=True,
            )
        )
        return 0

    if not socket.gethostname().startswith("jetsonthor"):
        raise RuntimeError(
            "motion demo must run on Jetson Thor; use --check-only for config validation"
        )
    if args.duration_s < 6.2:
        raise ValueError("duration-s must be >= 6.2 to reach all MVP scenarios")

    client = RobotdClient(args.socket, timeout_s=2.0)
    observer = DemoObserver()
    started = time.monotonic()
    try:
        client.connect()
        health = client.health()
        if not health["healthy"]:
            raise RuntimeError(f"robotd is not healthy: {health!r}")
        client.enable(True)
        adapter = RobotMotionAdapter(
            client, root / "config" / "motion_adapter_v1.json"
        )
        scheduler = ClosedLoopScheduler(
            config=root / "config" / "scheduler_v1.json",
            watchdog=ControllerWatchdog(root / "config" / "watchdog_v1.json"),
            perception_step=chain.perception,
            neural_step=chain.neural,
            publisher=adapter.send,
            control_observer=observer,
        )
        scheduler_summary = scheduler.run(args.duration_s)
    finally:
        try:
            if client.status.connected:
                client.stop()
        finally:
            client.close()

    summary = observer.summary()
    summary["elapsed_s"] = round(time.monotonic() - started, 3)
    summary["graph_key"] = graph.root_key
    summary["scheduler_exceptions"] = scheduler_summary["scheduler_exceptions"]
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["demo_result"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
