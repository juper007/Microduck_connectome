"""Guard research identity, source integrity, and source-based laterality."""

import copy
from pathlib import Path
import shutil
import tempfile
import unittest

from microduck_connectome.dna02_evidence import build_evidence, canonical, resolve_sides


ROOT = Path(__file__).resolve().parents[1]
G1 = ROOT / "docs/evidence/g1"


class DNa02EvidenceTests(unittest.TestCase):
    def test_pinned_evidence_and_identity(self):
        result = build_evidence(G1)
        self.assertEqual(canonical(result), (ROOT / "docs/evidence/p2-02/dna02-v1.json").read_bytes())
        self.assertEqual({r["side"]: r["body_id"] for r in result["readouts"]},
                         {"left": 523769, "right": 10360})
        self.assertEqual(sum(r["reachable_LC10a_body_count"] for r in result["readouts"]), 547)
        self.assertEqual(sum(r["simple_two_edge_path_count"] for r in result["readouts"]), 6571)

    def test_side_is_not_order_id_or_instance_inference(self):
        rows = [r["raw_source_record"] for r in build_evidence(G1)["readouts"]]
        self.assertEqual(resolve_sides(rows), resolve_sides(list(reversed(rows))))
        # Changing IDs/suffixes cannot change the source-field interpretation.
        rows = copy.deepcopy(rows)
        rows[0]["bodyId"], rows[1]["bodyId"] = rows[1]["bodyId"], rows[0]["bodyId"]
        rows[0]["instance"] = "unrelated_R"
        self.assertEqual(resolve_sides(rows)["left"]["bodyId"], 10360)

    def test_missing_ambiguous_duplicate_and_non_descending_rejected(self):
        rows = [r["raw_source_record"] for r in build_evidence(G1)["readouts"]]
        mutations = [("somaSide", None), ("somaSide", "M"), ("somaSide", "R"),
                     ("bodyId", 10360), ("superclass", "cb_intrinsic")]
        for key, value in mutations:
            with self.subTest(key=key, value=value):
                changed = copy.deepcopy(rows)
                changed[0][key] = value
                with self.assertRaises(ValueError):
                    resolve_sides(changed)

    def test_each_source_digest_is_checked(self):
        for name in ("source-metadata.json", "pathway-report.json", "query-report.json"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                for source in G1.glob("*.json"):
                    shutil.copyfile(source, Path(directory) / source.name)
                target = Path(directory) / name
                target.write_bytes(target.read_bytes() + b" ")
                with self.assertRaisesRegex(ValueError, "digest mismatch"):
                    build_evidence(directory)
