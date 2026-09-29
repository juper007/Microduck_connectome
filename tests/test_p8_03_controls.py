"""P8-03 raw decision and pose-relative fixture contract tests."""

from __future__ import annotations

import unittest
import hashlib
import json
import math
from pathlib import Path
import tempfile
from unittest.mock import patch

from microduck_connectome.fractional_rgb_v21 import render_fractional_pixels
from microduck_connectome.looming_scenario import load_config
from microduck_connectome.p8_03_geometry import relative_trial
from scripts.p8_03_score import audit_original_ledgers, manifest_check, score_raw, wilson_95
from scripts.p8_03_score import score_batch
from microduck_connectome.g8_r5d_metrics import first_sustained, pose_speeds
from scripts.p8_03_batch import recover_only
from scripts.p8_03_local_reference import settled_reference, verify_local_reference

LOCAL_CONFIG = json.loads((Path(__file__).parents[1] /
                           "config/p8_03_local_reference_v1.json").read_text())


class ControlGeometryTests(unittest.TestCase):
    def test_pose_relative_distance_and_rgb(self):
        config = load_config("config/looming_scenario_v1.json")
        pose = {"x_m": 1.2, "y_m": -0.3, "heading_rad": 0.4, "trunk_z_m": 0.3}
        for mode, elapsed, expected in (("static", 0.0, .85), ("static", 1.0, .85),
                                        ("receding", 0.0, .85), ("receding", 1.0, 1.05)):
            trial, distance = relative_trial(pose=pose, trial_id="S889200", ordinal=0,
                                             mode=mode, elapsed_after_arm_s=elapsed)
            self.assertAlmostEqual(distance, expected)
            self.assertEqual(len(render_fractional_pixels(config, trial, pose=pose, elapsed_s=0)), 33)
        moved = dict(pose, x_m=pose["x_m"] + .12)
        trial, distance = relative_trial(pose=moved, trial_id="S889200", ordinal=0,
                                         mode="static", elapsed_after_arm_s=1)
        self.assertAlmostEqual(distance, .85)
        self.assertAlmostEqual(trial.anchor_x_m - moved["x_m"],
                               .85 * math.cos(moved["heading_rad"]))



def clean_raw(stage="S"):
    start = 1_000_000_000
    rows = [{"kind": "arm", "timestamp_ns": start,
             "reset_id": "S889200" if stage == "S" else "R889300",
             "ordinal": 0 if stage == "S" else 0,
             "moving_confirmed_ns": start - 100_000_000,
             "precondition_displacement_m": .03, "precondition_applied_vx_mps": .06}]
    rows.append({"kind": "prearm_visual_anchor", "timestamp_ns": start - 1,
                 "distance_m": .85, "image_area": .01})
    rows.append({"kind": "robotd_health_before", "timestamp_ns": start - 3,
                 "healthy": True})
    rows.append({"kind": "local_reference", "timestamp_ns": start - 2,
                 "result": "PASS", "capture_ns": start - 300_000_000,
                 "reset_id": stage + ("889200" if stage == "S" else "889300"),
                 "reference": {"x_m": 0.0, "y_m": 0.0, "heading_rad": 0.0,
                               "trunk_z_m": .3}})
    for i in range(21):
        distance = .85 + (.01 * i if stage == "R" else 0)
        rows.append({"kind": "visual_frame", "timestamp_ns": start + i * 50_000_000,
                     "source_valid": True, "distance_m": distance,
                     "image_area": .01, "bearing_rad": 0.0,
                     "pose": {"x_m": .01 * i, "y_m": 0.0, "heading_rad": 0.0},
                     "virtual_center_x_m": .01 * i + distance,
                     "virtual_center_y_m": 0.0})
    for i in range(51):
        t = start + i * 20_000_000
        rows.extend(({"kind": "neural_step", "timestamp_ns": t, "runtime_healthy": True,
                      "dn_escape": 0, "decoder_stop": False, "source_age_ms": 0},
                     {"kind": "motion_refresh", "timestamp_ns": t, "positive_ack": True,
                      "robot_move_result": {"ok": True}, "call_ns": t - 2,
                      "write_ns": t - 1},
                     {"kind": "robot_state", "timestamp_ns": t, "deadman_limited": False,
                      "applied_velocity": [.07, 0.0, 0.0],
                      "requested_velocity": [.07, 0.0, 0.0],
                      "pose": {"x_m": .004 * i, "y_m": 0.0, "heading_rad": 0.0}} ,
                     {"kind": "control_publish", "timestamp_ns": t,
                      "sequence": i + 1, "call_ns": t - 1, "ack_ns": t,
                      "transport": "suppressed_neutral_for_stop_causality_fixture",
                      "neural_origin": False, "watchdog_state": "healthy",
                      "stop": False, "intent": {"stop": False, "vx": 0.0,
                                                  "vy": 0.0, "vyaw": 0.0}}))
    rows += [{"kind": "window_complete", "timestamp_ns": start + 1_000_000_000},
             {"kind": "robotd_health_after", "timestamp_ns": start + 1_000_000_001,
              "healthy": True},
             {"kind": "safety_snapshot", "timestamp_ns": start + 1_000_000_001,
              "violations": 0, "scheduler_result": {"scheduler_exceptions": 0}}]
    return rows


