"""Raw reconstruction tests for the development-only timing probe scorer."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.p8_03_timing_score import score_batch


ARM = 3_000_000_000


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
                    encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(root):
    config = {"schema_version": "p8-03-timing-probe-v1", "scored_window_ms": 1000,
              "visual_hz": 20, "neural_hz": 50, "control_hz": 50,
              "freshness_ttl_ms": 100,
              "settled_gate": {"max_prearm_health_age_ms": 300,
                               "allowed_observed_policy_states": ["walk", "stand"]},
              "moving_gate": {"duration_s": 1.5, "command_period_ms": 20,
                              "maximum_state_age_ms": 100, "maximum_pose_age_ms": 100,
                              "minimum_trunk_displacement_m": .01,
                              "minimum_fresh_applied_vx_mps": .04,
                              "minimum_pose_speed_mps": .015},
              "development_gate": {"ids": [
                  {"reset_id": name, "ordinal": i} for i, name in enumerate(
                      ("TPR2-001", "TPR2-002", "TPR2-003"))]}}
    (root / "final-down.log").write_text("down complete\n", encoding="utf-8")
    (root / "final-state-probe.json").write_text(json.dumps({"result": "PASS"}),
                                                   encoding="utf-8")
    journal = {"ids": [], "final_sim_down": {
        "exit": 0, "state_probe_result": "PASS",
        "sha256": digest(root / "final-down.log"),
        "state_probe_sha256": digest(root / "final-state-probe.json")}}
    for i, name in enumerate(("TPR2-001", "TPR2-002", "TPR2-003")):
        folder = root / name / "attempt-01"
        folder.mkdir(parents=True)
        reference = {"result": "PASS", "reset_id": name, "reference": {"x_m": 0}}
        (folder / "local-reference.json").write_text(json.dumps(reference), encoding="utf-8")
        marker = {"state": "ARMED", "reset_id": name, "source_head": "a" * 40,
                  "reference_sha256": digest(folder / "local-reference.json"),
                  "armed_at_monotonic_ns": ARM - 100_000}
        (folder / "armed.json").write_text(json.dumps(marker), encoding="utf-8")
        events = [
            {"kind": "robotd_health_before", "timestamp_ns": ARM - 2_000_000_000,
             "healthy": True},
            {"kind": "prearm_health", "timestamp_ns": ARM - 1_000_000,
             "after_ready": True, "health": {"healthy": True}},
            {"kind": "timing_prearm_ready", "timestamp_ns": ARM - 2_000_000,
             "worker_count": 6, "last_move_ack_ns": ARM - 10_000_000,
             "last_pose_source_ns": ARM - 3_000_000},
            {"kind": "arm", "timestamp_ns": ARM, "reset_id": name, "ordinal": i,
             "moving_confirmed_ns": ARM - 500_000_000,
             "precondition_displacement_m": .148,
             "precondition_applied_vx_mps": .07},
            {"kind": "timing_arm_anchor", "timestamp_ns": ARM,
             "pose_source_ns": ARM - 3_000_000,
             "pose": {"x_m": .15, "y_m": 0}},
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
            ts = ARM - 1_500_000_000 + j * 20_000_000
            events.append({"kind": "precondition_motion", "timestamp_ns": ts,
                           "robot_move_ack": {"accepted": True},
                           "state_ns": ts + 1_000_000, "pose_ns": ts + 2_000_000,
                           "applied_velocity": [.07, 0, 0], "limited_by": [],
                           "pose": {"x_m": j * .002, "y_m": 0}})
        timing = [{"kind": "motion_refresh", "phase": "prearm",
                   "timestamp_ns": ARM - 10_000_000,
                   "move_ack_ns": ARM - 10_000_000},
                  {"kind": "pose_observation", "timestamp_ns": ARM - 2_000_000,
                   "source_timestamp_ns": ARM - 3_000_000,
                   "move_ack_ns": ARM - 10_000_000,
                   "value": {"pose": {"x_m": .15, "y_m": 0}}},
                  {"kind": "motion_arm", "timestamp_ns": ARM,
                   "last_move_ack_ns": ARM - 10_000_000,
                   "handoff_gap_ns": 10_000_000}]
        neural, visual = [], []
        for slot in range(20):
            ts = ARM + slot * 50_000_000
            row = {"frame_id": slot + 1, "timestamp_ns": ts,
                   "perception_valid": True, "perception_target_area": .01,
                   "pixels_sha256": f"frame-{slot}",
                   "processing_started_ns": ts + 1_000,
                   "processing_finished_ns": ts + 100_000}
            visual.append(row)
            events.append({"kind": "visual_frame", "timestamp_ns": ts,
                           "source_valid": True, "source_frame_id": slot + 1,
                           "pixels_sha256": row["pixels_sha256"], "image_area": .01})
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
                           "dn_runtime_healthy": True, "perception_valid": True,
                           "perception_frame_id": frame_id,
                           "perception_timestamp_ns": source_ns,
                           "perception_age_ms": (started - source_ns) / 1e6})
            events.append({"kind": "neural_step", "timestamp_ns": wake,
                           "runtime_healthy": True, "source_frame_id": frame_id})
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


if __name__ == "__main__":
    unittest.main()
