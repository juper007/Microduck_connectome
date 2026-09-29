"""R1 regression through the actual trial entry point and bounded child supervisor."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import p8_03_trial as trial
from scripts import p8_03_batch as batch


class FakeRobot:
    def __init__(self, *_args, **_kwargs):
        self.closed = False
        self.stops = 0
        self.fail_enable = False
    def connect(self):
        pass
    def enable(self, _value):
        if self.fail_enable:
            raise RuntimeError("injected enable failure")
    def stop(self):
        self.stops += 1
    def health(self):
        return {"healthy": True, "degraded": False, "control_loop": {"ticks": 1}}
    def close(self):
        self.closed = True


class FakeClient:
    def __init__(self, *_args):
        self.moves = 0
        self.stops = 0
        self.closed = False
    def request(self, method, _params):
        if method == "robot.stop":
            self.stops += 1
        return {"ok": True}
    def close(self):
        self.closed = True


class FakeSampler:
    def __init__(self, *_args):
        self.moving = False
        self.closed = False
        self.fail_before_move = False
    def after(self, _timestamp_ns):
        if self.fail_before_move:
            raise RuntimeError("injected before movement")
        now = time.monotonic_ns()
        return ({"policy": "stand", "safety": {"fallen": False, "limp": False},
                 "move": {"applied": [.06 if self.moving else 0., 0., 0.],
                          "limited_by": [], "requested": [.06 if self.moving else 0., 0., 0.]},
                 "t_ns": now}, now)
    def close(self):
        self.closed = True


class FakePose:
    def __init__(self, *_args):
        self.sampler = None
        self.x = 0.0
        self.closed = False
        self.last = time.monotonic_ns()
    def read(self):
        if self.sampler.moving:
            self.x += .02
        self.last = time.monotonic_ns()
        return {"x_m": self.x, "y_m": 0., "trunk_z_m": .12,
                "heading_rad": 0., "roll_rad": 0., "pitch_rad": 0.}
    def source(self, _pose):
        return {"request_ns": self.last - 1000, "response_ns": self.last,
                "raw_packet": "{}"}
    def close(self):
        self.closed = True


class FakeChain:
    def __init__(self, *_args, **_kwargs):
        self.visual_frames = []
        self.neural_ledger = []
    def perception(self, _now_ns):
        return None
    def neural(self, _frame, _now_ns):
        return None


class FakePublisher:
    nonzero_count = 0
    post_stop_move_count = 0
    def __init__(self, *_args):
        pass


class FakeScheduler:
    def __init__(self, *_args, **_kwargs):
        self._threads = []
        self._fixture_complete = threading.Event()


class TrialPathTests(unittest.TestCase):
    def _run_path(self, *, fail_before_move=False, fail_setup=False):
        with tempfile.TemporaryDirectory() as dirname:
            folder = Path(dirname)
            reference = folder / "local-reference.json"
            record = {"schema_version": "p8-03-local-reference-v1", "result": "PASS",
                      "reset_id": "D889400", "attempt": 1, "capture_ns": 0,
                      "reference": {"x_m": 0., "y_m": 0., "trunk_z_m": .12,
                                    "heading_rad": 0., "roll_rad": 0., "pitch_rad": 0.}}
            trial.json_write(reference, record)
            digest = hashlib.sha256(reference.read_bytes()).hexdigest()
            self.assertEqual(reference.read_text(),
                             json.dumps(record, sort_keys=True, indent=2,
                                        allow_nan=False) + "\n")
            args = SimpleNamespace(root=folder, local_reference=reference,
                socket="unused", body_port=7894, attempt=1, stage="D", source_head="a" * 40,
                armed_marker=folder / "armed.json", progress=folder / "progress.jsonl",
                events=folder / "events.jsonl", ledger=folder / "ledger.jsonl",
                visual=folder / "visual.jsonl", summary=folder / "summary.json")
            gate = {"settle_window_s": .5, "minimum_distinct_pose_samples": 6,
                    "max_planar_drift_m": .0005, "max_z_drift_m": .0005,
                    "max_heading_drift_rad": .005, "max_pose_response_age_ms": 100,
                    "max_robotd_state_age_ms": 100, "max_health_age_ms": 300,
                    "max_abs_applied_vx_mps": .0001, "max_abs_applied_vy_mps": .0001,
                    "max_abs_applied_vyaw_radps": .0001,
                    "allowed_observed_policy_states": ["stand", "walk"]}
            execution = {"graph_path": str(folder / "graph.json"), "graph_sha256": "b"*64,
                         "settled_gate": gate,
                         "moving_gate": {"minimum_trunk_displacement_m": .01,
                                         "minimum_fresh_applied_vx_mps": .04,
                                         "maximum_state_age_ms": 100,
                                         "maximum_pose_age_ms": 100}}
            master = {"scenario": {"moving_precondition": {"duration_s": .04,
                       "command_period_ms": 20, "vx_mps": .06, "vy_mps": 0., "vyaw_radps": 0.}}}
            selected = {"looming_estimator": {"method": "log_area", "area_epsilon": 1e-6,
                        "full_scale_rate_per_s": .5, "max_gap_ms": 150, "window_ms": 200}}
            robot, client, sampler, pose = FakeRobot(), FakeClient(), FakeSampler(), FakePose()
            sampler.fail_before_move = fail_before_move
            pose.sampler = sampler
            def move(_client, **_kwargs):
                client.moves += 1
                sampler.moving = True
                now = time.monotonic_ns()
                return {"ok": True}, now, now, now
            def fail_geometry(**_kwargs):
                raise RuntimeError("injected after moving-body acquisition")
            scheduler_patch = (patch.object(trial, "NeuralStopRefreshScheduler",
                                            side_effect=RuntimeError("injected setup"))
                               if fail_setup else
                               patch.object(trial, "NeuralStopRefreshScheduler", FakeScheduler))
            with (patch.object(trial, "verify", return_value=(master, execution,
                    {"reset_id": "D889400", "ordinal": 0, "motion": "static",
                     "arm_elapsed_s": 2.}, selected, {"tof_mm": 1000}, digest)),
                  patch.object(trial.ConnectomeGraph, "from_cache", return_value=object()),
                  patch.object(trial, "RobotdClient", return_value=robot),
                  patch.object(trial, "RobotMotionAdapter", return_value=object()),
                  patch.object(trial, "IsolatedStopPublisher", FakePublisher),
                  patch.object(trial, "JsonLines", return_value=client),
                  patch.object(trial, "RobotStateSampler", return_value=sampler),
                  patch.object(trial, "PoseWithLineage", return_value=pose),
                  patch.object(trial, "LoomingChain", FakeChain),
                  patch.object(trial, "ControllerWatchdog", return_value=object()),
                  patch.object(trial, "FaultStopLatch", return_value=object()),
                  scheduler_patch,
                  patch.object(trial, "acknowledged_precondition_move", move),
                  patch.object(trial, "pose_speeds", return_value=[{"speed_mps": .05}]),
                  patch.object(trial, "first_sustained", return_value=1),
                  patch.object(trial, "precondition_deadman_after_motion", return_value=False),
                  patch.object(trial, "relative_trial", side_effect=fail_geometry)):
                if fail_setup:
                    with self.assertRaisesRegex(RuntimeError, "injected setup"):
                        trial.run(args)
                else:
                    self.assertEqual(trial.run(args), 1)
            self.assertTrue(robot.closed and client.closed and sampler.closed and pose.closed)
            self.assertEqual(client.stops, 1)
            self.assertFalse(args.armed_marker.exists())
            if fail_setup:
                self.assertFalse(args.summary.exists())
                return
            summary = json.loads(args.summary.read_text())
            events = [json.loads(line) for line in args.events.read_text().splitlines()]
            self.assertEqual(summary["reference_sha256"], digest)
            self.assertEqual(next(e for e in events if e["kind"] == "local_reference")
                             ["reference_sha256"], digest)
            self.assertEqual(client.moves, 0) if fail_before_move else self.assertGreater(client.moves, 0)
            if fail_before_move:
                self.assertIn("injected before movement", str(summary["fixture_errors"]))
            else:
                self.assertIn("injected after moving-body acquisition",
                              str(summary["fixture_errors"]))


    def test_failure_before_secondary_client_uses_robotd_stop(self):
        with tempfile.TemporaryDirectory() as dirname:
            folder = Path(dirname)
            reference = folder / "local-reference.json"
            reference.write_text("{}", encoding="utf-8")
            digest = hashlib.sha256(reference.read_bytes()).hexdigest()
            args = SimpleNamespace(root=folder, local_reference=reference, socket="unused",
                                   source_head="a" * 40)
            robot = FakeRobot()
            robot.fail_enable = True
            selected = {"looming_estimator": {"method": "log_area", "area_epsilon": 1e-6,
                        "full_scale_rate_per_s": .5, "max_gap_ms": 150, "window_ms": 200}}
            with (patch.object(trial, "verify", return_value=({},
                    {"graph_path": str(folder / "graph.json"), "graph_sha256": "b"*64},
                    {"reset_id": "D889400", "ordinal": 0, "motion": "static",
                     "arm_elapsed_s": 2.}, selected, {}, digest)),
                  patch.object(trial.ConnectomeGraph, "from_cache", return_value=object()),
                  patch.object(trial, "RobotdClient", return_value=robot)):
                with self.assertRaisesRegex(RuntimeError, "injected enable failure"):
                    trial.run(args)
            self.assertEqual(robot.stops, 1)
            self.assertTrue(robot.closed)

    def test_setup_exception_closes_subscribers_and_stops(self):
        self._run_path(fail_setup=True)

    def test_prearm_exception_cleanup_and_hash_lineage(self):
        self._run_path(fail_before_move=True)

    def test_moving_acquisition_reached_without_nameerror(self):
        self._run_path(fail_before_move=False)


class ChildDeadlineTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "POSIX signal behavior is checked on Thor")
    def test_child_timeout_is_bounded_without_operator(self):
        with tempfile.TemporaryDirectory() as dirname:
            start = time.monotonic()
            code, stopped, timed_out = batch.run_trial_child(
                [sys.executable, "-c",
                 "import threading,time; threading.Thread(target=lambda:time.sleep(10)).start(); raise RuntimeError('prearm failure')"],
                Path(dirname) / "child.log", os.environ.copy(),
                progress=lambda: None, timeout_s=.2)
            self.assertTrue(stopped and timed_out)
            self.assertNotEqual(code, 0)
            self.assertLess(time.monotonic() - start, 4)


class FrozenContractTests(unittest.TestCase):
    def test_persisted_reference_hash_is_canonical_and_repeatable(self):
        from tests.test_p8_03_local_reference import samples
        from scripts.p8_03_local_reference import settled_reference
        config = json.loads(Path("config/p8_03_local_reference_v1_r1.json").read_text())
        record = settled_reference(samples(), config["settled_gate"], 0)
        self.assertIsNotNone(record)
        record["reset_id"] = "D889400"
        record["attempt"] = 1
        with tempfile.TemporaryDirectory() as dirname:
            path = Path(dirname) / "local-reference.json"
            trial.json_write(path, record)
            observed, digest = trial.checked_reference(
                path, config["settled_gate"], "D889400", 1)
            self.assertEqual(observed, record)
            self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(trial.checked_reference(
                path, config["settled_gate"], "D889400", 1)[1], digest)
            with self.assertRaises(RuntimeError):
                trial.checked_reference(path, config["settled_gate"], "D889100", 1)

    def test_fresh_ids_and_frozen_behavior(self):
        old = json.loads(Path("config/p8_03_local_reference_v1.json").read_text())
        new = json.loads(Path("config/p8_03_local_reference_v1_r1.json").read_text())
        self.assertEqual([r["reset_id"] for r in new["development_gate"]["ids"]],
                         [f"D8894{i:02d}" for i in range(10)])
        self.assertNotIn("D889100", [r["reset_id"] for r in new["development_gate"]["ids"]])
        self.assertEqual(new["final_static"], old["final_static"])
        self.assertEqual(new["final_receding"], old["final_receding"])
        for key in ("settled_gate", "moving_gate", "scored_window_ms", "static_distance_m",
                    "static_tolerance_m", "receding_speed_mps", "receding_max_negative_frame_step_m",
                    "visual_hz", "neural_hz", "control_hz", "freshness_ttl_ms",
                    "max_false_stops_per_set", "max_false_stops_pooled",
                    "max_safety_limit_violations", "selected_pipeline"):
            self.assertEqual(new[key], old[key], key)
        self.assertFalse(new["behavioral_acceptance_change"])
        self.assertFalse(new["simulator_rng_seeded"])