class RawScorerTests(unittest.TestCase):
    def test_clean_controls(self):
        for stage, ordinal in (("S", 0), ("R", 0)):
            result = score_raw(clean_raw(stage), trial_id="S889200" if stage == "S" else "R889300",
                               ordinal=ordinal, stage=stage)
            self.assertTrue(result["clean_true_negative"], result)

    def test_missing_transition_and_prearm_health_contaminate(self):
        result = score_raw(clean_raw(), trial_id="S889200", ordinal=0,
                           stage="S", local_gate=LOCAL_CONFIG["settled_gate"])
        self.assertIn("local_reference_transition_invalid", result["failure_causes"])
        self.assertIn("prearm_health_invalid", result["failure_causes"])

    def test_nonzero_arm_prime_healthy_stop_is_counted(self):
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            folder = root / "S889200" / "attempt-01"
            folder.mkdir(parents=True)
            events = [{"kind": "arm", "timestamp_ns": 1_000_000_000,
                       "reset_id": "S889200", "ordinal": 0},
                      {"kind": "neural_step", "timestamp_ns": 1_000_000_001,
                       "runtime_healthy": True, "dn_escape": .6,
                       "decoder_stop": True}]
            (folder / "events.jsonl").write_text("".join(json.dumps(r) + "\n"
                                                       for r in events))
            marker = {"schema_version": "p8-03-local-arm-v1",
                      "task": "P8-03-LOCAL-REFERENCE-PROTOCOL-V1",
                      "reset_id": "S889200", "ordinal": 0, "attempt": 1,
                      "source_head": "a" * 40, "config_sha256": "b" * 64,
                      "state": "ARMED", "armed_at_utc_ns": 1,
                      "armed_at_monotonic_ns": 999_999_999}
            (folder / "armed.json").write_text(json.dumps(marker))
            (root / "batch-journal.json").write_text(json.dumps({
                "source_path": str(Path(__file__).parents[1]),
                "schema_version": "p8-03-local-batch-journal-v1", "stage": "S",
                "reset_id_semantics": "UNIQUE_LABEL_ONLY",
                "simulator_rng_seeded": False, "source_head": "a" * 40,
                "config_sha256": "b" * 64,
                "ids": [{"reset_id": "S889200", "ordinal": 0,
                         "status": "PREARM_UNCLASSIFIED",
                         "attempts": [{"name": "attempt-01", "armed": True,
                                       "status": "TRIAL_EXITED", "trial_exit": 1}]}],
                "final_sim_down": None}))
            result = score_batch(root, LOCAL_CONFIG, "S")
            self.assertEqual(result["false_neural_stops"], 1)
            self.assertTrue(result["trials"][0]["false_neural_stop"])
            self.assertIn("attempt_accounting", result["trials"][0]["failure_causes"])
            self.assertNotIn("arm_marker_invalid", result["trials"][0]["failure_causes"])
            self.assertEqual(result["result"], "FAIL")
            marker["armed_at_monotonic_ns"] = 1_000_000_001
            (folder / "armed.json").write_text(json.dumps(marker))
            late = score_batch(root, LOCAL_CONFIG, "S")
            self.assertIn("arm_marker_invalid", late["trials"][0]["failure_causes"])

    def test_completed_trial_ignores_post_window_neural_stop(self):
        full_rows = clean_raw()
        full_rows.append({"kind": "neural_step", "timestamp_ns": 2_100_000_000,
                          "runtime_healthy": True, "dn_escape": .7,
                          "decoder_stop": True})
        full_result = score_raw(full_rows, trial_id="S889200", ordinal=0, stage="S")
        self.assertTrue(full_result["clean_true_negative"])
        self.assertFalse(full_result["false_neural_stop"])
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            folder = root / "S889200" / "attempt-01"
            folder.mkdir(parents=True)
            events = [{"kind": "arm", "timestamp_ns": 1_000_000_000,
                       "reset_id": "S889200", "ordinal": 0},
                      {"kind": "neural_step", "timestamp_ns": 2_100_000_000,
                       "runtime_healthy": True, "dn_escape": .7,
                       "decoder_stop": True}]
            (folder / "events.jsonl").write_text("".join(json.dumps(r) + "\n"
                                                       for r in events))
            (root / "batch-journal.json").write_text(json.dumps({
                "source_path": str(Path(__file__).parents[1]),
                "schema_version": "p8-03-local-batch-journal-v1", "stage": "S",
                "reset_id_semantics": "UNIQUE_LABEL_ONLY",
                "simulator_rng_seeded": False, "source_head": "a" * 40,
                "config_sha256": "b" * 64,
                "ids": [{"reset_id": "S889200", "ordinal": 0,
                         "status": "ARMED_COMPLETE",
                         "attempts": [{"name": "attempt-01", "armed": True,
                                       "status": "TRIAL_EXITED", "trial_exit": 0}]}],
                "final_sim_down": None}))
            result = score_batch(root, LOCAL_CONFIG, "S")
            self.assertEqual(result["false_neural_stops"], 0)
            self.assertFalse(result["trials"][0]["false_neural_stop"])
            self.assertEqual(result["result"], "FAIL")  # incomplete raw remains terminal

    def test_raw_movement_tampering_contaminates(self):
        rows = clean_raw()
        for event in rows:
            for key in ("timestamp_ns", "call_ns", "write_ns", "ack_ns"):
                if type(event.get(key)) is int:
                    event[key] += 2_000_000_000
        arm = next(r for r in rows if r["kind"] == "arm")
        local = next(r for r in rows if r["kind"] == "local_reference")
        local["capture_ns"] = 1_000_000_000
        pre = []
        poses = []
        for i in range(75):
            t = 1_500_000_000 + i * 20_000_000
            x = i * .0014
            packet = {"trunk": [x, 0., .3], "imu": {"quat": [1., 0., 0., 0.]}}
            pose_ns = t + 2_000_000
            pre.append({"kind": "precondition_motion", "timestamp_ns": t,
                        "robot_move_ack": {"ok": True}, "state_ns": t + 1_000_000,
                        "pose_ns": pose_ns, "pose_request_ns": t + 1_500_000,
                        "raw_body_packet": json.dumps(packet),
                        "pose": {"x_m": x, "y_m": 0., "trunk_z_m": .3,
                                 "heading_rad": 0.},
                        "applied_velocity": [.07, 0., 0.], "limited_by": []})
            poses.append({"timestamp_ns": pose_ns, "x_m": x, "y_m": 0.})
        arm["moving_confirmed_ns"] = first_sustained(
            pose_speeds(poses, window_ms=100, max_window_ms=140),
            threshold_mps=.015, duration_ms=200, at_or_above=True)
        arm["precondition_displacement_m"] = poses[-1]["x_m"] - poses[0]["x_m"]
        arm["precondition_applied_vx_mps"] = .07
        rows.extend(pre)
        clean = score_raw(rows, trial_id="S889200", ordinal=0, stage="S",
                          moving_gate=LOCAL_CONFIG["moving_gate"])
        self.assertNotIn("moving_precondition_raw_invalid", clean["failure_causes"])
        pre[20]["pose"]["x_m"] += .1
        tampered = score_raw(rows, trial_id="S889200", ordinal=0, stage="S",
                             moving_gate=LOCAL_CONFIG["moving_gate"])
        self.assertIn("moving_precondition_raw_invalid", tampered["failure_causes"])

    def test_false_stop_even_if_cleanup_follows(self):
        rows = clean_raw()
        rows += [{"kind": "neural_step", "timestamp_ns": 1_500_000_000,
                  "runtime_healthy": True, "dn_escape": .6, "decoder_stop": True,
                  "source_age_ms": 0},
                 {"kind": "cleanup", "timestamp_ns": 2_000_000_001}]
        result = score_raw(rows, trial_id="S889200", ordinal=0, stage="S")
        self.assertTrue(result["false_neural_stop"])
        self.assertFalse(result["clean_true_negative"])

    def test_dn_threshold_crossing_cannot_be_clean_negative(self):
        rows = clean_raw()
        next(r for r in rows if r["kind"] == "neural_step")["dn_escape"] = .6
        result = score_raw(rows, trial_id="S889200", ordinal=0, stage="S")
        self.assertTrue(result["false_neural_stop"])
        self.assertIn("dn_decoder_mismatch", result["failure_causes"])

    def test_geometry_and_fault_contaminate(self):
        rows = clean_raw()
        next(r for r in rows if r["kind"] == "visual_frame")["distance_m"] = .86
        rows.append({"kind": "fault", "timestamp_ns": 1_300_000_000})
        result = score_raw(rows, trial_id="S889200", ordinal=0, stage="S")
        self.assertIn("static_geometry", result["failure_causes"])
        self.assertIn("fault_or_exception", result["failure_causes"])

    def test_wilson_has_fixed_denominator(self):
        low, high = wilson_95(1, 20)
        self.assertLess(low, .05)
        self.assertGreater(high, .05)

    def test_extra_or_mutated_raw_fails_full_manifest(self):
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            path = root / "S889200" / "attempt-01" / "events.jsonl"
            path.parent.mkdir(parents=True)
            path.write_bytes(b'{"kind":"arm"}\n')
            data = path.read_bytes()
            manifest = {"schema_version": "p8-03-local-raw-manifest-v1",
                        "files": [{"path": path.relative_to(root).as_posix(),
                                   "sha256": hashlib.sha256(data).hexdigest(),
                                   "bytes": len(data), "record_count": 1}]}
            (root / "raw-manifest.json").write_text(json.dumps(manifest))
            self.assertEqual(manifest_check(root)["result"], "PASS")
            path.write_bytes(data + b"{}\n")
            self.assertEqual(manifest_check(root)["result"], "FAIL")
            path.write_bytes(data)
            (root / "unlisted.log").write_text("junk")
            self.assertEqual(manifest_check(root)["result"], "FAIL")

    def test_fault_stop_blocks_clean_true_negative(self):
        rows = clean_raw()
        rows.append({"kind": "control_publish", "timestamp_ns": 1_500_000_000,
                     "watchdog_state": "fault", "stop": True,
                     "neural_origin": False, "transport": "robot.stop"})
        result = score_raw(rows, trial_id="S889200", ordinal=0, stage="S")
        self.assertFalse(result["false_neural_stop"])
        self.assertFalse(result["clean_true_negative"])
        self.assertIn("fault_stop", result["failure_causes"])

    def test_empty_control_ledger_and_stopped_body_fail(self):
        rows = [r for r in clean_raw() if r["kind"] != "control_publish"]
        result = score_raw(rows, trial_id="S889200", ordinal=0, stage="S")
        self.assertIn("control_publish_missing_or_invalid", result["failure_causes"])
        rows = clean_raw()
        for row in rows:
            if row["kind"] == "robot_state":
                row["applied_velocity"][0] = 0.0
            if row["kind"] == "visual_frame":
                row["pose"]["x_m"] = 0.0
                row["virtual_center_x_m"] = row["distance_m"]
        result = score_raw(rows, trial_id="S889200", ordinal=0, stage="S")
        self.assertIn("applied_motion_missing", result["failure_causes"])
        self.assertIn("body_not_moving", result["failure_causes"])

    def test_recovery_is_audit_only(self):
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            journal = {"ids": [{"reset_id": "S889200", "attempts": [
                {"name": "attempt-01", "status": "TRIAL_CHILD_STARTED", "armed": False}]}]}
            path = root / "batch-journal.json"
            path.write_text(json.dumps(journal))
            data = path.read_bytes()
            (root / "raw-manifest.json").write_text(json.dumps({
                "schema_version": "p8-03-local-raw-manifest-v1", "files": [{
                "path": "batch-journal.json", "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data), "record_count": 1}]}))
            result = recover_only(root)
            self.assertEqual(result["in_flight_unknown_arm"], ["S889200/attempt-01"])
            self.assertEqual(path.read_bytes(), data)

    def test_original_ledgers_must_match_events(self):
        with tempfile.TemporaryDirectory() as dirname:
            folder = Path(dirname)
            events = [{"kind": "visual_frame", "timestamp_ns": 1_000_000_000,
                       "source_valid": True, "image_area": .01},
                      {"kind": "neural_step", "timestamp_ns": 1_001_000_000,
                       "runtime_healthy": True, "dn_escape": 0,
                       "decoder_stop": False, "source_age_ms": 1,
                       "source_frame_id": 1}]
            visual = [{"timestamp_ns": 1_000_000_000, "frame_id": 1, "perception_valid": True,
                       "perception_target_area": .01}]
            neural = [{"neural_call_timestamp_ns": 1_001_000_000,
                       "neural_call_started_ns": 1_001_000_000,
                       "perception_timestamp_ns": 1_000_000_000,
                       "dn_runtime_healthy": True,
                       "male_cns_healthy": True, "dn_escape": 0,
                       "raw_decoder_stop": False, "perception_age_ms": 1,
                       "perception_frame_id": 1, "input_none": False,
                       "result_none": False, "perception_valid": True}]
            for name, rows in (("events.jsonl", events), ("visual-frames.jsonl", visual),
                               ("neural-ledger.jsonl", neural)):
                (folder / name).write_text("".join(json.dumps(row) + "\n" for row in rows))
            summary = {"event_sha256": hashlib.sha256((folder / "events.jsonl").read_bytes()).hexdigest(),
                       "visual_sha256": hashlib.sha256((folder / "visual-frames.jsonl").read_bytes()).hexdigest(),
                       "neural_ledger_sha256": hashlib.sha256((folder / "neural-ledger.jsonl").read_bytes()).hexdigest()}
            self.assertEqual(audit_original_ledgers(folder, events, summary), [])
            self.assertIn("original_rgb_tof_lineage_invalid",
                          audit_original_ledgers(folder, events, summary, tof_mm=500))
            neural[0]["perception_timestamp_ns"] = 100_000_000
            (folder / "neural-ledger.jsonl").write_text(json.dumps(neural[0]) + "\n")
            summary["neural_ledger_sha256"] = hashlib.sha256(
                (folder / "neural-ledger.jsonl").read_bytes()).hexdigest()
            self.assertIn("original_neural_visual_freshness_invalid",
                          audit_original_ledgers(folder, events, summary))
            neural[0]["perception_timestamp_ns"] = 1_000_000_000
            neural[0]["neural_call_started_ns"] = 1_200_000_000
            (folder / "neural-ledger.jsonl").write_text(json.dumps(neural[0]) + "\n")
            summary["neural_ledger_sha256"] = hashlib.sha256(
                (folder / "neural-ledger.jsonl").read_bytes()).hexdigest()
            self.assertIn("original_neural_visual_freshness_invalid",
                          audit_original_ledgers(folder, events, summary))
            neural[0]["neural_call_started_ns"] = 1_001_000_000
            neural[0]["dn_escape"] = .6
            (folder / "neural-ledger.jsonl").write_text(json.dumps(neural[0]) + "\n")
            summary["neural_ledger_sha256"] = hashlib.sha256(
                (folder / "neural-ledger.jsonl").read_bytes()).hexdigest()
            self.assertIn("original_neural_disagreement",
                          audit_original_ledgers(folder, events, summary))


if __name__ == "__main__":
    unittest.main()
