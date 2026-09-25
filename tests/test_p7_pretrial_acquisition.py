"""Official policy readback must reject a silent fallback before a trial."""

import hashlib
import tempfile
from pathlib import Path
import unittest

from scripts.p7_pretrial_acquisition import validate_loaded_walk_policy


class WalkPolicyReadbackTests(unittest.TestCase):
    def test_exact_loaded_override_and_hash_are_required(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "walk.onnx"
            path.write_bytes(b"policy artifact")
            copied = Path(folder) / "release.onnx"
            copied.write_bytes(path.read_bytes())
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            readback = {"policies": {"enabled": True, "mode": "walk",
                       "slots": [{"slot": "walk", "path": str(copied),
                                  "origin": "local", "overridden": True,
                                  "error": None}]}}
            self.assertEqual(validate_loaded_walk_policy(readback, path, digest)
                             ["loaded_walk_sha256"], digest)
            for change in ({"overridden": False}, {"error": "load failed"},
                           {"origin": "default"},
                           {"path": str(Path(folder) / "wrong.onnx")}):
                failed = {"policies": {**readback["policies"], "slots": [
                    {**readback["policies"]["slots"][0], **change}]}}
                with self.assertRaises((ValueError, FileNotFoundError)):
                    validate_loaded_walk_policy(failed, path, digest)
            with self.assertRaises(ValueError):
                validate_loaded_walk_policy(readback, path, "bad-hash")


if __name__ == "__main__":
    unittest.main()
