"""Small source-shaped tests for the preregistered graph-v2 selector."""

import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import pyarrow as pa

from microduck_connectome.rebuild_mvp_graph import select_nodes, _validated_pairs


ROOT = Path(__file__).resolve().parents[1]


class GraphV2SelectionTests(TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / "config/graph_v2.json").read_text())

    def test_rejects_changed_path_depth_or_normalization(self):
        _validated_pairs(self.config)
        changed = json.loads(json.dumps(self.config))
        changed["path_pairs"][1]["max_edges"] = 3
        with self.assertRaises(ValueError):
            _validated_pairs(changed)
        changed = json.loads(json.dumps(self.config))
        changed["normalization"] = "renormalize selected edges"
        with self.assertRaises(ValueError):
            _validated_pairs(changed)

    def test_selects_direct_looming_and_two_hop_steering_from_source_rows(self):
        annotations = pa.table({
            "bodyId": pa.array([1, 2, 3, 4, 5, 6, 7], type=pa.int64()),
            "type": ["LC10a", "DNa02", "LPLC2", "DNp01", "mid", "mid", "mid"],
            "somaSide": ["L", "R", "L", "R", "L", "R", "L"],
        })
        batch = pa.record_batch({
            "body_pre": pa.array([1, 5, 3, 3, 6, 1, 7], type=pa.int64()),
            "body_post": pa.array([5, 2, 4, 6, 4, 7, 4], type=pa.int64()),
            "weight": pa.array([3, 4, 5, 6, 7, 8, 9], type=pa.int64()),
        })
        manifest = {"weights": {"expected_rows": 7}}
        with patch("microduck_connectome.rebuild_mvp_graph.weight_batches", return_value=[batch]):
            selected, populations, paths, intermediates = select_nodes(
                annotations, Path("unused"), manifest, self.config
            )
        self.assertEqual(set(selected), {1, 2, 3, 4, 5, 6})
        self.assertEqual(intermediates, {5, 6})
        self.assertEqual(len(populations["LPLC2"]), 1)
        self.assertEqual(paths["LC10a->DNa02"]["selected_two_edge_path_count"], 1)
        self.assertEqual(paths["LPLC2->DNp01"]["direct_edge_count"], 1)
        self.assertEqual(paths["LPLC2->DNp01"]["selected_two_edge_path_count"], 1)
        self.assertEqual(paths["LPLC2->DNp01"]["direct_weight_sum"], 5)
