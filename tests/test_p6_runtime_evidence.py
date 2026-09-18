import json
from pathlib import Path
import re
import unittest


EVIDENCE = (
    Path(__file__).parents[1]
    / "docs"
    / "evidence"
    / "p6-01"
    / "thor-runtime-success-v1.json"
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class P6RuntimeEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_identity_and_pins(self):
        evidence = self.evidence
        self.assertEqual(evidence["task"], "P6-01")
        self.assertEqual(evidence["result"], "PASS")
        self.assertEqual(evidence["execution_target"], "Thor")
        self.assertEqual(
            evidence["pinned_upstream"]["microduck"],
            "344925c9f8fa031f85428a305b1e8ec2eaae29c1",
        )
        self.assertEqual(
            evidence["pinned_upstream"]["microduck_rl"],
            "cb70b792312d559a4da09064d92009079671815f",
        )
        self.assertTrue(evidence["upstream_checkouts_clean_before_and_after"])
        self.assertEqual(evidence["platform"]["architecture"], "aarch64")

    def test_two_real_healthy_cycles_and_clean_shutdowns(self):
        evidence = self.evidence
        self.assertEqual(evidence["launch_cycle_count"], 2)
        for key in ("launch_1", "launch_2"):
            cycle = evidence[key]
            self.assertTrue(cycle["simulator_started"])
            self.assertTrue(cycle["body_backend_reachable"])
            self.assertTrue(cycle["robotd_reachable"])
            self.assertEqual(cycle["robotd_health"], "healthy")
            self.assertEqual(cycle["control_loop_hz"], 50.0)
            self.assertEqual(cycle["missed_ticks"], 0)
            self.assertEqual(cycle["bus"], "ok")
            self.assertTrue(cycle["clean_shutdown"])
            self.assertTrue(cycle["port_released"])
            self.assertFalse(cycle["orphan_processes"])

    def test_runtime_artifact_hashes_and_scope(self):
        evidence = self.evidence
        hashes = evidence["runtime_artifacts"]
        hash_values = [value for key, value in hashes.items() if key.endswith("_sha256")]
        self.assertGreaterEqual(len(hash_values), 8)
        self.assertTrue(all(SHA256.fullmatch(value) for value in hash_values))
        self.assertTrue(evidence["preflight"]["ready"])
        self.assertTrue(evidence["preflight"]["all_checks_true"])
        self.assertFalse(evidence["hidden_patch_required"])
        self.assertFalse(evidence["p6_02_started"])
        self.assertTrue(evidence["acceptance_met"])


if __name__ == "__main__":
    unittest.main()
