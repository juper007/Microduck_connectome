"""Pinned, read-only MaleCNS query using only the Python standard library."""

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

ENDPOINT = "https://neuprint.janelia.org"
DATASET = "male-cns:v1.0"
CREDENTIAL_ENV = "NEUPRINT_APPLICATION_CREDENTIALS"
QUERY_VERSION = "dna02-body-ids-v1"
QUERY = "MATCH (n:Neuron) WHERE n.type = 'DNa02' RETURN n.bodyId AS bodyId ORDER BY bodyId"
MAX_RESPONSE_BYTES = 65536


class NeuprintError(RuntimeError):
    """Safe public error; never contains transport details or response contents."""


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Even same-host redirects are rejected: credentials have one destination.
        return None


def _canonical(value):
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")


@dataclass(frozen=True)
class QueryResult:
    body_ids: tuple[int, ...]
    created_utc: str

    def provenance(self, *, code_commit: str) -> dict:
        """Return public provenance; the caller supplies the executing Git SHA."""
        if not isinstance(code_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", code_commit):
            raise ValueError("code_commit must be a full lowercase Git SHA")
        return {
            "dataset": DATASET,
            "endpoint": ENDPOINT,
            "query_version": QUERY_VERSION,
            "query": QUERY,
            "query_sha256": hashlib.sha256(QUERY.encode("utf-8")).hexdigest(),
            "extraction_tool_version": code_commit,
            "created_utc": self.created_utc,
            "body_ids": list(self.body_ids),
            "node_count": len(self.body_ids),
            "body_id_set_hash": hashlib.sha256(_canonical(self.body_ids)).hexdigest(),
            "filters": {"type": "DNa02"},
            "scope": "annotation identity only; no connectivity or biological interpretation",
        }


class NeuprintClient:
    """Fixed endpoint/dataset; only the known DNa02 read query is exposed.

    timeout_seconds is the socket-operation timeout, not a total wall-clock deadline.
    Credentials are read from the environment per call and are never retained here.
    """

    def __init__(self, *, timeout_seconds: float = 20):
        valid = False
        try:
            valid = (not isinstance(timeout_seconds, bool)
                     and isinstance(timeout_seconds, (float, int))
                     and math.isfinite(timeout_seconds) and timeout_seconds > 0)
        except OverflowError:
            pass
        if not valid:
            raise ValueError("timeout_seconds must be finite and positive")
        self.timeout_seconds = timeout_seconds

    def fetch_dna02(self) -> QueryResult:
        token = os.environ.get(CREDENTIAL_ENV, "")
        if not token or any(ord(char) < 33 or ord(char) > 126 for char in token):
            raise NeuprintError("Missing or invalid NEUPRINT_APPLICATION_CREDENTIALS")

        failure = None
        try:
            request = Request(
                ENDPOINT + "/api/custom/custom",
                data=_canonical({"dataset": DATASET, "cypher": QUERY}),
                headers={"Authorization": "Bearer " + token,
                         "Content-Type": "application/json", "Accept": "application/json"},
                method="POST",
            )
            with build_opener(_RejectRedirects()).open(
                    request, timeout=self.timeout_seconds) as response:
                if response.status != 200:
                    failure = "neuPrint returned an unexpected HTTP status"
                else:
                    raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            if error.code in (401, 403):
                failure = "neuPrint authorization failed"
            elif 300 <= error.code < 400:
                failure = "neuPrint redirect refused"
            else:
                failure = "neuPrint HTTP request failed"
            try:
                error.close()
            except Exception:
                pass  # Cleanup failures must not expose transport data either.
        except Exception:
            # Transport errors may contain URLs, headers, response text or tokens.
            failure = "neuPrint network request failed (including possible timeout)"
        finally:
            token = None
        # Outside the handler: no sensitive exception survives in __context__.
        if failure:
            raise NeuprintError(failure)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise NeuprintError("neuPrint response exceeds size limit")

        malformed = False
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeError, RecursionError):
            malformed = True
        if malformed:
            raise NeuprintError("neuPrint returned malformed JSON")
        if (not isinstance(payload, dict) or payload.get("columns") != ["bodyId"]
                or not isinstance(payload.get("data"), list) or not payload["data"]):
            raise NeuprintError("neuPrint returned an invalid or empty result schema")
        ids = []
        for row in payload["data"]:
            if (not isinstance(row, list) or len(row) != 1
                    or type(row[0]) is not int or row[0] <= 0):
                raise NeuprintError("neuPrint returned an invalid body ID row")
            ids.append(row[0])
        if len(ids) != len(set(ids)):
            raise NeuprintError("neuPrint returned duplicate body IDs")
        return QueryResult(tuple(sorted(ids)), datetime.now(timezone.utc).isoformat())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code-commit", required=True, help="full Git SHA of clean executing code")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[0-9a-f]{40}", args.code_commit):
        parser.error("--code-commit must be a full lowercase Git SHA")
    try:
        result = NeuprintClient().fetch_dna02()
        manifest_path = Path(__file__).resolve().parent.parent / "data/manifests/neuprint_dna02_smoke.json"
        expected = json.loads(manifest_path.read_text(encoding="utf-8"))
        if expected["dataset"] != DATASET or list(result.body_ids) != expected["body_ids"]:
            raise NeuprintError("Known DNa02 result differs from the pinned smoke manifest")
        evidence = result.provenance(code_commit=args.code_commit)
        evidence["expected_result_verified"] = True
    except NeuprintError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:
        print("Unable to load or validate the smoke manifest", file=sys.stderr)
        return 1
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
