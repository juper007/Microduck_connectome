"""P8-R3 V2.1 paired RGB representation screen; no robotd or final seeds.

Run against the pinned graph-v2 artifact on Thor. The output retains every
candidate, seed, resolution, motion, RGB frame, and 50 Hz neural step.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from microduck_connectome.graph import ConnectomeGraph
from microduck_connectome.fractional_rgb_v21 import FractionalRedTargetDetector, render_fractional_pixels
from microduck_connectome.looming_scenario import evaluator_truth, load_config, make_trial, pixels_sha256, render_pixels
from microduck_connectome.looming_v2 import LoomingEstimatorV2, LoomingV2Config
from microduck_connectome.watchdog import ControllerWatchdog
from scripts.p6_telemetry_runtime_fixture import FullChain


ROOT = Path(__file__).resolve().parents[1]
POSE = {"x_m": 0.0, "y_m": 0.0, "heading_rad": 0.0, "trunk_z_m": 0.125}
SEEDS = (885401, 885402, 885403)  # New V2.1 development seeds.
ARM_ELAPSED_S = (2.0, 2.6, 3.0)
RESOLUTIONS = ((65, 33), (129, 65))
MOTIONS = ("approaching", "static", "receding")
REPRESENTATIONS = ("binary", "fractional")
METHODS = {
    "A_log_area": LoomingV2Config(method="log_area", full_scale_rate_per_s=0.5),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_case(graph, scenario, *, representation, method, config, seed, arm_elapsed_s, motion):
    chain = FullChain(ROOT, graph)
    chain.pipeline.looming_estimator = LoomingEstimatorV2(config)
    if representation == "fractional":
        chain.pipeline.camera_detector = FractionalRedTargetDetector()
    renderer = render_fractional_pixels if representation == "fractional" else render_pixels
    watchdog = ControllerWatchdog(ROOT / "config/watchdog_v1.json")
    trial = make_trial(scenario, trial_id=f"p8-r3-{method}-{motion}-{seed}",
                       seed=seed, motion=motion, initial_pose=POSE)
    frames, steps = [], []
    current = None
    # Common elapsed 4.0 s end avoids entering the virtual sphere for late arms.
    # Observation lengths are 2.0, 1.4, and 1.0 s for the paired arm times.
    step_count = round((4.0 - arm_elapsed_s) * 50) + 1
    for index in range(step_count):
        now_ns = (index + 1) * 20_000_000
        elapsed_s = arm_elapsed_s + index * 0.02
        truth = evaluator_truth(scenario, trial, pose=POSE, elapsed_s=elapsed_s)
        if index % 5 == 0:
            pixels = renderer(scenario, trial, pose=POSE, elapsed_s=elapsed_s)
            current = chain.pipeline.process(
                pixels, camera_timestamp_ns=now_ns, camera_frame_id=index // 5 + 1,
                tof_left_mm=scenario["tof_mm"], tof_center_mm=scenario["tof_mm"],
                tof_right_mm=scenario["tof_mm"], tof_timestamp_ns=now_ns,
                tof_frame_id=index // 5 + 1, now_ns=now_ns,
            )
            frames.append({
                "elapsed_s": elapsed_s, "timestamp_ns": now_ns,
                "pixel_sha256": pixels_sha256(pixels),
                "target_area": current["target_area"], "target_x": current["target_x"],
                "confidence": current["confidence"], "valid": current["valid"],
                "looming": current["looming"],
                "distance_to_boundary_m": truth["distance_to_boundary_m"],
            })
        update = chain.neural(current, now_ns)
        trace = update.trace
        watchdog.observe_neural(update.readout)
        watchdog.observe_behavior(update.behavior_intent)
        output = watchdog.tick(now_ns=now_ns, output_sequence=index + 1)
        channels = trace["stimulus_channels"]
        readout = trace["dn_readout"]
        neural_stop = bool(
            readout["runtime_healthy"] and readout["escape"] >= 0.5
            and trace["pre_safety_intent"]["stop"]
            and trace["safety_result"]["intent"]["stop"]
            and output["watchdog_state"] == "healthy" and output["intent"]["stop"]
        )
        steps.append({
            "elapsed_s": elapsed_s, "timestamp_ns": now_ns,
            "frame_id": current["frame_id"],
            "lplc2_left": channels["lplc2_left"],
            "lplc2_right": channels["lplc2_right"],
            "dn_escape": readout["escape"],
            "runtime_healthy": readout["runtime_healthy"],
            "neural_stop": neural_stop,
            "watchdog_state": output["watchdog_state"],
            "distance_to_boundary_m": truth["distance_to_boundary_m"],
        })
    first_positive = next((row for row in frames if row["looming"] > 0), None)
    first_changed = next((row for row in frames[1:] if row["pixel_sha256"] != frames[0]["pixel_sha256"]), None)
    first_threshold = next((row for row in steps if row["dn_escape"] >= 0.5 and row["runtime_healthy"]), None)
    first_stop = next((row for row in steps if row["neural_stop"]), None)
    return {
        "representation": representation, "method": method, "seed": seed,
        "arm_elapsed_s": arm_elapsed_s, "motion": motion,
        "resolution": [scenario["image_width_px"], scenario["image_height_px"]],
        "first_changed_rgb": first_changed,
        "first_positive_looming": first_positive,
        "looming_peak": max(row["looming"] for row in frames),
        "positive_looming_frames": sum(row["looming"] > 0 for row in frames),
        "lplc2_peak": max(row["lplc2_left"] for row in steps),
        "positive_lplc2_steps": sum(row["lplc2_left"] > 0 for row in steps),
        "dn_peak": max(row["dn_escape"] for row in steps),
        "first_dn_threshold": first_threshold,
        "first_healthy_neural_stop": first_stop,
        "preboundary_stop": first_stop is not None and first_stop["distance_to_boundary_m"] > 0,
        "frames": frames, "steps": steps,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph-artifact", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest_path = ROOT / "data/manifests/controller-graph-v2.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    graph_path = args.graph_artifact or Path(manifest["thor_artifact"])
    if digest(graph_path) != manifest["graph_sha256"]:
        raise RuntimeError("graph-v2 artifact SHA256 mismatch")
    graph = ConnectomeGraph.from_cache(graph_path.parent, manifest["graph_sha256"])
    baseline = load_config(ROOT / "config/looming_scenario_v1.json")
    cases = []
    for method, config in METHODS.items():
        for representation in REPRESENTATIONS:
            for width, height in RESOLUTIONS:
                scenario = {**baseline, "image_width_px": width, "image_height_px": height}
                for motion in MOTIONS:
                    for seed, arm_elapsed_s in zip(SEEDS, ARM_ELAPSED_S):
                        cases.append(run_case(graph, scenario, representation=representation,
                                              method=method, config=config, seed=seed,
                                              arm_elapsed_s=arm_elapsed_s, motion=motion))
    report = {
        "schema_version": "p8-r3-v21-internal-development-v1",
        "scope": "paired binary/fractional synthetic RGB and graph-v2; no moving body or robotd",
        "development_only": True, "seeds": SEEDS, "arm_elapsed_s": ARM_ELAPSED_S,
        "representations": REPRESENTATIONS, "visual_hz": 10, "neural_hz": 50,
        "methods": {name: vars(config) for name, config in METHODS.items()},
        "graph_sha256": manifest["graph_sha256"],
        "scenario_sha256": digest(ROOT / "config/looming_scenario_v1.json"),
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n",
                           encoding="utf-8", newline="\n")
    print(json.dumps({"cases": len(cases), "approaching_preboundary_stops": sum(
        case["preboundary_stop"] for case in cases if case["motion"] == "approaching"),
        "control_stops": sum(case["first_healthy_neural_stop"] is not None for case in cases
                             if case["motion"] != "approaching")}, sort_keys=True))


if __name__ == "__main__":
    main()
