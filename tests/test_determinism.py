import hashlib
import json
from pathlib import Path
import unittest

from microduck_connectome.determinism import replay_trace, trace_sha256, verify_fixed_replay
from microduck_connectome.neural_model import model_config_sha256

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config" / "neural_model_v1.json").read_text(encoding="utf-8"))
EVIDENCE_PATH = ROOT / "docs" / "evidence" / "p3-05" / "determinism-v1.json"
EXPECTED_HASH = "e03ac3bbe892f45b2d2797a4618fa1de952ca29b58c7b07b879c7353cafaa702"


def canonical_sha256(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class StubGraph:
    body_ids = (101, 102, 103)

    def edges(self):
        return (
            {"source_body_id": 101, "target_body_id": 102, "normalized_weight": 0.5},
            {"source_body_id": 102, "target_body_id": 103, "normalized_weight": 0.25},
        )


TRACE = ({101: 0.4}, {101: 0.7}, {102: 0.6}, {}, {103: 0.2})


class DeterminismTests(unittest.TestCase):
    def test_fixed_replay_is_exact_and_matches_versioned_hash(self):
        report = verify_fixed_replay(StubGraph(), CONFIG, TRACE)
        self.assertTrue(report["exact_replay_equal"])
        self.assertEqual(report["steps"], 5)
        self.assertEqual(report["body_ids"], [101, 102, 103])
        self.assertEqual(report["trace_sha256"], EXPECTED_HASH)

    def test_committed_evidence_matches_executable_fixture(self):
        evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
        graph_fixture = {"body_ids": list(StubGraph.body_ids), "edges": list(StubGraph().edges())}
        json_trace = [{str(key): value for key, value in step.items()} for step in TRACE]
        report = verify_fixed_replay(StubGraph(), CONFIG, TRACE)

        self.assertEqual(evidence["dataset"], "male-cns:v1.0")
        self.assertEqual(evidence["fixture_kind"], "synthetic_contract_fixture")
        self.assertEqual(evidence["neural_config_sha256"], model_config_sha256(CONFIG))
        self.assertEqual(evidence["runtime_backend"], "python-cpu-float32-contract")
        self.assertEqual(evidence["random_seed"], "none")
        self.assertEqual(evidence["graph"], graph_fixture)
        self.assertEqual(evidence["trace"], json_trace)
        self.assertEqual(evidence["graph_fixture_sha256"], canonical_sha256(graph_fixture))
        self.assertEqual(evidence["input_trace_sha256"], canonical_sha256(json_trace))
        self.assertEqual(evidence["trace_sha256"], report["trace_sha256"])
        self.assertEqual(evidence["steps"], report["steps"])
        self.assertEqual(evidence["graph"]["body_ids"], report["body_ids"])
        self.assertTrue(evidence["exact_replay_equal"])
        self.assertRegex(evidence["producer_commit"], r"^[0-9a-f]{40}$")
        self.assertRegex(evidence["base_runtime_commit"], r"^[0-9a-f]{40}$")

    def test_two_fresh_replays_are_structurally_identical(self):
        first = replay_trace(StubGraph(), CONFIG, TRACE)
        second = replay_trace(StubGraph(), CONFIG, TRACE)
        self.assertEqual(first, second)
        self.assertEqual(trace_sha256(first), trace_sha256(second))
        self.assertTrue(all(snapshot["healthy"] for snapshot in first))

    def test_changed_valid_trace_changes_hash(self):
        changed = ({101: 0.4}, {101: 0.6}, {102: 0.6}, {}, {103: 0.2})
        self.assertNotEqual(
            trace_sha256(replay_trace(StubGraph(), CONFIG, TRACE)),
            trace_sha256(replay_trace(StubGraph(), CONFIG, changed)),
        )

    def test_nonsequence_trace_is_rejected(self):
        with self.assertRaises(TypeError):
            replay_trace(StubGraph(), CONFIG, {101: 0.4})


if __name__ == "__main__":
    unittest.main()
