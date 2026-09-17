"""Bootstrap smoke check; online mode never substitutes synthetic data."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--online", action="store_true")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "config/versions.json").read_text())
    if platform.python_version() != manifest["environment"]["python"]:
        raise ValueError("Python version differs from config/versions.json")
    if manifest["dataset"]["id"] != "male-cns:v1.0":
        raise ValueError("Unexpected dataset; frozen MVP requires male-cns:v1.0")
    for upstream in manifest["upstream"].values():
        if not re.fullmatch(r"[0-9a-f]{40}", upstream["commit"]):
            raise ValueError("Upstream must use a full commit SHA")
    from neuprint import Client
    result = {
        "bootstrap": "PASS",
        "python": platform.python_version(),
        "neuprint_python": importlib.metadata.version("neuprint-python"),
        "dataset": manifest["dataset"]["id"],
        "dataset_query": "NOT_RUN",
        "phase_0_gate": "NOT_EVALUATED",
    }
    if args.online:
        token = os.environ.get("NEUPRINT_TOKEN")
        if not token:
            print("BLOCKED: set NEUPRINT_TOKEN in your environment; never commit it.", file=sys.stderr)
            return 2
        try:
            client = Client(manifest["dataset"]["server"], dataset=manifest["dataset"]["id"], token=token)
            neurons = client.fetch_custom(
                'MATCH (n:Neuron) WHERE n.type = "DNge104" '
                'RETURN n.bodyId AS bodyId, n.type AS type ORDER BY bodyId LIMIT 10'
            )
            if neurons.empty or not (neurons["type"] == "DNge104").all():
                raise ValueError("Known neuron query did not return expected records")
            result["dataset_query"] = "PASS"
            result["records"] = neurons.to_dict(orient="records")
        except Exception:
            # Do not expose request headers, credentials, or exception payloads.
            print("FAIL: neuPrint query failed; verify access, dataset and connectivity.", file=sys.stderr)
            return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
