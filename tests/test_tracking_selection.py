"""Guard the identity freeze, side semantics, provenance and bounded routes."""

import copy
from pathlib import Path
import shutil
import tempfile
import unittest

from microduck_connectome.tracking_selection import (
    EVIDENCE_HASHES, build_selection, canonical, population, validate_selection,
)


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence"
FROZEN = EVIDENCE / "p2-05/tracking-selection-v1.json"


class TrackingSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.selection = build_selection(EVIDENCE)

    def test_frozen_complete_population_and_bilateral_routes(self):
        self.assertEqual(FROZEN.read_bytes(), canonical(self.selection))
        self.assertEqual(canonical(build_selection(EVIDENCE)), canonical(self.selection))
        config = self.selection["config"]
        self.assertEqual({s: len(v) for s, v in config["input_ids_by_soma_side"].items()},
                         {"left": 135, "right": 140})
        self.assertEqual(config["readout_ids_by_soma_side"], {"left": 523769, "right": 10360})
        # Independently recorded G1 scientific acceptance facts, not inferred side order.
        actual = {(r["source_soma_side"], r["readout_soma_side"]):
                  (r["reachable_input_count"], r["simple_two_edge_path_count"])
                  for r in self.selection["routes"]}
        self.assertEqual(actual, {("left", "left"): (135, 2137),
                                 ("left", "right"): (135, 941),
                                 ("right", "left"): (140, 1224),
                                 ("right", "right"): (137, 2269)})
        right_route = next(r for r in self.selection["routes"]
                           if r["source_soma_side"] == r["readout_soma_side"] == "right")
        self.assertEqual(right_route["unreachable_input_ids"], [76174, 86507, 100368])
        self.assertTrue(set(right_route["unreachable_input_ids"]) <=
                        set(config["input_ids_by_soma_side"]["right"]))

    def test_source_side_not_order_id_or_instance(self):
        rows = copy.deepcopy(self.selection["selected_source_records"])
        groups = population(rows, "LC10a")
        self.assertEqual(groups, population(list(reversed(rows)), "LC10a"))
        for row in rows:
            row["instance"] = "LC10a_R" if row["somaSide"] == "L" else "LC10a_L"
        self.assertEqual(groups, population(rows, "LC10a"))
        left = next(r for r in rows if r["somaSide"] == "L")
        right = next(r for r in rows if r["somaSide"] == "R")
        old_left, old_right = left["bodyId"], right["bodyId"]
        left["bodyId"], right["bodyId"] = old_right, old_left
        self.assertIn(old_right, population(rows, "LC10a")["left"])
        self.assertIn(old_left, population(rows, "LC10a")["right"])

    def test_invalid_source_records_fail_closed(self):
        rows = self.selection["selected_source_records"]
        for field, value in [("somaSide", None), ("somaSide", "M"), ("somaSide", "left"),
                             ("bodyId", True), ("bodyId", 0), ("bodyId", rows[1]["bodyId"]),
                             ("type", "LC10"), ("superclass", "cb_intrinsic")]:
            with self.subTest(field=field, value=value):
                changed = copy.deepcopy(rows)
                changed[0][field] = value
                with self.assertRaises(ValueError):
                    population(changed, "LC10a")
        for subset in ([], [r for r in rows if r["somaSide"] == "L"]):
            with self.assertRaises(ValueError):
                population(subset, "LC10a")

    def test_every_evidence_hash_is_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in EVIDENCE_HASHES:
                target = Path(directory) / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(EVIDENCE / name, target)
            for name in EVIDENCE_HASHES:
                with self.subTest(name=name):
                    target = Path(directory) / name
                    original = target.read_bytes()
                    target.write_bytes(original + b" ")
                    with self.assertRaisesRegex(ValueError, "digest mismatch"):
                        build_selection(directory)
                    target.write_bytes(original)

    def test_tampered_selection_cannot_rehash_itself_into_acceptance(self):
        mutations = [
            lambda x: x["config"]["input_ids_by_soma_side"]["left"].pop(),
            lambda x: x["config"]["readout_ids_by_soma_side"].update(left=10360),
            lambda x: x["selected_source_records"][0].update(somaSide="R"),
            lambda x: x["config"].update(dataset="male-cns:v2.0"),
            lambda x: x["routes"][0].update(reachable_input_count=0),
            lambda x: x["source_evidence_sha256"].update({"g1/query-report.json": "0" * 64}),
            lambda x: x["candidate_dispositions"].update(LC4="selected"),
            lambda x: x["config"].update(gain=1.0),
        ]
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "selection.json"
            for mutate in mutations:
                changed = copy.deepcopy(self.selection)
                mutate(changed)
                changed["config_sha256"] = hashlib.sha256(canonical(changed["config"])).hexdigest()
                target.write_bytes(canonical(changed))
                with self.assertRaisesRegex(ValueError, "differs from frozen"):
                    validate_selection(target, EVIDENCE)
            target.write_bytes(FROZEN.read_bytes() + b" ")
            with self.assertRaises(ValueError):
                validate_selection(target, EVIDENCE)
