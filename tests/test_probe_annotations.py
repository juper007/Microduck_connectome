import importlib.util
from pathlib import Path
import tempfile
import unittest

import pyarrow as pa

spec = importlib.util.spec_from_file_location("probe", Path(__file__).resolve().parents[1] / "scripts/probe_annotations.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.table = pa.table({"bodyId": [2, 1], "type": ["candidate", "candidate"],
                               "instance": ["b", "a"], "somaSide": ["R", "L"]})
        self.manifest = {"expected_rows": 2, "candidate_types": ["candidate"],
                         "dataset": "synthetic", "sha256": "unused", "scope": "test"}

    def test_order_is_canonical(self):
        first = probe.summarize(self.table, self.manifest)
        second = probe.summarize(self.table.take([1, 0]), self.manifest)
        self.assertEqual(first, second)
        self.assertEqual(first["candidates"]["candidate"]["records"][0]["bodyId"], 1)

    def test_duplicate_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            probe.summarize(self.table.set_column(0, "bodyId", pa.array([1, 1])), self.manifest)

    def test_invalid_ids_rejected(self):
        for values in [[0, 1], [None, 1]]:
            with self.assertRaisesRegex(ValueError, "positive"):
                probe.summarize(self.table.set_column(0, "bodyId", pa.array(values, type=pa.int64())), self.manifest)

    def test_bad_schema_rejected(self):
        with self.assertRaisesRegex(ValueError, "column"):
            probe.summarize(self.table.drop(["type"]), self.manifest)

    def test_missing_candidate_rejected(self):
        with self.assertRaisesRegex(ValueError, "absent"):
            probe.summarize(self.table, dict(self.manifest, candidate_types=["missing"]))

    def test_bad_cache_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache"
            path.write_bytes(b"bad")
            with self.assertRaisesRegex(ValueError, "checksum"):
                probe.acquire(path, self.manifest)
            self.assertEqual(path.read_bytes(), b"bad")


if __name__ == "__main__":
    unittest.main()
