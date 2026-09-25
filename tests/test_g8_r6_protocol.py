"""Prospective G8-R6 protocol identity and trial matrix checks."""

import json
from pathlib import Path
import unittest

from scripts.g8_r6_preregister import DEST, GRAPH, generate
from scripts.p7_no_target_batch_v4 import validate_control_specs


class G8R6ProtocolTest(unittest.TestCase):
    def test_committed_protocol_matches_generator(self):
        protocol = json.loads(DEST.read_text(encoding="utf-8"))
        self.assertEqual(protocol, generate())
        self.assertEqual(protocol["graph_key"], GRAPH)
        self.assertEqual(protocol["graph_sha256"], GRAPH)
        self.assertEqual(protocol["target_trial_count"], 120)
        self.assertEqual(len(protocol["target_trials"]), 120)
        self.assertEqual(len(validate_control_specs(protocol)), 40)
        seeds = [row["seed"] for key in ("target_trials", "no_target_trials")
                 for row in protocol[key]]
        self.assertEqual(len(seeds), len(set(seeds)))
        self.assertEqual(protocol["target_response"]["correct_direction_rate_min"], .9)
        self.assertEqual(protocol["no_target_false_turn"]["false_turn_rate_max"], .05)


if __name__ == "__main__":
    unittest.main()
