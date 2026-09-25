"""Read-only Thor graph-v2 replay of P8-R2 RGB-derived sensory and DN paths.

This is an internal development recertification. It never contacts robotd and
cannot count as a P8-02 closed-loop trial.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import socket
import subprocess

from microduck_connectome.graph import ConnectomeGraph
from microduck_connectome.looming_scenario import (
    evaluator_truth, load_config, make_trial, pixels_sha256, render_pixels,
)
from microduck_connectome.watchdog import ControllerWatchdog
from scripts.p6_telemetry_runtime_fixture import FullChain


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = Path("config/p8_r2_rgb_resolution_dev_v1.json")
POSE = {"x_m": 0.0, "y_m": 0.0, "heading_rad": 0.0, "trunk_z_m": 0.125}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def load_frozen() -> tuple[dict, dict, dict, ConnectomeGraph]:
    if not socket.gethostname().startswith("jetsonthor") or platform.python_version_tuple()[:2] != ("3", "12"):
        raise RuntimeError("P8-R2 graph recertification requires Thor Python 3.12")
    if git("status", "--porcelain").strip():
        raise RuntimeError("P8-R2 requires a clean committed checkout")
    if (ROOT / PROTOCOL).read_bytes() != git("show", f"HEAD:{PROTOCOL.as_posix()}"):
        raise RuntimeError("P8-R2 protocol differs from committed bytes")
    protocol = json.loads((ROOT / PROTOCOL).read_text(encoding="utf-8"))
    if protocol["status"] != "FROZEN_DEVELOPMENT_ONLY" or protocol["implementation_commit"] is None:
        raise RuntimeError("P8-R2 development protocol is not frozen")
    expected_runs = [
        (pair["seed"], pair["arm_elapsed_s"], label)
        for pair in protocol["matched_pair_order"] for label in pair["run_order"]
    ]
    actual_runs = [
        (row["seed"], row["arm_elapsed_s"], row["representation"])
        for row in protocol["ordered_official_runs"]
    ]
    if (expected_runs != actual_runs or len(actual_runs) != 6
            or any(set(pair["run_order"]) != {"baseline", "candidate"}
                   for pair in protocol["matched_pair_order"])
            or protocol["raw_manifest_schema"]["ordered_rows"] != 6):
        raise RuntimeError("P8-R2 ordered development matrix mismatch")
    reserved = set(range(880000, 880120)) | set(range(881000, 881024)) | set(range(882000, 882024)) | set(range(883000, 883010)) | set(range(880901, 880907))
    if {row["seed"] for row in protocol["ordered_official_runs"]} & reserved:
        raise RuntimeError("P8-R2 development seed overlaps prior or final ranges")
    if subprocess.run(
        ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", protocol["implementation_commit"], "HEAD"],
        check=False,
    ).returncode:
        raise RuntimeError("P8-R2 implementation commit is not an ancestor")
    baseline = load_config(ROOT / protocol["scenario_baseline"]["path"])
    candidate = load_config(ROOT / protocol["scenario_candidate"]["path"])
    for label, config in (("baseline", baseline), ("candidate", candidate)):
        spec = protocol[f"scenario_{label}"]
        if (config["schema_version"], config["image_width_px"], config["image_height_px"]) != (
            spec["schema_version"], spec["image_width_px"], spec["image_height_px"]
        ):
            raise RuntimeError(f"{label} scenario version/resolution mismatch")
        if sha(ROOT / spec["path"]) != spec["git_blob_sha256"]:
            raise RuntimeError(f"{label} scenario byte hash mismatch")
    for key in baseline:
        if key not in ("schema_version", "image_width_px", "image_height_px") and baseline[key] != candidate[key]:
            raise RuntimeError(f"physical geometry or fixture changed: {key}")
    frozen_configs = {
        "neural_model": "neural_model_v1.json",
        "sensory_mapping": "sensory_mapping_v1.json",
        "dn_readout": "dn_readout_v1.json",
        "escape_decoder": "escape_decoder_v1.json",
        "safety_envelope": "safety_envelope_v1.json",
        "watchdog": "watchdog_v1.json",
        "motion_adapter": "motion_adapter_v1.json",
        "scheduler": "scheduler_v1.json",
    }
    if set(protocol["config_sha256"]) != set(frozen_configs):
        raise RuntimeError("P8-R2 controller config identity set mismatch")
    for name, filename in frozen_configs.items():
        if sha(ROOT / "config" / filename) != protocol["config_sha256"][name]:
            raise RuntimeError(f"P8-R2 {name} config bytes changed")
    manifest = json.loads((ROOT / "data/manifests/controller-graph-v2.json").read_text(encoding="utf-8"))
    if (manifest["graph_sha256"] != protocol["graph_sha256"]
            or manifest["dataset"] != protocol["dataset"]):
        raise RuntimeError("graph-v2 identity mismatch")
    artifact = Path(manifest["thor_artifact"])
    if sha(artifact) != protocol["graph_sha256"]:
        raise RuntimeError("graph-v2 artifact byte mismatch")
    return protocol, baseline, candidate, ConnectomeGraph.from_cache(artifact.parent, protocol["graph_sha256"])


def replay(graph, config, *, seed: int, arm_s: float, duration_ms: int, motion: str, label: str) -> dict:
    trial = make_trial(config, trial_id=f"p8-r2-{label}-{motion}-{seed}", seed=seed,
                       motion=motion, initial_pose=POSE)
    chain = FullChain(ROOT, graph)
    watchdog = ControllerWatchdog(ROOT / "config/watchdog_v1.json")
    frames = []
    steps = []
    current = None
    first_positive = None
    for index in range(math.ceil(duration_ms / 20)):
        now_ns = (index + 1) * 20_000_000
        elapsed = arm_s + index * 0.02
        if index % 2 == 0:
            pixels = render_pixels(config, trial, pose=POSE, elapsed_s=elapsed)
            current = chain.pipeline.process(
                pixels, camera_timestamp_ns=now_ns, camera_frame_id=index // 2 + 1,
                tof_left_mm=config["tof_mm"], tof_center_mm=config["tof_mm"],
                tof_right_mm=config["tof_mm"], tof_timestamp_ns=now_ns,
                tof_frame_id=index // 2 + 1, now_ns=now_ns,
            )
            truth = evaluator_truth(config, trial, pose=POSE, elapsed_s=elapsed)
            row = {
                "step": index + 1, "timestamp_ns": now_ns, "frame_id": current["frame_id"],
                "pixel_sha256": pixels_sha256(pixels),
                "red_pixel_count": sum(pixel == (255, 0, 0) for line in pixels for pixel in line),
                "target_area": current["target_area"], "looming": current["looming"],
                "evaluator_center_distance_m": truth["center_distance_m"],
                "evaluator_boundary_margin_m": truth["distance_to_boundary_m"],
            }
            frames.append(row)
            if first_positive is None and row["looming"] > 0:
                first_positive = current
        update = chain.neural(current, now_ns)
        trace = update.trace
        watchdog.observe_neural(update.readout)
        watchdog.observe_behavior(update.behavior_intent)
        output = watchdog.tick(now_ns=now_ns, output_sequence=index + 1)
        truth = evaluator_truth(config, trial, pose=POSE, elapsed_s=elapsed)
        channels = trace["stimulus_channels"]
        readout = trace["dn_readout"]
        stop = bool(
            readout["runtime_healthy"] and readout["escape"] >= 0.5
            and trace["pre_safety_intent"]["stop"]
            and trace["safety_result"]["intent"]["stop"]
            and output["watchdog_state"] == "healthy" and output["intent"]["stop"]
        )
        steps.append({
            "step": index + 1, "timestamp_ns": now_ns,
            "frame_id": current["frame_id"], "frame_valid": current["valid"],
            "runtime_step": trace["male_cns"]["runtime_step"],
            "runtime_healthy": trace["male_cns"]["healthy"],
            "lplc2_left": channels["lplc2_left"],
            "lplc2_right": channels["lplc2_right"],
            "dn_escape": readout["escape"], "neural_stop": stop,
            "watchdog_state": output["watchdog_state"],
            "evaluator_boundary_margin_m": truth["distance_to_boundary_m"],
        })
    if first_positive is not None:
        assert chain.mapper.build_external(first_positive, now_ns=first_positive["timestamp_ns"])
        assert chain.mapper.build_external(first_positive, now_ns=first_positive["timestamp_ns"] + 100_000_001) == {}
    invalid_ns = steps[-1]["timestamp_ns"] + 20_000_000
    invalid = chain.pipeline.process(
        (), camera_timestamp_ns=invalid_ns, camera_frame_id=len(frames) + 1,
        tof_left_mm=config["tof_mm"], tof_center_mm=config["tof_mm"],
        tof_right_mm=config["tof_mm"], tof_timestamp_ns=invalid_ns,
        tof_frame_id=len(frames) + 1, now_ns=invalid_ns, camera_source_valid=False,
    )
    if invalid["valid"] or chain.mapper.build_external(invalid, now_ns=invalid_ns):
        raise RuntimeError("invalid RGB did not map to neutral external input")
    tof_loss_ns = invalid_ns + 20_000_000
    tof_loss_pixels = render_pixels(config, trial, pose=POSE, elapsed_s=arm_s + duration_ms / 1000)
    tof_loss = chain.pipeline.process(
        tof_loss_pixels, camera_timestamp_ns=tof_loss_ns,
        camera_frame_id=len(frames) + 2,
        tof_left_mm=config["tof_mm"], tof_center_mm=config["tof_mm"],
        tof_right_mm=config["tof_mm"], tof_timestamp_ns=tof_loss_ns,
        tof_frame_id=len(frames) + 2, now_ns=tof_loss_ns, tof_source_valid=False,
    )
    if tof_loss["valid"] or chain.mapper.build_external(tof_loss, now_ns=tof_loss_ns):
        raise RuntimeError("invalid ToF did not map to neutral external input")
    if motion != "approaching" and (any(f["looming"] > 0 for f in frames)
                                     or any(s["neural_stop"] for s in steps)):
        raise RuntimeError(f"{motion} fixed-pose control produced a healthy neural escape")
    return {
        "label": label, "motion": motion, "seed": seed, "arm_elapsed_s": arm_s,
        "frame_count": len(frames), "neural_step_count": len(steps),
        "positive_looming_frames": sum(f["looming"] > 0 for f in frames),
        "positive_lplc2_steps": sum(s["lplc2_left"] > 0 for s in steps),
        "peak_lplc2": max(s["lplc2_left"] for s in steps),
        "peak_dn_escape": max(s["dn_escape"] for s in steps),
        "first_healthy_neural_stop": next((s for s in steps if s["neural_stop"]), None),
        "invalid_rgb_neutral": True, "invalid_tof_neutral": True,
        "stale_rgb_neutral": first_positive is not None,
        "frames": frames, "steps": steps,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    protocol, baseline, candidate, graph = load_frozen()
    cases = []
    for pair in protocol["matched_pair_order"]:
        for label in pair["run_order"]:
            cases.append(replay(graph, baseline if label == "baseline" else candidate,
                                seed=pair["seed"], arm_s=pair["arm_elapsed_s"],
                                duration_ms=pair["maximum_neural_observation_ms"],
                                motion="approaching", label=label))
    for motion, seed in protocol["negative_control_seeds_offline_only"].items():
        cases.append(replay(graph, candidate, seed=seed, arm_s=2.0,
                            duration_ms=1000, motion=motion, label="candidate"))
    report = {
        "schema_version": "p8-r2-rgb-path-recertification-v1",
        "scope": "internal RGB-to-graph-v2-to-DN path; no official body movement or transport",
        "source_head": git("rev-parse", "HEAD").decode().strip(),
        "protocol_sha256": sha(ROOT / PROTOCOL),
        "baseline_scenario_sha256": sha(ROOT / protocol["scenario_baseline"]["path"]),
        "candidate_scenario_sha256": sha(ROOT / protocol["scenario_candidate"]["path"]),
        "graph_sha256": protocol["graph_sha256"],
        "dataset": protocol["dataset"],
        "config_sha256": protocol["config_sha256"],
        "python_version": platform.python_version(),
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n",
                           encoding="utf-8", newline="\n")
    print(json.dumps({"cases": len(cases), "candidate_early_internal_stops": sum(
        c["label"] == "candidate" and c["motion"] == "approaching"
        and c["first_healthy_neural_stop"] is not None
        and c["first_healthy_neural_stop"]["evaluator_boundary_margin_m"] > 0 for c in cases),
        "negative_controls_no_stop": all(c["first_healthy_neural_stop"] is None
                                         for c in cases if c["motion"] != "approaching")}, sort_keys=True))


if __name__ == "__main__":
    main()
