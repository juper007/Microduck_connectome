"""Offline preflight checks for the blocked P8-R3 official fixture."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

from microduck_connectome.control_contracts import make_behavior_intent
from microduck_connectome.fault_stop import FaultStopLatch
from microduck_connectome.neural_stop_arbiter import MotionLatched, NeuralStopMotionArbiter
from microduck_connectome.neural_stop_latch import NeuralStopIntentLatch
from microduck_connectome.safety_clamp import SafetyClamp
from microduck_connectome.watchdog import ControllerWatchdog
from scripts.p8_r3_official_batch import validate_trial_artifacts
from scripts.p8_r3_official_trial import (
    LoomingChain, VisualCadence, validate_frozen_material,
    validate_frozen_output_dir, validate_frozen_selection,
)


ROOT = Path(__file__).resolve().parents[1]


class OfficialSelectionTests(unittest.TestCase):
    def setUp(self):
        self.protocol = json.loads((ROOT / "config/p8_r3_official_v1.json").read_text())

    def test_unselected_internal_failure_cannot_launch(self):
        with self.assertRaisesRegex(RuntimeError, "internal neural gate"):
            validate_frozen_selection(self.protocol)
        v21 = json.loads((ROOT / "config/p8_r3_v21_official_v1.json").read_text())
        with self.assertRaisesRegex(RuntimeError, "internal neural gate and official protocol freeze"):
            validate_frozen_selection(v21)

    def frozen(self):
        protocol = copy.deepcopy(self.protocol)
        protocol["internal_gate_status"] = "PASS"
        protocol["official_freeze_status"] = "FROZEN"
        protocol["selected_v2"] = {
            "method": "log_area", "full_scale_rate_per_s": 0.5,
            "area_epsilon": 1e-6, "max_gap_ms": 150, "window_ms": 200,
        }
        protocol["visual_hz"] = 25
        protocol["scenario_config_path"] = "config/looming_scenario_v1.json"
        protocol["scenario_config_sha256"] = "a" * 64
        protocol["internal_gate_artifact_path"] = "docs/evidence/p8-r3/internal-development-raw-v1.json"
        protocol["internal_gate_artifact_sha256"] = "b" * 64
        return protocol

    def test_frozen_candidate_and_cadence_are_exact(self):
        protocol = self.frozen()
        selected, hz = validate_frozen_selection(protocol)
        self.assertEqual((selected.method, hz), ("log_area", 25))
        protocol["selected_v2"]["full_scale_rate_per_s"] = 0.49
        with self.assertRaisesRegex(RuntimeError, "prospective"):
            validate_frozen_selection(protocol)
        protocol = self.frozen()
        protocol["visual_hz"] = 50
        with self.assertRaisesRegex(RuntimeError, "visual cadence"):
            validate_frozen_selection(protocol)

    def test_official_seed_matrix_cannot_be_replaced(self):
        protocol = self.frozen()
        protocol["ordered_official_runs"][1]["seed"] = 880000
        with self.assertRaisesRegex(RuntimeError, "seed matrix"):
            validate_frozen_selection(protocol)

    def test_v21_requires_fractional_detector_and_log_area(self):
        protocol = self.frozen()
        protocol["schema_version"] = "p8-r3-v21-official-development-v1"
        protocol["ordered_official_runs"] = [
            {"run_id": f"{i+1:02d}-{seed}", "seed": seed,
             "arm_elapsed_s": arm}
            for i, (seed, arm) in enumerate(zip((885421, 885422, 885423),
                                                 (2.0, 2.6, 3.0)))
        ]
        protocol["fractional_rgb_module_sha256"] = "c" * 64
        protocol["visual_hz"] = 10
        with self.assertRaisesRegex(RuntimeError, "RGB representation"):
            validate_frozen_selection(protocol)
        protocol["visual_representation"] = "fractional_rgb_v21"
        selected, hz = validate_frozen_selection(protocol)
        self.assertEqual((selected.method, hz), ("log_area", 10))
        protocol["selected_v2"]["method"] = "relative_radius"
        protocol["selected_v2"]["full_scale_rate_per_s"] = 0.25
        with self.assertRaisesRegex(RuntimeError, "V2.1 fractional RGB"):
            validate_frozen_selection(protocol)
        protocol["selected_v2"]["method"] = "log_area"
        protocol["selected_v2"]["full_scale_rate_per_s"] = 0.5
        protocol["visual_hz"] = 20
        with self.assertRaisesRegex(RuntimeError, "10 Hz"):
            validate_frozen_selection(protocol)

    def test_v21_selected_material_and_hashes_match_repository(self):
        protocol = json.loads((ROOT / "config/p8_r3_v21_official_v1.json").read_text())
        self.assertEqual(protocol["internal_gate_status"], "PASS")
        self.assertEqual(protocol["visual_hz"], 10)
        self.assertEqual(protocol["selected_v2"], {
            "method": "log_area", "full_scale_rate_per_s": 0.5,
            "area_epsilon": 1e-6, "max_gap_ms": 150, "window_ms": 200,
        })
        self.assertEqual(protocol["scenario_seeds"], [885421, 885422, 885423])
        self.assertEqual(protocol["visual_representation"], "fractional_rgb_v21")
        scenario = json.loads((ROOT / protocol["scenario_config_path"]).read_text())
        self.assertEqual((scenario["image_width_px"], scenario["image_height_px"]),
                         (65, 33))
        self.assertEqual(scenario["safety_boundary_center_distance_m"], 0.25)
        frozen_files = {
            "graph_manifest_sha256": "data/manifests/controller-graph-v2.json",
            "fractional_rgb_module_sha256": "microduck_connectome/fractional_rgb_v21.py",
            "looming_v2_module_sha256": "microduck_connectome/looming_v2.py",
            "internal_gate_artifact_sha256": protocol["internal_gate_artifact_path"],
            "initial_internal_gate_artifact_sha256": protocol["initial_internal_gate_artifact_path"],
            "internal_gate_manifest_sha256": protocol["internal_gate_manifest_path"],
            "sampling_gate_manifest_sha256": protocol["sampling_gate_manifest_path"],
            "scenario_config_sha256": protocol["scenario_config_path"],
            "visual_scheduler_config_sha256": protocol["visual_scheduler_config_path"],
        }
        for key, relative in frozen_files.items():
            with self.subTest(key=key):
                self.assertEqual(
                    hashlib.sha256(subprocess.check_output(
                        ["git", "-C", str(ROOT), "show", f"HEAD:{relative}"])).hexdigest(),
                    protocol[key])
        files = {"neural_model": "neural_model_v1.json",
                 "sensory_mapping": "sensory_mapping_v1.json",
                 "dn_readout": "dn_readout_v1.json",
                 "escape_decoder": "escape_decoder_v1.json",
                 "safety_envelope": "safety_envelope_v1.json",
                 "watchdog": "watchdog_v1.json",
                 "motion_adapter": "motion_adapter_v1.json",
                 "scheduler": "scheduler_v1.json", "telemetry": "telemetry_v1.json"}
        for key, relative in files.items():
            with self.subTest(config=key):
                self.assertEqual(hashlib.sha256(subprocess.check_output(
                    ["git", "-C", str(ROOT), "show", f"HEAD:config/{relative}"])).hexdigest(),
                    protocol["config_sha256"][key])
        versions = json.loads((ROOT / "config/versions.json").read_text())
        self.assertEqual(protocol["microduck_commit"], versions["upstream"]["microduck"]["commit"])
        self.assertEqual(protocol["microduck_rl_commit"], versions["upstream"]["microduck_rl"]["commit"])

    def test_v21_frozen_preflight_rejects_source_hash_and_output_drift(self):
        protocol = json.loads((ROOT / "config/p8_r3_v21_official_v1.json").read_text())
        protocol["source_freeze_sha"] = subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
        validate_frozen_material(ROOT, protocol)
        validate_frozen_output_dir(protocol, Path(protocol["frozen_output_dir"]))
        drift = copy.deepcopy(protocol)
        drift["internal_gate_artifact_sha256"] = "0" * 64
        with self.assertRaisesRegex(RuntimeError, "internal_gate_artifact_sha256 hash mismatch"):
            validate_frozen_material(ROOT, drift)
        drift = copy.deepcopy(protocol)
        drift["source_freeze_sha"] = "0" * 40
        with self.assertRaisesRegex(RuntimeError, "source SHA"):
            validate_frozen_material(ROOT, drift)
        with self.assertRaisesRegex(RuntimeError, "frozen raw directory"):
            validate_frozen_output_dir(protocol, Path(protocol["frozen_output_dir"] + "-replacement"))


class ArtifactTests(unittest.TestCase):
    def test_retained_raw_artifacts_must_match_hash_and_folder(self):
        import hashlib

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            summary = {}
            for key in ("trace_artifact", "events_artifact", "neural_ledger_artifact",
                        "visual_frame_artifact"):
                path = folder / f"{key}.jsonl"
                path.write_text('{"event":1}\n')
                summary[key] = {"path": str(path), "record_count": 1,
                                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            validate_trial_artifacts(summary, folder)
            summary["visual_frame_artifact"]["sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                validate_trial_artifacts(summary, folder)


class CadenceTests(unittest.TestCase):
    def test_frozen_visual_rates_on_50hz_scheduler_ticks(self):
        ticks = [index * 20_000_000 for index in range(16)]
        for hz, expected in (
            (10, [0, 100, 200, 300]),
            (20, [0, 60, 100, 160, 200, 260, 300]),
            (25, [0, 40, 80, 120, 160, 200, 240, 280]),
        ):
            with self.subTest(hz=hz):
                cadence = VisualCadence(hz)
                observed = [tick // 1_000_000 for tick in ticks if cadence.due(tick)]
                self.assertEqual(observed, expected)


class NeuralChainIntegrationTests(unittest.TestCase):
    def make_chain(self):
        chain = LoomingChain.__new__(LoomingChain)
        chain.neural_sequence = 0
        chain.mapper = SimpleNamespace(
            map_channels=lambda frame, now_ns: {"lplc2_left": frame["looming"],
                                                  "lplc2_right": frame["looming"]},
            build_external=lambda frame, now_ns: {1: frame["looming"]})
        chain.runtime_index = {1: 0}
        chain.dn_ids = (1,)
        values = iter((0.0, 0.6, 0.0, 0.0))
        chain.runtime = SimpleNamespace(step=lambda external: {
            "spikes": (True,), "healthy": True})
        chain.aggregator = SimpleNamespace(update=lambda spikes, *, timestamp_ns,
                                           sequence, runtime_healthy: {
            "timestamp_ns": timestamp_ns, "sequence": sequence,
            "steering_left": 0.0, "steering_right": 0.0,
            "escape": next(values), "runtime_healthy": runtime_healthy})
        chain.steering = SimpleNamespace(decode=lambda readout: None)
        chain.escape = SimpleNamespace(apply=lambda readout, steering: make_behavior_intent(
            timestamp_ns=readout["timestamp_ns"], sequence=readout["sequence"],
            stop=readout["escape"] >= 0.5, confidence=readout["escape"]))
        chain.safety = SafetyClamp()
        chain.neural_stop_latch = NeuralStopIntentLatch(escape_threshold=0.5)
        chain.arbiter = NeuralStopMotionArbiter()
        chain.graph_identity = "test-graph"
        chain.scenario = "stop"
        chain.neural_ledger = []
        watchdog = ControllerWatchdog(ROOT / "config/watchdog_v1.json")
        return chain, watchdog

    @staticmethod
    def sample(index, now_ns):
        return {"timestamp_ns": now_ns, "frame_id": index, "valid": True,
                "looming": 0.0 if index == 1 else 1.0,
                "proximity_left": 0.0, "proximity_center": 0.0,
                "proximity_right": 0.0}

    def test_priming_escape_and_post_ack_held_stop_follow_one_safety_path(self):
        chain, watchdog = self.make_chain()
        outputs = []
        for index, now_ns in enumerate((100, 120, 140, 160), start=1):
            update = chain.neural(self.sample(index, now_ns), now_ns)
            self.assertTrue(watchdog.observe_neural(update.readout))
            self.assertTrue(watchdog.observe_behavior(update.behavior_intent))
            output = watchdog.tick(now_ns=now_ns + 1, output_sequence=index)
            outputs.append(output)
            if index == 2:
                self.assertEqual(chain.arbiter.publish(
                    output, lambda _output: "robot_stop_refreshed"), "robot_stop_refreshed")
                confirmed = chain.neural_stop_latch.confirm(
                    output=output, transport_result="robot_stop_refreshed",
                    ack_ns=122, source_neural_sequence=2, source_intent_stop=True)
                self.assertEqual(confirmed.first_healthy_stop_ack_ns, 122)
            elif index > 2:
                self.assertEqual(chain.arbiter.publish(
                    output, lambda _output: "robot_stop_refreshed"), "robot_stop_refreshed")
        self.assertFalse(outputs[0]["intent"]["stop"])
        self.assertTrue(all(item["watchdog_state"] == "healthy" for item in outputs))
        self.assertTrue(all(item["intent"]["stop"] for item in outputs[1:]))
        self.assertEqual(chain.arbiter.latch_reason, "healthy_neural_escape")
        self.assertFalse(chain.neural_ledger[2]["raw_decoder_stop"])
        self.assertTrue(chain.neural_ledger[2]["held_nonstop_decoder_output"])
        self.assertEqual([row["perception_timestamp_ns"] for row in chain.neural_ledger[2:]],
                         [140, 160])
        self.assertTrue(all(row["post_safety_stop"] for row in chain.neural_ledger[2:]))
        with self.assertRaises(MotionLatched):
            chain.arbiter.move(lambda: None)

    def test_fault_before_ack_takes_priority_over_harness_neural_candidate(self):
        chain, watchdog = self.make_chain()
        fault = FaultStopLatch()
        for index, now_ns in ((1, 100), (2, 120)):
            update = chain.neural(self.sample(index, now_ns), now_ns)
            self.assertTrue(watchdog.observe_neural(update.readout))
            self.assertTrue(watchdog.observe_behavior(update.behavior_intent))
        self.assertEqual(chain.arbiter.latch_reason, "healthy_neural_escape")
        fault.latch("camera_loss", detected_ns=121, planned=True)
        watchdog.latch_fault(fault.snapshot().reason)
        chain.arbiter.latch("fault_camera_loss")
        output = watchdog.tick(now_ns=122, output_sequence=1)
        self.assertEqual(output["stale_reason"], "fault_camera_loss")
        self.assertEqual(chain.arbiter.latch_reason, "fault_camera_loss")
        record = chain.neural_stop_latch.confirm(
            output=output, transport_result="robot_stop_refreshed",
            ack_ns=123, source_neural_sequence=2, source_intent_stop=True)
        self.assertIsNone(record.first_healthy_stop_ack_ns)


if __name__ == "__main__":
    unittest.main()
