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

class PinnedMDNArtifactTests(unittest.TestCase):
    def test_committed_report_identity_provenance_and_structural_claims(self):
        import hashlib
        import json
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        raw = (root / "docs/evidence/p2-04/mdn-v1.json").read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         "df95b7d6cc8348e04c6c0cdb6ea747ceb89e738155d6047f32f5778e362dda36")
        report = json.loads(raw)
        self.assertEqual(report["dataset"], "male-cns:v1.0")
        self.assertEqual({r["bodyId"]: r["somaSide"] for r in identity(report["readouts"])},
                         {10763: "R", 11288: "L", 11332: "R", 12348: "L"})
        manifest = json.loads((root / "data/manifests/pathway-source-v1.json").read_text())
        self.assertEqual(report["source_manifest"], manifest)
        self.assertEqual(report["outgoing_source_rows"], 18796)
        self.assertEqual(sum(r["weight"] for r in report["outgoing"]), 39119)
        lbl, lul = report["downstream"]
        self.assertEqual({r["bodyId"]: (r["somaSide"], r["somaNeuromere"])
                          for r in lbl["source_records"]}, {801214: ("R", "T3"), 801246: ("L", "T3")})
        self.assertEqual(lbl["total_weight"], 463)
        self.assertEqual(len(lbl["direct_edges"]), 4)
        self.assertEqual(lul["status"], "absent_exact_type")
        self.assertEqual(lul["source_records"], [])
        for source in report["outgoing"]:
            self.assertEqual(sum(g["weight"] for g in source["target_superclasses"]), source["weight"])
            self.assertEqual(sum(g["bodies"] for g in source["target_superclasses"]), source["target_bodies"])
