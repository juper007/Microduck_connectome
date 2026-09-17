"""Synthetic connectivity fixtures; no biological population/pathway evidence."""

import copy
import hashlib
import json
import unittest

from microduck_connectome.annotations import normalize_annotations
from microduck_connectome.connectivity import ConnectivityError, extract_connectivity


def annotations(ids=(1, 2, 3)):
    return normalize_annotations(
        [{"bodyId": value, "type": None if value == 3 else f"synthetic-{value}",
          "instance": None, "somaSide": None, "class": None} for value in ids],
        dataset="male-cns:v1.0", source_note="Synthetic test fixture",
        extraction_commit="a" * 40)


def edge(pre=1, post=2, weight=3):
    return {"body_pre": pre, "body_post": post, "weight": weight}


def extract(rows=None, annotation_artifact=None, **changes):
    metadata = dict(dataset="male-cns:v1.0", source_sha256="b" * 64,
                    confidence_filter="Synthetic: all rows retained, no weight threshold",
                    extraction_commit="c" * 40, created_utc="2026-09-17T00:00:00Z",
                    query_or_extraction_config="Synthetic all-outgoing source fixture",
                    seed_populations=["synthetic-seed"], readout_populations=[],
                    selection_rules="Synthetic explicit annotation body ID set")
    metadata.update(changes)
    return extract_connectivity(annotations() if annotation_artifact is None else annotation_artifact,
                                [edge()] if rows is None else rows, **metadata)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True, allow_nan=False).encode()).hexdigest()


