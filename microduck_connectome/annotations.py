"""Strict, deterministic annotation projection; no biological inference or I/O."""

from collections.abc import Mapping
import json
import re

from .neuprint_client import DATASET

SCHEMA_VERSION = "annotation-v1"
MAX_BODY_ID = 2 ** 63 - 1
SOURCE_FIELDS = frozenset(("bodyId", "type", "instance", "somaSide", "class"))
RECORD_FIELDS = frozenset(("body_id", "cell_type", "instance", "soma_side", "neuron_class"))
ARTIFACT_FIELDS = frozenset(("schema_version", "dataset", "source_note", "extraction_commit", "records"))


class AnnotationError(ValueError):
    """An input violates the supported annotation contract."""


def _keys(value, expected, label):
    if not isinstance(value, Mapping) or set(value) != expected:
        raise AnnotationError(f"{label} must be a mapping with exactly the documented fields")


def _text(value, label, *, nullable=False):
    if nullable and value is None:
        return value
    if not isinstance(value, str) or not value.strip():
        raise AnnotationError(f"{label} must be a nonblank string" + (" or null" if nullable else ""))
    # Reject lone surrogates so canonical output always has a UTF-8 representation.
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise AnnotationError(f"{label} must be valid Unicode") from None
    return value


def normalize_annotations(rows, *, dataset, source_note, extraction_commit):
    """Validate a bounded source projection and return a fresh JSON-safe artifact.

    All five source keys are required; optional annotations use explicit None.
    source_note identifies the evidence/query/fixture; extraction_commit is its
    full lowercase Git SHA. These assertions are caller-supplied, not verified.
    """
    if dataset != DATASET:
        raise AnnotationError(f"dataset must be {DATASET}")
    _text(source_note, "source_note")
    if not isinstance(extraction_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", extraction_commit):
        raise AnnotationError("extraction_commit must be a full lowercase Git SHA")
    if not isinstance(rows, (list, tuple)):
        raise AnnotationError("rows must be a list or tuple")
    records = []
    seen = set()
    for index, row in enumerate(rows):
        label = f"row {index}"
        _keys(row, SOURCE_FIELDS, label)
        body_id = row["bodyId"]
        if type(body_id) is not int or not 1 <= body_id <= MAX_BODY_ID:
            raise AnnotationError(f"{label}.bodyId must be an integer in 1..2**63-1 (no coercion)")
        if body_id in seen:
            raise AnnotationError(f"{label}.bodyId is duplicated")
        seen.add(body_id)
        cell_type = _text(row["type"], f"{label}.type", nullable=True)
        instance = _text(row["instance"], f"{label}.instance", nullable=True)
        neuron_class = _text(row["class"], f"{label}.class", nullable=True)
        side = row["somaSide"]
        if side is not None and (not isinstance(side, str) or side not in ("left", "right")):
            raise AnnotationError(f"{label}.somaSide must be left, right, or null")
        records.append({"body_id": body_id, "cell_type": cell_type, "instance": instance,
                        "soma_side": side, "neuron_class": neuron_class})
    return {"schema_version": SCHEMA_VERSION, "dataset": DATASET,
            "source_note": source_note, "extraction_commit": extraction_commit,
            "records": sorted(records, key=lambda record: record["body_id"])}


def _validate_artifact(artifact):
    _keys(artifact, ARTIFACT_FIELDS, "artifact")
    if artifact["schema_version"] != SCHEMA_VERSION:
        raise AnnotationError(f"schema_version must be {SCHEMA_VERSION}")
    if not isinstance(artifact["records"], list):
        raise AnnotationError("records must be a list")
    rows = []
    for index, record in enumerate(artifact["records"]):
        _keys(record, RECORD_FIELDS, f"record {index}")
        rows.append({"bodyId": record["body_id"], "type": record["cell_type"],
                     "instance": record["instance"], "somaSide": record["soma_side"],
                     "class": record["neuron_class"]})
    return normalize_annotations(rows, dataset=artifact["dataset"],
                                 source_note=artifact["source_note"],
                                 extraction_commit=artifact["extraction_commit"])


def annotations_to_json(artifact):
    """Revalidate even mutated artifacts; return canonical JSON text (no newline)."""
    return json.dumps(_validate_artifact(artifact), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AnnotationError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(value):
    raise AnnotationError("nonfinite JSON numbers are unsupported")


def annotations_from_json(text):
    """Decode and revalidate an artifact, rejecting ambiguous duplicate JSON keys."""
    if not isinstance(text, str):
        raise AnnotationError("JSON input must be text")
    try:
        artifact = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, RecursionError) as error:
        raise AnnotationError("invalid annotation JSON") from error
    return _validate_artifact(artifact)
