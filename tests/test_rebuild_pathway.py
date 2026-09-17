"""Source adapter tests use tiny real Feather files with independently pinned hashes."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import pyarrow as pa
import pyarrow.feather as feather

from microduck_connectome.graph_cache import load_graph
from microduck_connectome.rebuild_pathway import ROOT, FIELDS, digest, rebuild


class RebuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.annotations = self.root / "annotations.feather"
        self.weights = self.root / "weights.feather"
        rows = [
            [1, "LC10a", "seed", "L", None, "optic", "brain"],
            [2, "DNa02", "out", "R", None, "descending_neuron", None],
            [3, "intermediate", "", "M", None, "cb_intrinsic", "brain"],
            [4, "deadend", None, "", None, "vnc_intrinsic", "T1"],
        ]
        self.table = pa.table({name: pa.array([r[i] for r in rows], type=pa.int64() if i == 0 else pa.string())
                               for i, name in enumerate(FIELDS)})
        feather.write_feather(self.table, self.annotations)
        # 99 is unannotated but lies on a two-hop route; it must not enter graph.
        edges = [(1, 3, 4), (3, 2, 5), (1, 99, 6), (99, 2, 7),
                 (1, 4, 8), (3, 100, 15), (2, 101, 9)]
        self.edges = edges
        self.write_weights(edges)
        self.manifest = {"dataset": "male-cns:v1.0", "confidence_filter": "fixture no filter",
                         "annotations": {"sha256": digest(self.annotations), "expected_rows": 4},
                         "weights": {"sha256": digest(self.weights), "expected_rows": len(edges)}}
        self.config = json.loads((ROOT / "config/pathway-lc10a-dna02-v1.json").read_text())

    def write_weights(self, edges):
        feather.write_feather(pa.table({name: pa.array([r[i] for r in edges], type=pa.int64())
                                        for i, name in enumerate(["body_pre", "body_post", "weight"])}),
                              self.weights, chunksize=2)

    def run_build(self, name="out"):
        return rebuild(self.annotations, self.weights, self.manifest, self.config, "a" * 40, self.root / name)

    def test_selection_denominator_metadata_and_repeatability(self):
        report = self.run_build()
        self.assertEqual(report["selected_body_ids"], [1, 2, 3])
        self.assertEqual(report["intermediate_body_ids"], [3])
        self.assertEqual(report["stage_counts"]["unannotated_overlap_ids"], 1)
        self.assertEqual(report["candidate_inventory"]["MDN"]["status"], "absent_exact_type")
        graph = load_graph(self.root / "out/graphs", report["graph"]["cache_key"])
        self.assertEqual({r["body_id"]: r["raw_weight_sum"] for r in graph["full_outgoing_sums"]},
                         {1: 18, 2: 9, 3: 20})
        self.assertEqual([e["normalized_weight"] for e in graph["edges"]], [4 / 18, 5 / 20])
        self.assertEqual(report["source_annotation_records"][2]["somaSide"], "M")
        self.assertIsNone(graph["annotations"]["records"][2]["soma_side"])
        self.assertEqual(report, self.run_build("repeat"))
        self.assertEqual((self.root / "out/pathway-report.json").read_bytes(),
                         (self.root / "repeat/pathway-report.json").read_bytes())
        metadata = json.loads((self.root / "out/source-metadata.json").read_text())
        self.assertEqual(metadata["extraction_commit"], "a" * 40)
        self.assertEqual(metadata["records"], report["source_annotation_records"])
        self.assertEqual(digest(self.root / "out/source-metadata.json"), report["source_metadata"]["sha256"])

    def test_hash_and_row_count_fail_closed(self):
        self.manifest["weights"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.run_build()
        self.manifest["weights"]["sha256"] = digest(self.weights)
        self.manifest["weights"]["expected_rows"] += 1
        with self.assertRaisesRegex(ValueError, "row count"):
            self.run_build()

    def test_invalid_outside_selected_rows_rejected(self):
        self.write_weights(self.edges + [(999, 1000, 0)])
        self.manifest["weights"] = {"sha256": digest(self.weights), "expected_rows": 8}
        with self.assertRaisesRegex(ValueError, "nonpositive"):
            self.run_build()

    def test_duplicate_selected_edge_rejected(self):
        self.write_weights(self.edges + [self.edges[0]])
        self.manifest["weights"] = {"sha256": digest(self.weights), "expected_rows": 8}
        with self.assertRaisesRegex(ValueError, "duplicates"):
            self.run_build()

    def test_absent_required_population(self):
        self.config["seed_type"] = "absent"
        with self.assertRaisesRegex(ValueError, "population absent"):
            self.run_build()

    def test_config_semantics_cannot_silently_change(self):
        self.config["normalization"] = "induced only"
        with self.assertRaisesRegex(ValueError, "semantics"):
            self.run_build()

    def test_duplicate_annotation_ids_rejected(self):
        feather.write_feather(pa.concat_tables([self.table, self.table.slice(0, 1)]), self.annotations)
        self.manifest["annotations"] = {"sha256": digest(self.annotations), "expected_rows": 5}
        with self.assertRaisesRegex(ValueError, "body IDs"):
            self.run_build()


if __name__ == "__main__":
    unittest.main()
