"""Content identity must not depend on the historical local candidate object."""

import hashlib
from pathlib import Path
import subprocess
from unittest.mock import patch as mock_patch

import pytest

from microduck_connectome import p8_03_upstream_source as source


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def test_reproduction_requires_exact_base_patch_tree_files_and_clean_checkout(tmp_path):
    repo = tmp_path / "upstream"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    metadata = repo / "duck-ipc-proto/src/lib.rs"
    metadata.parent.mkdir(parents=True)
    metadata.write_text("base\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "base")
    base, base_tree = git(repo, "rev-parse", "HEAD"), git(repo, "rev-parse", "HEAD^{tree}")
    metadata.write_text("accepted_move_generation\nconsumed_move_generation\n"
                        "control_tick_sequence\n")
    diff = subprocess.check_output(["git", "-C", str(repo), "diff", "--binary"])
    reviewed_patch = tmp_path / "reviewed.patch"
    reviewed_patch.write_bytes(diff)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "reproduction")
    expected_file = hashlib.sha256(metadata.read_bytes()).hexdigest()
    with (mock_patch.object(source, "BASE_SHA", base),
          mock_patch.object(source, "BASE_TREE", base_tree),
          mock_patch.object(source, "CANDIDATE_TREE", git(repo, "rev-parse", "HEAD^{tree}")),
          mock_patch.object(source, "PATCH_SHA256", hashlib.sha256(diff).hexdigest()),
          mock_patch.object(source, "FILE_SHA256", {"duck-ipc-proto/src/lib.rs": expected_file})):
        identity = source.verify_reconstructed_source(repo, reviewed_patch)
        assert identity["upstream_source_identity"] == (
            "RECONSTRUCTED_FROM_PINNED_BASE_AND_REVIEWED_PATCH")
        assert identity["patched_diff_sha256"] == hashlib.sha256(diff).hexdigest()
        metadata.write_text("tampered\n")
        with pytest.raises(ValueError, match="not clean"):
            source.verify_reconstructed_source(repo, reviewed_patch)
        git(repo, "checkout", "--", "duck-ipc-proto/src/lib.rs")
        reviewed_patch.write_bytes(diff + b"\n")
        with pytest.raises(ValueError, match="patch hash mismatch"):
            source.verify_reconstructed_source(repo, reviewed_patch)
