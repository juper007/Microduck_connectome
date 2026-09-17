"""Small offline fixtures for reproducible evidence and integrity failures."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from microduck_connectome.graph_cache import GraphCacheError, store_graph
from microduck_connectome.query_pathway_report import _canonical, _digest, query_report
from test_connectivity import annotations, edge, extract


class QueryReportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.path = self.base / "pathway-report.json"
        config = {"seed_type": "synthetic-1", "readout_type": "synthetic-4"}
        graph = extract([edge(1, 2), edge(2, 4), edge(1, 3), edge(3, 4), edge(1, 99)],
                        annotations((1, 2, 3, 4)),
                        query_or_extraction_config=_canonical(config).decode())
        key = store_graph(self.base / "graphs", graph)
        records = [{"bodyId": 1, "superclass": "cb_intrinsic", "somaNeuromere": None},
                   {"bodyId": 2, "superclass": "vnc_intrinsic", "somaNeuromere": "synthetic-T"},
                   {"bodyId": 3}, {"bodyId": 4, "superclass": "descending_neuron"}]
        metadata = {"dataset": "male-cns:v1.0", "source_sha256": "d" * 64,
                    "extraction_commit": "c" * 40,
                    "source_note": "Synthetic source", "records": records}
        raw_metadata = _canonical(metadata) + b"\n"
        (self.base / "source-metadata.json").write_bytes(raw_metadata)
        manifest = {"annotations": {"sha256": "d" * 64}, "weights": {"sha256": "b" * 64}}
        self.report = {
            "schema_version": "pathway-report-v1", "dataset": "male-cns:v1.0",
            "code_commit": "c" * 40, "source_manifest": manifest,
            "source_manifest_sha256": _digest(_canonical(manifest)),
            "selection_config": config, "selection_config_sha256": _digest(_canonical(config)),
            "selected_body_ids": [1, 2, 3, 4], "source_annotation_records": records,
            "graph": {"cache_key": key, "relative_path": f"graphs/{key}.json", "manifest": graph["manifest"]},
            "source_metadata": {"relative_path": "source-metadata.json", "sha256": _digest(raw_metadata)},
        }
        self.write_report()

    def write_report(self, report=None):
        self.path.write_bytes(_canonical(self.report if report is None else report) + b"\n")

    def query(self):
        return query_report(self.path, code_commit="e" * 40)

    def test_query_results_and_byte_identical_cli_runs(self):
        result = self.query()
        self.assertEqual(result["path_query"]["pairs"][0]["shortest_path"], [1, 2, 4])
        self.assertEqual(result["path_query"]["simple_two_hop_paths"], [[1, 2, 4], [1, 3, 4]])
        self.assertEqual(result["path_query"]["simple_two_hop_path_count"], 2)
        self.assertEqual(result["descending"]["body_ids"], (4,))
        self.assertEqual(result["descending"]["unknown_body_ids"], (3,))
        self.assertEqual(result["cross_superclass"]["cb_intrinsic_to_vnc_intrinsic"]["edge_count"], 1)
        self.assertEqual(result["cross_superclass"]["vnc_intrinsic_to_cb_intrinsic"]["edge_count"], 0)
        self.assertEqual(result["soma_neuromere_coverage"]["unknown_body_ids"], [1, 3, 4])
        self.assertEqual(result["soma_neuromere_coverage"]["known_source_label_counts"], {"synthetic-T": 1})
        self.assertEqual(result["input_report_sha256"], _digest(self.path.read_bytes()))
        outputs = [self.base / "out1.json", self.base / "out2.json"]
        for output in outputs:
            subprocess.run([sys.executable, "-m", "microduck_connectome.query_pathway_report",
                            "--report", str(self.path), "--output", str(output),
                            "--code-commit", "e" * 40], check=True, capture_output=True)
        self.assertEqual(outputs[0].read_bytes(), outputs[1].read_bytes())

    def test_metadata_hash_and_graph_integrity_fail_closed(self):
        metadata_path = self.base / "source-metadata.json"
        original = metadata_path.read_bytes()
        metadata_path.write_bytes(original + b" ")
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            self.query()
        metadata_path.write_bytes(original)
        graph_path = self.base / self.report["graph"]["relative_path"]
        graph = json.loads(graph_path.read_bytes())
        graph["edges"][0]["raw_synapse_weight"] += 1
        graph_path.write_bytes(_canonical(graph))
        with self.assertRaises(GraphCacheError):
            self.query()

    def test_consistency_checks_fail_closed(self):
        changes = [("selected_body_ids", [1]), ("dataset", "another-dataset"),
                   ("code_commit", "f" * 40), ("selection_config_sha256", "f" * 64),
                   ("source_manifest_sha256", "f" * 64), ("source_annotation_records", [])]
        for key, value in changes:
            changed = copy.deepcopy(self.report)
            changed[key] = value
            self.write_report(changed)
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.query()
        self.write_report()
        for sha in (None, "HEAD", "E" * 40, "e" * 39):
            with self.assertRaises(ValueError):
                query_report(self.path, code_commit=sha)

    def test_relative_paths_and_overwrite_protection(self):
        for section in ("graph", "source_metadata"):
            for path in ("../escape.json", "/absolute.json", "C:/absolute.json",
                         "graphs/../escape.json", "graphs\\escape.json", "./source-metadata.json"):
                changed = copy.deepcopy(self.report)
                changed[section]["relative_path"] = path
                self.write_report(changed)
                with self.subTest(section=section, path=path), self.assertRaises(ValueError):
                    self.query()
        self.write_report()
        original = self.path.read_bytes()
        run = subprocess.run([sys.executable, "-m", "microduck_connectome.query_pathway_report",
                              "--report", str(self.path), "--output", str(self.path),
                              "--code-commit", "e" * 40], capture_output=True)
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(self.path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
