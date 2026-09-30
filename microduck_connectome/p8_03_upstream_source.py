"""Verify a local reproduction of the reviewed MicroDuck diagnostic patch."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess


BASE_SHA = "344925c9f8fa031f85428a305b1e8ec2eaae29c1"
BASE_TREE = "9ddbb232bc835e1a91a10a49f6ca4b0cdadaad84"
HISTORICAL_CANDIDATE_SHA = "c47085a57770c52ed4cd00d5960b17598df2d7af"
CANDIDATE_TREE = "8118cb336af98fb0947f3de592843dc8b5434096"
PATCH_SHA256 = "828ff2619ee378d4fe49fe358944dcc9b5aa9b6583e7aef1afe43a353411655a"
FILE_SHA256 = {
    "duck-ipc-proto/src/lib.rs": "da02f4734cdb3d69962ebc7c17995d98c42276024424e14b3d40314df85d39ee",
    "robotd/src/intents.rs": "1e02a13b2fda02e0cecf615091b91960862c598d651ab24ed55785d90b222c8f",
    "robotd/src/main.rs": "57a9d8ac0a24b150f695a8784e20866ba950006cf2e7fbfe53e2cb551f4171d7",
    "robotctl/src/monitor.rs": "87877ef9fde9c9252ca0fe9fd2d1f9c9e967d21ab852dcf1e9a6450cc9e8bc73",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def verify_reconstructed_source(repo: Path, patch: Path, *,
                                run_tests: bool = False) -> dict:
    """Require the clean one-parent reproduction commit to contain exactly the patch.

    The historical candidate commit is provenance, not an object dependency.
    Tests run in batch preflight; trial startup repeats the immutable content checks.
    """
    repo, patch = repo.resolve(), patch.resolve()
    if _sha(patch.read_bytes()) != PATCH_SHA256:
        raise ValueError("reviewed upstream patch hash mismatch")
    if _git(repo, "status", "--porcelain"):
        raise ValueError("reconstructed upstream source is not clean")
    parents = _git(repo, "rev-list", "--parents", "-n", "1", "HEAD").split()
    if len(parents) != 2 or parents[1] != BASE_SHA:
        raise ValueError("reconstruction commit is not directly based on pinned MicroDuck")
    if _git(repo, "rev-parse", BASE_SHA + "^{tree}") != BASE_TREE:
        raise ValueError("pinned MicroDuck base tree mismatch")
    if _git(repo, "rev-parse", "HEAD^{tree}") != CANDIDATE_TREE:
        raise ValueError("reconstructed MicroDuck tree mismatch")
    diff = subprocess.check_output(["git", "-C", str(repo), "show", "--format=",
                                    "--binary", "HEAD"])
    if diff != patch.read_bytes():
        raise ValueError("reconstruction commit diff differs from reviewed patch")
    hashes = {name: _sha((repo / name).read_bytes()) for name in FILE_SHA256}
    if hashes != FILE_SHA256:
        raise ValueError("frozen MicroDuck candidate file hash mismatch")
    if any(token not in (repo / "duck-ipc-proto/src/lib.rs").read_text()
           for token in ("accepted_move_generation", "consumed_move_generation",
                         "control_tick_sequence")):
        raise ValueError("required robotd API metadata missing")
    result = {
        "upstream_source_identity": "RECONSTRUCTED_FROM_PINNED_BASE_AND_REVIEWED_PATCH",
        "base_commit": BASE_SHA, "base_tree": BASE_TREE,
        "historical_candidate_sha": HISTORICAL_CANDIDATE_SHA,
        "thor_reproduction_commit": parents[0], "candidate_tree": CANDIDATE_TREE,
        "patch_sha256": PATCH_SHA256, "patched_diff_sha256": _sha(diff),
        "candidate_file_sha256": hashes,
    }
    if run_tests:
        local_cargo = repo.parent / "cargo"
        cargo = shutil.which("cargo") or str(local_cargo / "bin/cargo")
        env = os.environ.copy()
        if local_cargo.is_dir():
            env["CARGO_HOME"] = str(local_cargo)
            env["RUSTUP_HOME"] = str(repo.parent / "rustup")
            env["PATH"] = str(local_cargo / "bin") + os.pathsep + env.get("PATH", "")
        checks = (("cargo fmt --all --check", [cargo, "fmt", "--all", "--check"]),
                  ("cargo test -p duck-ipc-proto -p robotd -p robotctl",
                   [cargo, "test", "-p", "duck-ipc-proto", "-p", "robotd",
                    "-p", "robotctl"]))
        for label, command in checks:
            proc = subprocess.run(command, cwd=repo, env=env, text=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  check=False)
            if proc.returncode:
                raise ValueError(f"upstream validation failed: {label}: {proc.stdout[-4000:]}")
        if _git(repo, "status", "--porcelain"):
            raise ValueError("upstream validation modified source")
        result["upstream_tests"] = "PASS"
        result["upstream_test_commands"] = [label for label, _ in checks]
    return result
