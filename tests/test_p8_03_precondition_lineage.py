"""Prospective robotd state lineage cannot hide a fresh deadman state."""

import json
from pathlib import Path
import queue
import tempfile
import time
import unittest
from unittest.mock import patch

from scripts.p8_03_precondition_lineage import (DurableStateLineage,
                                                 classify_observation)
from scripts.p6_telemetry_runtime_fixture import RobotStateSampler


def observation(index, source, received, *, requested=.07, applied=.07,
                limited=(), policy="walk"):
    return {"state_index": index, "previous_state_index": index - 1,
            "source_timestamp_ns": source,
            "previous_source_timestamp_ns": source - 20_000_000,
            "received_ns": received,
            "state": {"t_ns": source, "policy": policy,
                      "safety": {"fallen": False, "limp": False},
                      "move": {"requested": [requested, 0, 0],
                               "applied": [applied, 0, 0],
                               "limited_by": list(limited)}}}


class StateLineageTests(unittest.TestCase):
    def setUp(self):
        self.pre = observation(10, 1_000_000_000, 1_001_000_000,
                               requested=0, applied=0)
        self.options = {"pre_move_observation": self.pre,
                        "command_write_ns": 1_002_000_000,
                        "command_ack_ns": 1_004_000_000,
                        "command_accepted": True,
                        "source_clock_comparable": True,
                        "maximum_state_age_ns": 10_000_000,
                        "minimum_applied_vx_mps": .04,
                        "allowed_policies": frozenset({"walk"})}

    def test_host_received_after_ack_does_not_prove_command_effect(self):
        stale = observation(11, 1_001_500_000, 1_005_000_000,
                            requested=0, applied=0, limited=("deadman",))
        result = classify_observation(stale, **self.options)
        self.assertFalse(result["causal_post_command"])
        self.assertEqual(result["qualification_state"], "TRANSIENT")
        self.assertTrue(result["deadman"])

    def test_clock_comparability_must_be_proven(self):
        current = observation(11, 1_003_000_000, 1_005_000_000)
        options = {**self.options, "source_clock_comparable": False}
        self.assertEqual(classify_observation(current, **options)["qualification_state"],
                         "TRANSIENT")

    def test_newer_clean_state_is_only_a_state_candidate(self):
        current = observation(11, 1_003_000_000, 1_005_000_000)
        result = classify_observation(current, **self.options)
        self.assertTrue(result["causal_post_command"])
        self.assertEqual(result["qualification_state"], "QUALIFYING")

    def test_fresh_deadman_state_is_invalid_even_if_later_clean(self):
        deadman = observation(11, 1_003_000_000, 1_005_000_000,
                              applied=0, limited=("deadman",))
        self.assertEqual(classify_observation(deadman, **self.options)[
            "qualification_state"], "INVALID")
        clean = observation(12, 1_023_000_000, 1_025_000_000)
        self.assertEqual(classify_observation(clean, **self.options)[
            "qualification_state"], "QUALIFYING")

    def test_source_nonadvance_and_index_regression(self):
        repeated = observation(11, 1_000_000_000, 1_005_000_000)
        self.assertEqual(classify_observation(repeated, **self.options)[
            "qualification_state"], "TRANSIENT")
        with self.assertRaisesRegex(ValueError, "regressed"):
            classify_observation(observation(9, 1_003_000_000, 1_005_000_000),
                                 **self.options)

    def test_durable_journal_preserves_all_rows_and_exclusive_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lineage.jsonl"
            with DurableStateLineage(path) as journal:
                journal.append({"kind": "moving_acquisition_start", "timestamp_ns": 1})
                journal.append(observation(11, 1_003_000_000, 1_005_000_000))
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([row["kind"] for row in rows],
                             ["moving_acquisition_start", "state_observation"])
            self.assertEqual(rows[1]["state"]["move"]["applied"], [.07, 0, 0])
            with self.assertRaises(FileExistsError):
                DurableStateLineage(path)

    def test_sampler_callback_and_atomic_snapshot(self):
        class FakeClient:
            def __init__(self, *_args, **_kwargs):
                self.items = queue.Queue()
                self.closed = False

            def connect(self):
                pass

            def state(self, *, hz):
                self.assert_hz = hz
                return self.items.get(timeout=1)

            def close(self):
                self.closed = True
                self.items.put(observation(0, 0, 0)["state"])

        seen = []
        with patch("scripts.p6_telemetry_runtime_fixture.RobotdClient", FakeClient):
            sampler = RobotStateSampler("unused", on_state=seen.append)
            try:
                self.assertIsNone(sampler.snapshot())
                sampler.client.items.put(observation(0, 1_000_000_000, 0)["state"])
                deadline = time.monotonic() + 1
                while sampler.snapshot() is None and time.monotonic() < deadline:
                    time.sleep(.001)
                first = sampler.snapshot()
                self.assertEqual(first["state_index"], 0)
                self.assertEqual(seen[0], first)
                self.assertEqual(sampler.after_snapshot(0), first)
                first["state"]["move"]["applied"][0] = 999
                self.assertNotEqual(sampler.snapshot()["state"]["move"]["applied"][0], 999)
            finally:
                sampler.close()


if __name__ == "__main__":
    unittest.main()
