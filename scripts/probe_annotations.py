"""Verify official annotation bytes and list candidate populations, without credentials."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from urllib.request import urlopen

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.feather as feather

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/manifests/annotations-v1.json"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def acquire(path, manifest):
    if path.exists():
        if digest(path) != manifest["sha256"]:
            raise ValueError("Cached annotation checksum mismatch; cache was not replaced")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as out:
            temporary = Path(out.name)
            with urlopen(manifest["url"], timeout=60) as response:
                while chunk := response.read(1024 * 1024):
                    out.write(chunk)
        if digest(temporary) != manifest["sha256"]:
            raise ValueError("Downloaded annotation checksum mismatch")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def summarize(table, manifest):
    fields = {"bodyId": pa.int64(), "type": pa.string(), "instance": pa.string(), "somaSide": pa.string()}
    for name, dtype in fields.items():
        if name not in table.column_names or table.schema.field(name).type != dtype:
            raise ValueError(f"Invalid or missing annotation column: {name}")
    ids = table["bodyId"]
    if ids.null_count or pc.any(pc.less_equal(ids, 0)).as_py():
        raise ValueError("Body IDs must be non-null positive integers")
    if len(pc.unique(ids)) != table.num_rows:
        raise ValueError("Duplicate body IDs")
    if table.num_rows != manifest["expected_rows"]:
        raise ValueError("Unexpected annotation row count")
    candidates = {}
    for name in manifest["candidate_types"]:
        selected = table.filter(pc.equal(table["type"], name)).select(list(fields)).sort_by("bodyId")
        rows = selected.to_pylist()
        if not rows:
            raise ValueError(f"Expected candidate type absent: {name}")
        sides = {}
        for row in rows:
            key = row["somaSide"] if row["somaSide"] is not None else "UNKNOWN"
            sides[key] = sides.get(key, 0) + 1
        candidates[name] = {"count": len(rows), "soma_side_counts": sides, "records": rows}
    return {"dataset": manifest["dataset"], "annotation_sha256": manifest["sha256"],
            "row_count": table.num_rows, "scope": manifest["scope"], "candidates": candidates}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=ROOT / "data/cache/body-annotations.feather")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text())
    if args.cache.resolve() == args.output.resolve():
        raise ValueError("Output must not overwrite input cache")
    acquire(args.cache, manifest)
    result = summarize(feather.read_table(args.cache), manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({name: {k: v for k, v in value.items() if k != "records"}
                      for name, value in result["candidates"].items()}, sort_keys=True))


if __name__ == "__main__":
    main()