class ConnectivityTests(unittest.TestCase):
    def test_external_targets_count_without_annotations_and_isolates_remain(self):
        result = extract([edge(1, 2, 3), edge(1, 99, 7), edge(2, 3, 4)])
        self.assertEqual(result["full_outgoing_sums"], [
            {"body_id": 1, "raw_weight_sum": 10}, {"body_id": 2, "raw_weight_sum": 4},
            {"body_id": 3, "raw_weight_sum": 0}])
        self.assertEqual(result["edges"][0], {
            "source_body_id": 1, "target_body_id": 2, "raw_synapse_weight": 3,
            "normalized_weight": .3, "source_type": "synthetic-1",
            "target_type": "synthetic-2", "provenance_dataset": "male-cns:v1.0"})
        self.assertIsNone(result["edges"][1]["target_type"])
        self.assertEqual(result["manifest"]["node_count"], 3)
        self.assertEqual(result["manifest"]["edge_count"], 2)
        self.assertEqual(result["manifest"]["raw_weight_sum"], 7)
        self.assertEqual(result["manifest"]["source_raw_weight_sum"], 14)

    def test_subgraph_does_not_renormalize(self):
        rows = [edge(1, 2, 3), edge(1, 3, 2), edge(1, 99, 5), edge(2, 3, 4)]
        small = extract(rows, annotations((1, 2)))
        large = extract(rows, annotations((1, 2, 3, 99)))
        self.assertEqual(small["edges"][0], large["edges"][0])
        self.assertEqual(small["edges"][0]["normalized_weight"], .3)
        self.assertEqual(small["full_outgoing_sums"][0], large["full_outgoing_sums"][0])

    def test_order_independent_and_no_input_aliasing(self):
        rows = [edge(2, 1, 2), edge(1, 99, 7), edge(1, 2, 3)]
        artifact = annotations((3, 1, 2))
        original = copy.deepcopy((rows, artifact))
        result = extract(rows, artifact)
        reversed_artifact = copy.deepcopy(artifact)
        reversed_artifact["records"].reverse()
        self.assertEqual(result, extract(tuple(reversed(rows)), reversed_artifact))
        self.assertEqual((rows, artifact), original)
        result["annotations"]["records"][0]["cell_type"] = "changed"
        result["edges"][0]["raw_synapse_weight"] = 99
        self.assertEqual((rows, artifact), original)

    def test_exact_weights_above_float_and_int64_precision(self):
        weight = 2 ** 63 + 123
        result = extract([edge(1, 2, weight), edge(1, 99, weight)])
        self.assertEqual(result["edges"][0]["raw_synapse_weight"], weight)
        self.assertEqual(result["edges"][0]["normalized_weight"], .5)
        self.assertEqual(result["full_outgoing_sums"][0]["raw_weight_sum"], weight * 2)
        self.assertEqual(json.loads(json.dumps(result)), result)

    def test_maximum_body_ids_and_self_edges(self):
        maximum = 2 ** 63 - 1
        result = extract([edge(maximum, maximum, 1)], annotations((maximum,)))
        self.assertEqual(result["edges"][0]["source_body_id"], maximum)
        self.assertEqual(result["edges"][0]["normalized_weight"], 1.)

    def test_empty_graph_and_selected_nodes_without_edges(self):
        result = extract([], annotations(()))
        self.assertEqual(result["edges"], [])
        self.assertEqual(result["full_outgoing_sums"], [])
        self.assertEqual(result["manifest"]["node_count"], 0)
        self.assertEqual(result["manifest"]["raw_weight_sum"], 0)
        self.assertEqual(extract([])["manifest"]["node_count"], 3)
        self.assertEqual(extract([])["edges"], [])

    def test_unselected_sources_are_validated_and_counted(self):
        result = extract([edge(99, 1, 7), edge(99, 100, 8)])
        self.assertEqual(result["edges"], [])
        self.assertEqual(result["manifest"]["source_edge_count"], 2)
        self.assertTrue(all(row["raw_weight_sum"] == 0 for row in result["full_outgoing_sums"]))
        with self.assertRaises(ConnectivityError):
            extract([edge(99, 100, 0)])

    def test_hashes_and_required_manifest(self):
        rows = [edge(1, 99, 7), edge(1, 2, 3)]
        result = extract(rows)
        manifest = result["manifest"]
        for key in ("dataset", "extraction_tool_version", "query_or_extraction_config", "created_utc",
                    "node_count", "edge_count", "raw_weight_sum", "body_id_set_hash", "edge_table_hash",
                    "seed_populations", "readout_populations", "selection_rules", "confidence_filter"):
            self.assertIn(key, manifest)
        self.assertEqual(manifest["body_id_set_hash"], digest([1, 2, 3]))
        self.assertEqual(manifest["edge_table_hash"], digest(result["edges"]))
        self.assertEqual(manifest["source_edge_table_hash"], digest(list(reversed(rows))))
        self.assertEqual(manifest["annotation_artifact_hash"], digest(result["annotations"]))
        self.assertEqual(manifest["full_outgoing_sums_hash"], digest(result["full_outgoing_sums"]))
        changed = extract([edge(1, 99, 8), edge(1, 2, 3)])["manifest"]
        self.assertNotEqual(manifest["edge_table_hash"], changed["edge_table_hash"])
        self.assertNotEqual(manifest["full_outgoing_sums_hash"], changed["full_outgoing_sums_hash"])
        # Timestamp is caller-supplied provenance, not part of content table hashes.
        later = extract(rows, created_utc="2026-09-18T00:00:00Z")["manifest"]
        self.assertEqual(manifest["edge_table_hash"], later["edge_table_hash"])

    def test_invalid_ids_weights_and_duplicate_pairs(self):
        for key in ("body_pre", "body_post", "weight"):
            invalids = [True, False, None, "1", 1., 0, -1, [], {}, float("inf"), float("nan")]
            if key != "weight":
                invalids.append(2 ** 63)
            for value in invalids:
                row = edge()
                row[key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ConnectivityError):
                    extract([row])
        for rows in ([edge(), edge()], [edge(), edge(weight=4)], [edge(99, 100), edge(99, 100)]):
            with self.assertRaisesRegex(ConnectivityError, "duplicates"):
                extract(rows)

    def test_invalid_source_schema_and_containers(self):
        invalids = [None, [], "row", 5, dict(edge(), extra=1)]
        for key in edge():
            row = edge()
            del row[key]
            invalids.append(row)
        for row in invalids:
            with self.subTest(row=row), self.assertRaises(ConnectivityError):
                extract([row])
        for rows in ({}, "rows", iter([]), 5):
            with self.assertRaises(ConnectivityError):
                extract(rows)
        with self.assertRaises(ConnectivityError):
            extract_connectivity(annotations(), None, dataset="wrong", source_sha256="",
                                 confidence_filter="", extraction_commit="", created_utc="",
                                 query_or_extraction_config="", seed_populations=[],
                                 readout_populations=[], selection_rules="")

    def test_invalid_provenance(self):
        cases = {
            "dataset": ["male-cns:v0.9", None, ""],
            "source_sha256": [None, "a" * 63, "A" * 64, "z" * 64, "a" * 64 + "\n"],
            "extraction_commit": ["main", "A" * 40, "a" * 39, None],
            "created_utc": [None, "2026-09-17", "2026-02-30T00:00:00Z", "2026-09-17T24:00:00Z",
                            "2026-09-17T00:00:00+00:00"],
        }
        for field in ("confidence_filter", "query_or_extraction_config", "selection_rules"):
            cases[field] = [None, "", "  ", 1, "\ud800"]
        for field in ("seed_populations", "readout_populations"):
            cases[field] = [None, "name", {}, ["a", "a"], [""], [1], ["\ud800"]]
        for field, invalids in cases.items():
            for value in invalids:
                with self.subTest(field=field, value=value), self.assertRaises(ConnectivityError):
                    extract(**{field: value})

    def test_annotation_artifact_is_revalidated(self):
        for key, value in (("dataset", "wrong"), ("schema_version", "annotation-v2"),
                           ("source_note", ""), ("extraction_commit", "main"), ("records", {})):
            invalid = annotations()
            invalid[key] = value
            with self.subTest(key=key), self.assertRaises(ConnectivityError):
                extract(annotation_artifact=invalid)
        invalid = annotations()
        invalid["records"].append(invalid["records"][0])
        with self.assertRaises(ConnectivityError):
            extract(annotation_artifact=invalid)

    def test_population_order_is_canonical(self):
        self.assertEqual(extract(seed_populations=["b", "a"]), extract(seed_populations=["a", "b"]))

    def test_unrepresentable_normalization_fails_explicitly(self):
        with self.assertRaisesRegex(ConnectivityError, "underflows"):
            extract([edge(1, 2, 1), edge(1, 99, 10 ** 400)])


if __name__ == "__main__":
    unittest.main()
