"""MDN evidence rejection and deterministic aggregation checks."""
import copy
import unittest
from microduck_connectome.mdn_evidence import identity, summarize, build


def rows():
    return [{"bodyId": i, "type": "MDN", "instance": "ignored", "somaSide": side,
             "superclass": "descending_neuron"} for i, side in [(1, "L"), (2, "R"), (3, "L"), (4, "R")]]


class MDNEvidenceTests(unittest.TestCase):
    def test_order_does_not_infer_side(self):
        source = rows()
        self.assertEqual(identity(source), identity(list(reversed(source))))
        source[0]["instance"] = "MDN_R"
        self.assertEqual(identity(source)[0]["somaSide"], "L")

    def test_invalid_identity_rejected(self):
        for key, value in [("somaSide", None), ("somaSide", "M"), ("somaSide", "R"),
                           ("superclass", "vnc_intrinsic"), ("bodyId", 2), ("bodyId", True)]:
            with self.subTest(key=key, value=value):
                source = rows()
                source[0][key] = value
                with self.assertRaises(ValueError):
                    identity(source)
        with self.assertRaises(ValueError):
            identity(rows()[:-1])

    def test_aggregation_unknowns_and_exact_type(self):
        source = rows() + [{"bodyId": 5, "type": "LBL40", "somaSide": "R", "superclass": "vnc_intrinsic"},
                           {"bodyId": 6, "type": "other", "somaSide": None, "superclass": None, "synonyms": "LUL130"}]
        edges = [(1, 5, 4), (1, 5, 2), (1, 6, 3), (1, 99, 1)]
        result = summarize(source, edges)
        self.assertEqual(result, summarize(list(reversed(source)), list(reversed(edges))))
        self.assertEqual(result["downstream"][0]["total_weight"], 6)
        self.assertEqual(result["downstream"][1]["status"], "absent_exact_type")
        self.assertEqual(len(result["outgoing"][0]["target_superclasses"]), 3)
        self.assertEqual(result["outgoing"][0]["weight"], 10)

    def test_bad_edge_and_duplicate_annotations_rejected(self):
        for edge in [(1, 5, 0), (1, 5, -1), (1, 5, 1.5), (1, 5, True), (1, 0, 2), (99, 1, 2)]:
            with self.subTest(edge=edge), self.assertRaises(ValueError):
                summarize(rows(), [edge])
        with self.assertRaises(ValueError):
            summarize(rows() + [copy.deepcopy(rows()[0])], [])

    def test_source_output_collision_rejected_before_io(self):
        with self.assertRaisesRegex(ValueError, "overwrite"):
            build("missing-annotations.feather", "missing-weights.feather", "missing-weights.feather")
