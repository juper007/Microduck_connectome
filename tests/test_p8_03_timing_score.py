"""Raw reconstruction tests for the development-only timing probe scorer."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from microduck_connectome.fractional_rgb_v21 import render_fractional_pixels
from microduck_connectome.control_contracts import make_behavior_intent
from microduck_connectome.looming_scenario import load_config, pixels_sha256
from microduck_connectome.p8_03_geometry import relative_trial
from scripts.p8_03_timing_score import score_batch


ARM = 3_000_000_000
SCENARIO = load_config(Path(__file__).resolve().parents[1] /
                       "config/looming_scenario_v1.json")


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
                    encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(root):
    config = {"schema_version": "p8-03-timing-probe-v1", "scored_window_ms": 1000,
              "visual_hz": 20, "neural_hz": 50, "control_hz": 50,
              "freshness_ttl_ms": 100,
              "static_tolerance_m": .005,
              "settled_gate": {"max_prearm_health_age_ms": 300,
                               "allowed_observed_policy_states": ["walk", "stand"]},
              "moving_gate": {"duration_s": 1.5, "command_period_ms": 20,
                              "maximum_state_age_ms": 100, "maximum_pose_age_ms": 100,
                              "minimum_trunk_displacement_m": .01,
                              "minimum_fresh_applied_vx_mps": .04,
                              "minimum_pose_speed_mps": .015},
              "development_gate": {"ids": [
                  {"reset_id": name, "ordinal": i,
                   "mode": "static" if i == 0 else "receding"} for i, name in enumerate(
                      ("TPR2-001", "TPR2-002", "TPR2-003"))]}}
    (root / "final-down.log").write_text("down complete\n", encoding="utf-8")
    (root / "final-state-probe.json").write_text(json.dumps({"result": "PASS"}),
                                                   encoding="utf-8")
    journal = {"ids": [], "final_sim_down": {
        "exit": 0, "interrupted": False, "state_probe_result": "PASS",
        "sha256": digest(root / "final-down.log"),
        "state_probe_sha256": digest(root / "final-state-probe.json")}}
    for i, name in enumerate(("TPR2-001", "TPR2-002", "TPR2-003")):
        mode = "static" if i == 0 else "receding"
        folder = root / name / "attempt-01"
        folder.mkdir(parents=True)
        reference = {"result": "PASS", "reset_id": name, "reference": {"x_m": 0}}
        (folder / "local-reference.json").write_text(json.dumps(reference), encoding="utf-8")
        marker = {"state": "ARMED", "reset_id": name, "source_head": "a" * 40,
                  "reference_sha256": digest(folder / "local-reference.json"),
                  "armed_at_monotonic_ns": ARM - 100_000}
        (folder / "armed.json").write_text(json.dumps(marker), encoding="utf-8")
        baseline_pose = {"x_m": .15, "y_m": 0, "trunk_z_m": .1,
                         "heading_rad": 0}
        baseline_trial, _ = relative_trial(
            pose=baseline_pose, trial_id=name, ordinal=i, mode=mode,
            elapsed_after_arm_s=0)
        baseline_pixels = render_fractional_pixels(
            SCENARIO, baseline_trial, pose=baseline_pose, elapsed_s=0)
        baseline_area = sum(pixel[0] for line in baseline_pixels for pixel in line) / (
            255 * SCENARIO["image_width_px"] * SCENARIO["image_height_px"])
        events = [
            {"kind": "robotd_health_before", "timestamp_ns": ARM - 2_000_000_000,
             "healthy": True},
            {"kind": "prearm_health", "timestamp_ns": ARM - 1_000_000,
             "after_ready": True, "health": {"healthy": True}},
            {"kind": "timing_prearm_ready", "timestamp_ns": ARM - 2_000_000,
             "worker_count": 6, "last_move_ack_ns": ARM - 10_000_000,
             "state_source_ns": ARM - 4_000_000,
             "applied_velocity": [.07, 0, 0], "limited_by": [],
             "policy": "walk", "safety": {"fallen": False, "limp": False},
             "latest_pose_speed_mps": .07,
             "last_pose_source_ns": ARM - 3_000_000},
            {"kind": "arm", "timestamp_ns": ARM, "reset_id": name, "ordinal": i,
             "moving_confirmed_ns": ARM - 500_000_000,
             "precondition_displacement_m": .148,
             "precondition_applied_vx_mps": .07},
            {"kind": "timing_arm_anchor", "timestamp_ns": ARM,
             "pose_source_ns": ARM - 3_000_000,
             "pose": {"x_m": .15, "y_m": 0,
                      "trunk_z_m": .1, "heading_rad": 0},
             "moving_confirmed_ns": ARM - 43_000_000,
             "latest_pose_speed_mps": .07},
            {"kind": "prearm_visual_anchor", "timestamp_ns": ARM - 5_000_000,
             "distance_m": .85, "image_area": baseline_area,
             "pose": baseline_pose},
            {"kind": "window_complete", "timestamp_ns": ARM + 1_000_000_000},
            {"kind": "robotd_health_after", "timestamp_ns": ARM + 1_010_000_000,
             "healthy": True},
            {"kind": "timing_process_cpu", "timestamp_ns": ARM + 1_001_000_000,
             "cpu_at_arm_ns": 10, "cpu_at_complete_ns": 900_000_010},
            {"kind": "safety_snapshot", "timestamp_ns": ARM + 1_020_000_000,
             "violations": 0, "scheduler_result": {
                 "dropped_neural": 0, "scheduler_exceptions": 0,
                 "missed_deadlines": {"perception": 0, "neural": 0,
                                      "watchdog": 0}}}]
        for j in range(75):
            ts = ARM - 2_080_000_000 + j * 20_000_000
            events.append({"kind": "precondition_motion", "timestamp_ns": ts,
                           "robot_move_ack": {"accepted": True},
                           "state_ns": ts + 1_000_000, "pose_ns": ts + 2_000_000,
                           "applied_velocity": [.07, 0, 0], "limited_by": [],
                           "pose": {"x_m": j * .002, "y_m": 0}})
        timing = [{"kind": "motion_refresh", "phase": "prearm",
                   "timestamp_ns": ARM - 580_000_000 + j * 20_000_000,
                   "move_ack_ns": ARM - 580_000_000 + j * 20_000_000}
                  for j in range(29)]
        timing.append({"kind": "motion_refresh", "phase": "prearm",
                       "timestamp_ns": ARM - 10_000_000,
                       "move_ack_ns": ARM - 10_000_000})
        for j in range(18):
            source = ARM - 343_000_000 + j * 20_000_000
            pose_x = .15 - (17 - j) * .0014
            timing.append({"kind": "pose_observation", "timestamp_ns": source + 1_000_000,
                           "source_timestamp_ns": source,
                           "move_ack_ns": source - 3_000_000,
                           "value": {"request_ns": source - 1_000_000,
                                     "raw_body_packet": json.dumps({
                                         "trunk": [pose_x, 0, .1],
                                         "imu": {"quat": [1, 0, 0, 0]}}),
                                     "pose": {"x_m": pose_x, "y_m": 0,
                                              "trunk_z_m": .1,
                                              "heading_rad": 0}}})
        timing.append({"kind": "motion_arm", "timestamp_ns": ARM,
                   "last_move_ack_ns": ARM - 10_000_000,
                   "handoff_gap_ns": 10_000_000})
        neural, visual = [], []
        for slot in range(20):
            ts = ARM + slot * 50_000_000
            pose = {"x_m": slot * .002, "y_m": 0,
                    "trunk_z_m": .1, "heading_rad": 0}
            virtual, distance = relative_trial(
                pose=pose, trial_id=name, ordinal=i, mode=mode,
                elapsed_after_arm_s=(ts - ARM) / 1e9)
            pixels = render_fractional_pixels(SCENARIO, virtual,
                                              pose=pose, elapsed_s=0)
            area = sum(pixel[0] for line in pixels for pixel in line) / (
                255 * SCENARIO["image_width_px"] * SCENARIO["image_height_px"])
            row = {"frame_id": slot + 1, "timestamp_ns": ts,
                   "perception_valid": True, "perception_target_area": area,
                   "pixels_sha256": pixels_sha256(pixels),
                   "tof_source": "frozen_synthetic_fixture",
                   "tof_left_mm": SCENARIO["tof_mm"],
                   "tof_center_mm": SCENARIO["tof_mm"],
                   "tof_right_mm": SCENARIO["tof_mm"],
                   "tof_timestamp_ns": ts, "tof_frame_id": slot + 1,
                   "processing_started_ns": ts + 1_000,
                   "processing_finished_ns": ts + 100_000}
            visual.append(row)
            events.append({"kind": "visual_frame", "timestamp_ns": ts,
                           "source_valid": True, "source_frame_id": slot + 1,
                           "pixels_sha256": row["pixels_sha256"], "image_area": area,
                           "tof_timestamp_ns": ts, "tof_frame_id": slot + 1,
                           "distance_m": distance, "target_distance_m": distance,
                           "bearing_rad": 0, "pose": pose,
                           "pose_request_ns": ts + 1_000,
                           "pose_response_ns": ts + 2_000,
                           "raw_body_packet": json.dumps({
                               "trunk": [pose["x_m"], pose["y_m"], .1],
                               "imu": {"quat": [1, 0, 0, 0]}}),
                           "virtual_center_x_m": virtual.anchor_x_m,
                           "virtual_center_y_m": virtual.anchor_y_m})
        for slot in range(50):
            deadline = ARM + slot * 20_000_000
            wake = deadline + 500_000
            complete = deadline + 5_000_000
            for domain in ("perception", "neural", "watchdog"):
                domain_start = deadline + 5_000_000 if domain == "watchdog" else wake
                domain_complete = deadline + 8_000_000 if domain == "watchdog" else complete
                timing.append({"kind": "scheduled_tick", "domain": domain,
                               "slot": slot, "scheduled_deadline_ns": deadline,
                               "worker_wake_ns": wake, "step_start_ns": domain_start,
                               "tick_complete_ns": domain_complete,
                               "thread_id": 10, "late_or_overrun": False})
            timing.append({"kind": "neural_outer_arbiter_lock",
                           "timestamp_ns": wake + 100,
                           "wait_start_ns": wake, "acquired_ns": wake + 100,
                           "released_ns": deadline + 4_000_000,
                           "queue_access_start_ns": wake + 200,
                           "queue_access_end_ns": wake + 300,
                           "queue_wait_ns": 100, "perception_wait_ns": 0,
                           "perception_source_age_ns": 1_000_000,
                           "thread_id": 10})
            frame_id = slot * 20 // 50 + 1
            source_ns = ARM + (frame_id - 1) * 50_000_000
            started = deadline + 1_000_000
            returned = deadline + 3_000_000
            neural.append({"neural_call_timestamp_ns": wake,
                           "neural_call_started_ns": started,
                           "neural_call_returned_ns": returned,
                           "runtime_step": slot + 1, "input_none": False,
                           "result_none": False, "male_cns_healthy": True,
                           "dn_runtime_healthy": True, "dn_escape": 0.0,
                           "raw_decoder_stop": False, "perception_valid": True,
                           "perception_frame_id": frame_id,
                           "perception_timestamp_ns": source_ns,
                           "perception_age_ms": (started - source_ns) / 1e6})
            events.append({"kind": "neural_step", "timestamp_ns": wake,
                           "runtime_healthy": True, "dn_escape": 0.0,
                           "decoder_stop": False,
                           "source_age_ms": (started - source_ns) / 1e6,
                           "source_frame_id": frame_id})
            spans = {key: {"start_ns": started, "end_ns": started + 100_000}
                     for key in ("graph_runtime", "sensory_channels", "sensory_external",
                                 "readout", "decoder_safety_latch", "arbiter_lock_wait",
                                 "trace_construction", "ledger_append")}
            spans["neural_call"] = {"start_ns": started, "end_ns": returned}
            timing.append({"kind": "neural_span", "neural_call_timestamp_ns": wake,
                           "result_none": False, "spans": spans,
                           "thread_cpu_start_ns": 1000 * slot,
                           "thread_cpu_return_ns": 1000 * slot + 900})
            control = {"kind": "control_publish", "timestamp_ns": deadline + 7_000_000,
                       "call_ns": deadline + 6_000_000,
                       "ack_ns": deadline + 7_000_000, "sequence": slot + 1,
                       "watchdog_state": "healthy", "stop": False,
                       "intent": make_behavior_intent(
                           timestamp_ns=deadline + 5_000_000,
                           sequence=slot + 1),
                       "transport": "suppressed_neutral_for_stop_causality_fixture"}
            events.append(control)
            ack = deadline + 2_000_000
            move = {"kind": "motion_refresh", "phase": "scored", "scored_slot": slot,
                    "timestamp_ns": ack, "scheduled_deadline_ns": deadline,
                    "wake_ns": wake, "move_call_ns": deadline + 1_000_000,
                    "move_write_ns": deadline + 1_100_000,
                    "move_ack_ns": ack, "thread_id": 11,
                    "result": {"accepted": True}}
            timing.append(move)
            events.append(dict(move))
            timing.append({"kind": "state_observation", "timestamp_ns": ack + 3_000_000,
                           "source_timestamp_ns": ack + 2_000_000,
                           "move_ack_ns": ack, "thread_id": 12,
                           "value": {"applied_velocity": [.07, 0, 0],
                                     "requested_velocity": [.07, 0, 0],
                                     "limited_by": [], "policy": "walk",
                                     "safety": {}}})
            timing.append({"kind": "pose_observation", "timestamp_ns": ack + 4_000_000,
                           "source_timestamp_ns": ack + 3_000_000,
                           "move_ack_ns": ack, "thread_id": 13,
                           "value": {"request_ns": ack + 2_500_000,
                                     "raw_body_packet": json.dumps({
                                         "trunk": [slot * .002, 0, .1],
                                         "imu": {"quat": [1, 0, 0, 0]}}),
                                     "pose": {"x_m": slot * .002, "y_m": 0,
                                              "trunk_z_m": .1, "heading_rad": 0}}})
        events.sort(key=lambda row: row["timestamp_ns"])
        for key, rows, filename in (("event_sha256", events, "events.jsonl"),
                                    ("neural_ledger_sha256", neural, "neural-ledger.jsonl"),
                                    ("visual_sha256", visual, "visual-frames.jsonl"),
                                    ("timing_ledger_sha256", timing, "timing-ledger.jsonl")):
            write_jsonl(folder / filename, rows)
        summary = {"reset_id": name, "armed": True, "source_head": "a" * 40,
                   "reference_sha256": digest(folder / "local-reference.json"),
                   "scheduler_exceptions": 0, "safety_limit_violations": 0,
                   "fixture_errors": [], "timing_scheduler_ticks": 150,
                   "timing_motion": {"scored_slots_sent": 50, "missed_periods": 0,
                                     "queue_drops": 0, "fault_reason": None},
                   **{key: digest(folder / filename) for key, filename in (
                       ("event_sha256", "events.jsonl"),
                       ("neural_ledger_sha256", "neural-ledger.jsonl"),
                       ("visual_sha256", "visual-frames.jsonl"),
                       ("timing_ledger_sha256", "timing-ledger.jsonl"))}}
        (folder / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        journal["ids"].append({"reset_id": name, "status": "ARMED_COMPLETE",
                               "attempts": [{"name": "attempt-01", "armed": True,
                                             "status": "TRIAL_EXITED", "trial_exit": 0}]})
    (root / "batch-journal.json").write_text(json.dumps(journal), encoding="utf-8")
    return config


class TimingScoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = fixture(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_complete_real_slots_pass(self):
        score = score_batch(self.root, self.config)
        self.assertEqual(score["result"], "PASS", score)
        self.assertEqual(score["trials"][0]["metrics"]["neural"]["count"], 50)
        self.assertEqual(score["trials"][0]["metrics"]["motion"]["count"], 50)

    def test_missing_neural_slot_fails_even_with_summary(self):
        folder = self.root / "TPR2-001" / "attempt-01"
        path = folder / "timing-ledger.jsonl"
        rows = [row for row in (json.loads(line) for line in path.read_text().splitlines()) if not (
            row.get("kind") == "scheduled_tick" and row.get("domain") == "neural"
            and row.get("slot") == 7)]
        write_jsonl(path, rows)
        summary_path = folder / "summary.json"
        summary = json.loads(summary_path.read_text())
        summary["timing_ledger_sha256"] = digest(path)
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        score = score_batch(self.root, self.config)
        self.assertEqual(score["result"], "FAIL")
        self.assertIn("neural_slots_incomplete", score["trials"][0]["failure_causes"])

    def test_missing_control_publication_fails(self):
        folder = self.root / "TPR2-001" / "attempt-01"
        path = folder / "events.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        target = next(row for row in rows if row.get("kind") == "control_publish")
        rows.remove(target)
        write_jsonl(path, rows)
        summary_path = folder / "summary.json"
        summary = json.loads(summary_path.read_text())
        summary["event_sha256"] = digest(path)
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        score = score_batch(self.root, self.config)
        self.assertEqual(score["result"], "FAIL")
        self.assertIn("control_publications_incomplete_or_duplicate",
                      score["trials"][0]["failure_causes"])

    def test_duplicate_graph_step_cannot_fill_a_slot(self):
        folder = self.root / "TPR2-001" / "attempt-01"
        path = folder / "neural-ledger.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[7]["runtime_step"] = rows[6]["runtime_step"]
        write_jsonl(path, rows)
        summary_path = folder / "summary.json"
        summary = json.loads(summary_path.read_text())
        summary["neural_ledger_sha256"] = digest(path)
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        score = score_batch(self.root, self.config)
        self.assertEqual(score["result"], "FAIL")
        self.assertIn("neural_runtime_step_duplicate",
                      score["trials"][0]["failure_causes"])

    def test_deadman_state_cannot_count_as_continuous_motion(self):
        folder = self.root / "TPR2-001" / "attempt-01"
        path = folder / "timing-ledger.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        next(row for row in rows if row.get("kind") == "state_observation")[
            "value"]["limited_by"] = ["deadman"]
        write_jsonl(path, rows)
        summary_path = folder / "summary.json"
        summary = json.loads(summary_path.read_text())
        summary["timing_ledger_sha256"] = digest(path)
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        score = score_batch(self.root, self.config)
        self.assertEqual(score["result"], "FAIL")
        self.assertIn("state_motion_or_deadman_invalid",
                      score["trials"][0]["failure_causes"])

    def test_visual_without_raw_pose_cannot_pass(self):
        folder = self.root / "TPR2-001" / "attempt-01"
        path = folder / "events.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        next(row for row in rows if row.get("kind") == "visual_frame").pop(
            "raw_body_packet")
        write_jsonl(path, rows)
        summary_path = folder / "summary.json"
        summary = json.loads(summary_path.read_text())
        summary["event_sha256"] = digest(path)
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        score = score_batch(self.root, self.config)
        self.assertIn("visual_slot_0_geometry_invalid",
                      score["trials"][0]["failure_causes"])

    def test_unsafe_policy_at_ready_cannot_pass(self):
        folder = self.root / "TPR2-001" / "attempt-01"
        path = folder / "events.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        next(row for row in rows if row.get("kind") == "timing_prearm_ready")[
            "policy"] = "limp"
        write_jsonl(path, rows)
        summary_path = folder / "summary.json"
        summary = json.loads(summary_path.read_text())
        summary["event_sha256"] = digest(path)
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        score = score_batch(self.root, self.config)
        self.assertIn("prearm_ready_lineage_invalid",
                      score["trials"][0]["failure_causes"])

    def test_interrupted_final_down_cannot_pass(self):
        path = self.root / "batch-journal.json"
        journal = json.loads(path.read_text())
        journal["final_sim_down"]["interrupted"] = True
        path.write_text(json.dumps(journal), encoding="utf-8")
        score = score_batch(self.root, self.config)
        self.assertEqual(score["result"], "FAIL")
        self.assertFalse(score["final_down_raw_valid"])

    def test_stopped_body_before_arm_cannot_pass(self):
        folder = self.root / "TPR2-001" / "attempt-01"
        path = folder / "timing-ledger.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        poses = [row for row in rows if row.get("kind") == "pose_observation"
                 and row["source_timestamp_ns"] < ARM]
        held_x = poses[-8]["value"]["pose"]["x_m"]
        for row in poses[-7:]:
            row["value"]["pose"]["x_m"] = held_x
        write_jsonl(path, rows)
        summary_path = folder / "summary.json"
        summary = json.loads(summary_path.read_text())
        summary["timing_ledger_sha256"] = digest(path)
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        score = score_batch(self.root, self.config)
        self.assertIn("arm_body_motion_not_confirmed",
                      score["trials"][0]["failure_causes"])

    def test_missing_tof_source_cannot_pass(self):
        folder = self.root / "TPR2-001" / "attempt-01"
        path = folder / "visual-frames.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[0].pop("tof_source")
        write_jsonl(path, rows)
        summary_path = folder / "summary.json"
        summary = json.loads(summary_path.read_text())
        summary["visual_sha256"] = digest(path)
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        score = score_batch(self.root, self.config)
        self.assertIn("visual_slot_0_invalid", score["trials"][0]["failure_causes"])

    def test_missing_control_intent_cannot_pass(self):
        folder = self.root / "TPR2-001" / "attempt-01"
        path = folder / "events.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        next(row for row in rows if row.get("kind") == "control_publish").pop("intent")
        write_jsonl(path, rows)
        summary_path = folder / "summary.json"
        summary = json.loads(summary_path.read_text())
        summary["event_sha256"] = digest(path)
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        score = score_batch(self.root, self.config)
        self.assertIn("control_slot_0_intent_invalid",
                      score["trials"][0]["failure_causes"])

    def test_neural_event_disagreement_cannot_pass(self):
        folder = self.root / "TPR2-001" / "attempt-01"
        path = folder / "events.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        next(row for row in rows if row.get("kind") == "neural_step")[
            "source_age_ms"] = 99
        write_jsonl(path, rows)
        summary_path = folder / "summary.json"
        summary = json.loads(summary_path.read_text())
        summary["event_sha256"] = digest(path)
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        score = score_batch(self.root, self.config)
        self.assertIn("neural_slot_0_invalid", score["trials"][0]["failure_causes"])


if __name__ == "__main__":
    unittest.main()
