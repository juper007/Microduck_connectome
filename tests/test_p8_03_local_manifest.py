"""Package-level evidence completeness checks for the P8-03 local protocol."""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.p8_03_local_manifest import STAGE_FILES, create, verify


class PackageManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        source = json.loads(Path("config/p8_03_local_reference_v1.json").read_text())
        source["package_output"] = str(self.root)
        self.config = self.root / "source-config.json"
        self.config.write_text(json.dumps(source))
        (self.root / "preflight.jsonl").write_text('{"result":"PASS"}\n')
        for stage in ("development", "static", "receding"):
            folder = self.root / stage
            folder.mkdir()
            for name in STAGE_FILES:
                (folder / name).write_text("{}\n")
            (folder / "attempt-01-events.jsonl").write_text('{"kind":"arm"}\n')
        (self.root / "pooled-score.json").write_text('{"result":"PASS"}\n')
        self.manifest = self.root / "package-manifest.json"

    def _write(self):
        payload = create(self.root, self.config, "a" * 40, "final", self.manifest)
        self.manifest.write_text(json.dumps(payload))

    def test_every_file_is_accounted_and_corruption_fails(self):
        self._write()
        self.assertEqual(verify(self.root, self.config, self.manifest), [])
        (self.root / "static" / "attempt-01-events.jsonl").write_text("changed\n")
        self.assertIn("content_mismatch:static/attempt-01-events.jsonl",
                      verify(self.root, self.config, self.manifest))

    def test_missing_down_probe_or_pooled_score_blocks_creation(self):
        for rel in ("static/final-down.log", "receding/final-state-probe.json",
                    "pooled-score.json"):
            path = self.root / rel
            payload = path.read_bytes()
            path.unlink()
            with self.assertRaisesRegex(ValueError, "required evidence absent"):
                create(self.root, self.config, "a" * 40, "final", self.manifest)
            path.write_bytes(payload)

    def test_extra_file_fails_existing_manifest(self):
        self._write()
        (self.root / "unexpected.log").write_text("untracked\n")
        self.assertIn("missing_or_extra:unexpected.log",
                      verify(self.root, self.config, self.manifest))


if __name__ == "__main__":
    unittest.main()
