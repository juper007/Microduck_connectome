import unittest

from microduck_connectome.dnp01_evidence import identity, summarize


def row(body, typ, side, **kwargs):
    return {"bodyId": body, "type": typ, "somaSide": side,
            "superclass": "descending_neuron", "instance": typ, **kwargs}


class Dnp01EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.rows = [row(1, "DNp01", "L", instance="DNp01(GF)_L"),
                     row(2, "DNp01", "R", hemibrainType="Giant Fiber"),
                     row(3, "LC4", "L"), row(4, "LPLC2", "R"),
                     row(5, "GF", "L"), row(6, "GFish", "R")]

    def test_alias_audit_is_not_population_selection(self):
        result = identity(self.rows)
        self.assertEqual([r["bodyId"] for r in result["readouts"]], [1, 2])
        self.assertEqual([r["bodyId"] for r in result["alias_matches"]], [1, 2, 5])
        self.assertEqual(result["exact_GF_type_body_ids"], [5])
        for r in self.rows:
            r.pop("hemibrainType", None)
            r["instance"] = r["type"]
        self.assertEqual(identity(self.rows[:4])["alias_matches"], [])

    def test_missing_side_rejected_without_guessing(self):
        self.rows[0]["somaSide"] = None
        with self.assertRaises(ValueError):
            identity(self.rows)

    def test_direction_duplicates_unknowns_and_order(self):
        edges = [(3, 1, 2), (3, 1, 5), (1, 3, 99), (4, 2, 4), (1, 99, 8), (5, 6, 100)]
        report = summarize(self.rows, edges)
        self.assertEqual(report, summarize(list(reversed(self.rows)), list(reversed(edges))))
        self.assertEqual(report["direct_visual_edges"], [
            {"body_pre": 3, "body_post": 1, "weight": 7},
            {"body_pre": 4, "body_post": 2, "weight": 4}])
        self.assertEqual(report["outgoing"][0]["weight"], 107)
        self.assertEqual(report["outgoing"][0]["top_targets"][1]["annotation"], None)
        self.assertEqual(report["outgoing"][1]["target_bodies"], 0)

    def test_nonpositive_weights_rejected(self):
        with self.assertRaises(ValueError):
            summarize(self.rows, [(1, 2, 0)])


if __name__ == "__main__":
    unittest.main()
