"""Synthetic boundary tests: source labels here make no biological claims."""

import copy
import unittest

from microduck_connectome.graph import ConnectomeGraph
from microduck_connectome.pathway_queries import (
    cross_region_edges, descending_neurons, shortest_path,
)
from test_connectivity import annotations, edge, extract


def metadata():
    return {
        "dataset": "male-cns:v1.0", "source_sha256": "d" * 64,
        "extraction_commit": "c" * 40,
        "source_note": "Synthetic source only; not biological evidence",
        "records": [
            {"bodyId": 1, "superclass": "synthetic-descending", "somaNeuromere": "region-A",
             "type": "retained extra raw field"},
            {"bodyId": 2, "superclass": "synthetic-other", "somaNeuromere": "region-B"},
            {"bodyId": 3, "superclass": None, "somaNeuromere": None},
            {"bodyId": 4, "superclass": "synthetic-descending", "somaNeuromere": "region-B"},
            {"bodyId": 99, "superclass": "synthetic-descending", "somaNeuromere": "region-A"},
        ],
    }


class PathwayQueriesTests(unittest.TestCase):
    def setUp(self):
        self.rows = [edge(1, 3, 4), edge(3, 4, 4), edge(1, 2, 2), edge(2, 4, 3),
                     edge(1, 1, 1), edge(4, 1, 3), edge(1, 99, 3)]
        self.graph = ConnectomeGraph(extract(self.rows, annotations((5, 4, 3, 2, 1))))

    def path(self, **kwargs):
        return shortest_path(self.graph, 1, 4, max_hops=2, **kwargs)

    def test_shortest_directed_bounded_deterministic(self):
        self.assertEqual(self.path(), (1, 2, 4))
        self.assertIsNone(shortest_path(self.graph, 1, 4, max_hops=1))
        self.assertEqual(shortest_path(self.graph, 4, 1, max_hops=1), (4, 1))
        self.assertIsNone(shortest_path(self.graph, 4, 3, max_hops=1))
        self.assertIsNone(shortest_path(self.graph, 1, 5, max_hops=100))
        self.assertEqual(shortest_path(self.graph, 1, 1, max_hops=0), (1,))
        self.assertIsNone(shortest_path(self.graph, 1, 4, max_hops=0))
        reverse = ConnectomeGraph(extract(list(reversed(self.rows)), annotations((1, 2, 3, 4, 5))))
        self.assertEqual(shortest_path(reverse, 1, 4, max_hops=2), self.path())
        direct = ConnectomeGraph(extract(self.rows + [edge(1, 4, 1)], annotations((1, 2, 3, 4))))
        self.assertEqual(shortest_path(direct, 1, 4, max_hops=5), (1, 4))

    def test_restrictions_include_endpoints_unknown_type_and_weight(self):
        self.assertEqual(self.path(allowed_body_ids=[4, 3, 1, 3]), (1, 3, 4))
        self.assertEqual(self.path(min_raw_weight=3), (1, 3, 4))
        self.assertIsNone(self.path(min_raw_weight=5))
        self.assertEqual(self.path(allowed_types=["synthetic-1", None, "synthetic-4"]), (1, 3, 4))
        for changes in ({"allowed_types": []}, {"allowed_types": ["synthetic-2"]},
                        {"allowed_types": ["Synthetic-1", None, "synthetic-4"]},
                        {"allowed_body_ids": []}, {"allowed_body_ids": [2, 4]}):
            self.assertIsNone(self.path(**changes))
        self.assertIsNone(shortest_path(self.graph, 1, 1, max_hops=0, allowed_body_ids=[]))

    def test_path_input_errors_and_nested_view_boundary(self):
        for name, values in {
            "max_hops": [True, -1, 1.0, None], "min_raw_weight": [False, 0, -1, 1.0],
            "allowed_types": ["synthetic-1", 1, [""], [True], ["\ud800"]],
            "allowed_body_ids": ["1", 1, [1, True], [0], [2**63]],
        }.items():
            for value in values:
                kwargs = {"max_hops": 2, name: value}
                with self.subTest(name=name, value=repr(value)), self.assertRaises(ValueError):
                    shortest_path(self.graph, 1, 4, **kwargs)
        for source, target in [(True, 4), (1, False), (0, 4), (1, 2**63)]:
            with self.assertRaises(ValueError):
                shortest_path(self.graph, source, target, max_hops=2)
        with self.assertRaises(KeyError):
            self.path(allowed_body_ids=[1, 99])
        nested = self.graph.induced([1, 3, 4]).induced([1, 4])
        self.assertIsNone(shortest_path(nested, 1, 4, max_hops=100))
        for source, target in [(1, 3), (3, 4)]:
            with self.assertRaises(KeyError):
                shortest_path(nested, source, target, max_hops=2)
        with self.assertRaises(KeyError):
            shortest_path(nested, 1, 4, max_hops=2, allowed_body_ids=[1, 3, 4])

    def test_descending_exact_unknown_and_no_inference(self):
        result = descending_neurons(self.graph, metadata(), superclass_labels=["synthetic-descending"])
        self.assertEqual(result["body_ids"], (1, 4))
        self.assertEqual(result["unknown_body_ids"], (3, 5))
        self.assertEqual(result["root_key"], self.graph.root_key)
        self.assertEqual(descending_neurons(self.graph, metadata(),
                                          superclass_labels=["Synthetic-descending"])["body_ids"], ())
        changed = metadata()
        changed["records"][0].pop("superclass")
        changed["records"][0]["type"] = "DN-not-evidence"
        self.assertEqual(descending_neurons(self.graph, changed,
                                          superclass_labels=["synthetic-descending"])["unknown_body_ids"],
                         (1, 3, 5))

    def test_cross_region_direction_weights_and_class_scope(self):
        result = cross_region_edges(self.graph, metadata(), source_regions=["region-A"],
                                    target_regions=["region-B"])
        self.assertEqual(result["edges"], (self.graph.edge(1, 2),))
        self.assertEqual(result["edges"][0]["normalized_weight"], .2)
        self.assertEqual(result["source_body_ids"], (1,))
        self.assertEqual(result["target_body_ids"], (2, 4))
        self.assertEqual(result["unknown_body_ids"], (3, 5))
        reverse = cross_region_edges(self.graph, metadata(), source_regions=["region-B"],
                                     target_regions=["region-A"])
        self.assertEqual(reverse["edges"], (self.graph.edge(4, 1),))
        classes = cross_region_edges(self.graph, metadata(), region_field="superclass",
                                     source_regions=["synthetic-other"],
                                     target_regions=["synthetic-descending"])
        self.assertEqual(classes["edges"], (self.graph.edge(2, 4),))
        self.assertEqual(classes["region_field"], "superclass")

    def test_metadata_provenance_validation(self):
        bad_envelopes = [None, {}, {**metadata(), "dataset": "another-release"},
                         {**metadata(), "source_sha256": "x" * 64},
                         {**metadata(), "source_note": " "},
                         {**metadata(), "extraction_commit": "HEAD"},
                         {**metadata(), "records": None}]
        for row in ({"bodyId": True}, {"bodyId": 0}, {"bodyId": 2**63}, {}, [],
                    {"bodyId": 1, "superclass": []}, {"bodyId": 1, "somaNeuromere": ""}):
            bad_envelopes.append({**metadata(), "records": [row]})
        bad_envelopes.append({**metadata(), "records": [{"bodyId": 1}, {"bodyId": 1}]})
        for envelope in bad_envelopes:
            with self.subTest(envelope=envelope), self.assertRaises(ValueError):
                descending_neurons(self.graph, envelope, superclass_labels=["synthetic-descending"])
        for labels in ([], "synthetic-descending", [None], [False], [" "]):
            with self.assertRaises(ValueError):
                descending_neurons(self.graph, metadata(), superclass_labels=labels)
        for changes in ({"source_regions": []}, {"target_regions": ["region-A"]},
                        {"region_field": "type"}, {"source_regions": [None]}):
            kwargs = dict(source_regions=["region-A"], target_regions=["region-B"])
            kwargs.update(changes)
            with self.assertRaises(ValueError):
                cross_region_edges(self.graph, metadata(), **kwargs)

    def test_anatomical_queries_isolation_order_and_empty_view(self):
        envelope = metadata()
        original = copy.deepcopy(envelope)
        nested = self.graph.induced([1, 2, 3]).induced([1, 3])
        result = cross_region_edges(nested, envelope, source_regions=["region-A"],
                                    target_regions=["region-B"])
        self.assertEqual(result["edges"], ())
        self.assertEqual(result["target_body_ids"], ())
        self.assertEqual(result["unknown_body_ids"], (3,))
        self.assertEqual(result["root_key"], self.graph.root_key)
        selected = descending_neurons(nested, envelope, superclass_labels=["synthetic-descending"])
        self.assertEqual(selected["body_ids"], (1,))
        self.assertEqual(selected["unknown_body_ids"], (3,))
        result["source_provenance"].clear()
        self.assertEqual(envelope, original)
        envelope["records"].reverse()
        self.assertEqual(selected, descending_neurons(nested, envelope,
                                                    superclass_labels=["synthetic-descending"]))
        empty = descending_neurons(self.graph.induced([]), envelope,
                                   superclass_labels=["synthetic-descending"])
        self.assertEqual(empty["body_ids"], ())
        self.assertEqual(empty["unknown_body_ids"], ())
        edges = cross_region_edges(self.graph, envelope, source_regions=["region-A"],
                                   target_regions=["region-B"])["edges"]
        edges[0].clear()
        self.assertEqual(self.graph.edge(1, 2)["raw_synapse_weight"], 2)


if __name__ == "__main__":
    unittest.main()
