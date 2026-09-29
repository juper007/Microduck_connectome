"""Create or verify a complete P8-03 local-reference evidence package manifest.

The package root is separate from the source tree. A manifest excludes only
itself; every other regular artifact, including stage manifests and the pooled
score, is hashed and counted. A second invocation verifies without rewriting.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


STAGE_FILES = (
    "batch-journal.json",
    "score.json",
    "raw-manifest.json",
    "final-down.log",
    "final-state-probe.json",
)


def _files(root: Path, manifest_path: Path) -> dict[str, Path]:
    result = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"symlink in evidence package: {path}")
        if path.is_file() and path != manifest_path:
            rel = path.relative_to(root).as_posix()
            if rel in result:
                raise ValueError(f"duplicate evidence path: {rel}")
            result[rel] = path
    return result


def _records(path: Path, data: bytes) -> int | None:
    if path.suffix not in (".jsonl", ".log", ".txt"):
        return None
    return len(data.splitlines())


def _required(root: Path, purpose: str) -> list[str]:
    stages = ("development",) if purpose == "development" else (
        "development", "static", "receding")
    required = ["source-config.json", "preflight.jsonl"]
    for stage in stages:
        required.extend(f"{stage}/{name}" for name in STAGE_FILES)
    if purpose == "final":
        required.append("pooled-score.json")
    return [rel for rel in required if not (root / rel).is_file()]


def create(root: Path, config_path: Path, source_head: str,
           purpose: str, manifest_path: Path) -> dict:
    root = root.resolve(strict=True)
    manifest_path = manifest_path.resolve()
    if manifest_path.parent != root or manifest_path.exists():
        raise ValueError("manifest must be a new file directly under package root")
    if len(source_head) != 40 or any(c not in "0123456789abcdef" for c in source_head):
        raise ValueError("source HEAD must be an exact 40-character SHA")
    config_bytes = config_path.read_bytes()
    config = json.loads(config_bytes)
    if root != Path(config["package_output"]).resolve():
        raise ValueError("package root differs from frozen config")
    if not (root / "source-config.json").is_file() or (
            root / "source-config.json").read_bytes() != config_bytes:
        raise ValueError("packaged source config differs from reviewed source")
    missing = _required(root, purpose)
    if missing:
        raise ValueError(f"required evidence absent: {missing}")
    rows = []
    for rel, path in sorted(_files(root, manifest_path).items()):
        data = path.read_bytes()
        rows.append({"path": rel, "sha256": hashlib.sha256(data).hexdigest(),
                     "bytes": len(data), "record_count": _records(path, data)})
    return {"schema_version": "p8-03-local-package-manifest-v1",
            "task_id": config["task_id"], "purpose": purpose,
            "source_head": source_head,
            "config_sha256": hashlib.sha256(config_bytes).hexdigest(),
            "microduck_commit": config["microduck_commit"],
            "microduck_rl_commit": config["microduck_rl_commit"],
            "graph_sha256": config["graph_sha256"],
            "policy_sha256": config["walking_policy_sha256"],
            "files": rows}


def verify(root: Path, config_path: Path, manifest_path: Path) -> list[str]:
    root = root.resolve(strict=True)
    manifest_path = manifest_path.resolve(strict=True)
    manifest = json.loads(manifest_path.read_bytes())
    config_bytes = config_path.read_bytes()
    config = json.loads(config_bytes)
    errors = []
    if root != Path(config["package_output"]).resolve():
        errors.append("package_root_mismatch")
    if manifest.get("schema_version") != "p8-03-local-package-manifest-v1":
        errors.append("schema_mismatch")
    if manifest.get("task_id") != config["task_id"]:
        errors.append("task_mismatch")
    if manifest.get("config_sha256") != hashlib.sha256(config_bytes).hexdigest():
        errors.append("config_hash_mismatch")
    if not (root / "source-config.json").is_file() or (
            root / "source-config.json").read_bytes() != config_bytes:
        errors.append("packaged_config_mismatch")
    for key in ("microduck_commit", "microduck_rl_commit", "graph_sha256"):
        if manifest.get(key) != config[key]:
            errors.append(f"{key}_mismatch")
    if manifest.get("policy_sha256") != config["walking_policy_sha256"]:
        errors.append("policy_hash_mismatch")
    purpose = manifest.get("purpose")
    if purpose not in ("development", "final"):
        errors.append("purpose_invalid")
    else:
        errors.extend(f"required_missing:{p}" for p in _required(root, purpose))
    actual = _files(root, manifest_path)
    rows = manifest.get("files")
    if not isinstance(rows, list):
        return errors + ["files_invalid"]
    listed = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            errors.append("entry_invalid")
            continue
        rel = row["path"]
        if rel in listed:
            errors.append(f"duplicate:{rel}")
        listed[rel] = row
    for rel in sorted(actual.keys() ^ listed.keys()):
        errors.append(f"missing_or_extra:{rel}")
    for rel in sorted(actual.keys() & listed.keys()):
        data = actual[rel].read_bytes()
        row = listed[rel]
        if (row.get("sha256") != hashlib.sha256(data).hexdigest()
                or row.get("bytes") != len(data)
                or row.get("record_count") != _records(actual[rel], data)):
            errors.append(f"content_mismatch:{rel}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--purpose", choices=("development", "final"))
    parser.add_argument("--source-head")
    args = parser.parse_args()
    if args.verify:
        errors = verify(args.package_root, args.config, args.manifest)
        print(json.dumps({"result": "PASS" if not errors else "FAIL", "errors": errors}))
        raise SystemExit(0 if not errors else 1)
    if args.purpose is None or args.source_head is None:
        parser.error("creation requires --purpose and --source-head")
    payload = create(args.package_root, args.config, args.source_head,
                     args.purpose, args.manifest)
    with args.manifest.open("x", encoding="utf-8") as out:
        json.dump(payload, out, sort_keys=True, indent=2)
        out.write("\n")
    print(json.dumps({"result": "PASS", "entries": len(payload["files"])}))


if __name__ == "__main__":
    main()
