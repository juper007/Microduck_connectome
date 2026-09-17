"""Scientific provenance and selection regressions using real small Feather files."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

import pyarrow as pa
import pyarrow.feather as feather

from microduck_connectome.looming_evidence import build
from microduck_connectome.rebuild_pathway import FIELDS, canonical, digest


class LoomingEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.annotations = self.root / "annotations.feather"
        self.weights = self.root / "weights.feather"
        self.inventory = self.root / "inventory.json"
        raw = [(1, "LC4", "L"), (2, "LPLC2", "R"), (3, "DNp01", "L"),
               (4, "LC4-like", "R"), (5, "DNp01", "R"), (6, "LC4", None)]
        rows = [dict(zip(FIELDS, [body, typ, typ, side, None, None, None]))
                for body, typ, side in raw]
        feather.write_feather(pa.table({field: pa.array([r[field] for r in rows],
                              type=pa.int64() if field == "bodyId" else pa.string())
                              for field in FIELDS}), self.annotations)
        # Duplicate pair, reverse edge, lookalike type, unknown target, no-output input.
        edges = [(1, 3, 2), (1, 3, 3), (1, 99, 10), (2, 5, 7), (3, 1, 11), (4, 3, 13)]
        feather.write_feather(pa.table({field: pa.array([r[i] for r in edges], type=pa.int64())
                              for i, field in enumerate(("body_pre", "body_post", "weight"))}),
                              self.weights, chunksize=2)
        self.manifest = {"dataset": "male-cns:v1.0",
                         "annotations": {"sha256": digest(self.annotations), "expected_rows": len(rows)},
                         "weights": {"sha256": digest(self.weights), "expected_rows": len(edges)}}
        self.g1 = {"dataset": "male-cns:v1.0", "source_manifest": copy.deepcopy(self.manifest),
                   "candidate_inventory": {typ: {"source_records": [r for r in rows if r["type"] == typ]}
                                           for typ in ("LC4", "LPLC2", "DNp01")}}
        self.save_inventory()

    def save_inventory(self):
        self.inventory.write_bytes(canonical(self.g1))

    def run_build(self):
        return build(self.annotations, self.weights, self.manifest, self.inventory, "a" * 40)

    def test_direction_exact_type_duplicates_denominator_and_repeatability(self):
        result = self.run_build()
        self.assertEqual(result["direct_edges"], [{"body_pre": 1, "body_post": 3, "weight": 5},
                                                 {"body_pre": 2, "body_post": 5, "weight": 7}])
        self.assertEqual(result["all_outgoing_weight_by_input_type"], {"LC4": 15, "LPLC2": 7})
        self.assertEqual(result["selected_source_row_count"], 4)
        unknown = [r for r in result["summary_by_input_side_and_target"] if r["input_soma_side"] is None]
        self.assertEqual(len(unknown), 2)
        self.assertTrue(all(r["raw_synapse_weight"] == 0 for r in unknown))
        self.assertEqual(canonical(result), canonical(self.run_build()))

    def test_g1_identity_drift_fails(self):
        self.g1["candidate_inventory"]["LC4"]["source_records"][0]["somaSide"] = "R"
        self.save_inventory()
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            self.run_build()

    def test_source_hash_drift_fails(self):
        with self.weights.open("ab") as stream:
            stream.write(b"tampered")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            self.run_build()

    def test_source_row_count_drift_fails(self):
        self.manifest["weights"]["expected_rows"] += 1
        self.g1["source_manifest"] = copy.deepcopy(self.manifest)
        self.save_inventory()
        with self.assertRaisesRegex(ValueError, "row count mismatch"):
            self.run_build()

    def test_dataset_and_manifest_drift_fail(self):
        self.g1["dataset"] = "other"
        self.save_inventory()
        with self.assertRaisesRegex(ValueError, "dataset mismatch"):
            self.run_build()
        self.g1["dataset"] = "male-cns:v1.0"
        self.g1["source_manifest"]["weights"]["sha256"] = "0" * 64
        self.save_inventory()
        with self.assertRaisesRegex(ValueError, "manifest mismatch"):
            self.run_build()

    def test_invalid_producer_sha_fails(self):
        with self.assertRaisesRegex(ValueError, "Git SHA"):
            build(self.annotations, self.weights, self.manifest, self.inventory, "not-a-sha")


if __name__ == "__main__":
    unittest.main()
