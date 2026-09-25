"""Optional source-artifact checks for the G8-R1 graph on Thor.

Set G8_R1_BUILD_DIR to one completed rebuild directory to run this test.
"""

import json
import os
from pathlib import Path
from unittest import TestCase, skipUnless

from microduck_connectome.graph_cache import load_graph


ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = os.environ.get("G8_R1_BUILD_DIR")


@skipUnless(BUILD_DIR, "set G8_R1_BUILD_DIR for the pinned-source artifact")
class GraphV2ArtifactTests(TestCase):
    def test_frozen_populations_and_direct_edges(self):
        build_dir = Path(BUILD_DIR)
        report = json.loads((build_dir / "reachability-report-v1.json").read_text())
        graph = load_graph(build_dir / "graphs", report["graph"]["cache_key"])
        nodes = {row["body_id"] for row in graph["annotations"]["records"]}
        old = json.loads((ROOT / "docs/evidence/g1/pathway-report.json").read_text())
        self.assertTrue(set(old["selected_body_ids"]) <= nodes)

        sensory = json.loads((ROOT / "config/sensory_mapping_v1.json").read_text())
        readout = json.loads((ROOT / "config/dn_readout_v1.json").read_text())
        for population in sensory["populations"].values():
            self.assertTrue(set(population["body_ids"]) <= nodes)
        for population in readout["populations"].values():
            self.assertTrue(set(population["body_ids"]) <= nodes)

        lplc2 = set(sensory["populations"]["lplc2_left"]["body_ids"])
        lplc2 |= set(sensory["populations"]["lplc2_right"]["body_ids"])
        dnp01 = set(readout["populations"]["escape"]["body_ids"])
        direct = {
            (edge["source_body_id"], edge["target_body_id"]): edge["raw_synapse_weight"]
            for edge in graph["edges"]
            if edge["source_body_id"] in lplc2 and edge["target_body_id"] in dnp01
        }
        p2 = json.loads((ROOT / "docs/evidence/p2-03/dnp01-report.json").read_text())
        expected = {
            (edge["body_pre"], edge["body_post"]): edge["weight"]
            for edge in p2["direct_visual_edges"]
            if edge["body_pre"] in lplc2 and edge["body_post"] in dnp01
        }
        self.assertEqual(direct, expected)
        self.assertEqual(len(direct), 185)
        self.assertEqual(sum(direct.values()), 4862)
