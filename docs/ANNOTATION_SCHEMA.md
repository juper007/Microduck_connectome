# Annotation projection v1 (P1-02)

`microduck_connectome.annotations` validates a deliberately narrow, offline input
contract for pinned `male-cns:v1.0` annotation metadata. It does not query neuPrint,
verify caller provenance, or claim to accept arbitrary neuPrint response schemas.
All examples and test records below are synthetic; they are not population evidence.

## Source contract

`normalize_annotations(rows, *, dataset, source_note, extraction_commit)` accepts
a list or tuple of mappings with **exactly** these five keys. Missing keys and
extra keys fail instead of silently dropping data. Optional means an explicit
Python `None` / JSON `null`; the projection producer must include those keys.

| Source key | Output record key | Accepted value |
|---|---|---|
| `bodyId` | `body_id` | Exact Python `int` in `1..2**63-1`; no bool, float, string, or coercion |
| `type` | `cell_type` | Nonblank Unicode string or null |
| `instance` | `instance` | Nonblank Unicode string or null |
| `somaSide` | `soma_side` | Exact `left`, `right`, or null |
| `class` | `neuron_class` | Nonblank Unicode string or null |

The integer range is an explicit signed-64-bit interoperability limit of this
local schema, not a biological property of IDs. JSON emits exact integer tokens;
consumers must use integer-preserving parsers (JavaScript Number can lose precision
above `2**53-1`). IDs outside the supported range require a schema revision.

`left`/`right`/null is a **local supported projection vocabulary**, not a verified
inventory of all MaleCNS or neuPrint `somaSide` values. Other values such as `L`,
`R`, `midline`, `bilateral`, and `unknown` are rejected, never guessed or converted
to null. Live integration must first establish the actual source vocabulary and
record any explicitly reviewed transformation; this task provides no adapter.
`class` is treated as an opaque source label, with no claimed ontology.

Null records unavailable/unknown metadata in the input; it does not mean midline,
bilateral, contralateral, ipsilateral, or any scientific side. Soma side does not
establish projection or functional laterality. IDs, instance suffixes, cell types,
and class labels never supply inferred laterality. Nonblank strings are retained
exactly, including whitespace and Unicode; blank strings and lone surrogates fail.

## Artifact and provenance

The returned fresh dictionary has exactly `schema_version` (`annotation-v1`),
`dataset` (`male-cns:v1.0`), `source_note`, `extraction_commit`, and `records`.
Records are sorted numerically by body ID. Duplicate IDs fail even if all metadata
matches. Empty input is valid and produces an empty list; it makes no completeness
claim. Input rows are never changed or aliased by output records.

Dataset and provenance apply to every record in the artifact. Retain the envelope
when storing or passing records downstream. `source_note` is a required nonblank
string identifying the source/evidence/query (and must identify synthetic fixtures
as synthetic). `extraction_commit` is a required full lowercase 40-hex Git SHA of
the extraction implementation. Together these retain the evidence note and
extraction commit required by the body-ID policy §7. They are caller assertions:
the validator does not prove that a SHA exists or that a note is truthful. Mixed
sources need separate artifacts. The normalizer performs no extraction or filtering;
source query details and any upstream transformations belong in the source note or
a referenced source manifest. No timestamp is generated, so identical inputs and
provenance yield identical output. Do not include credentials in metadata.

`annotations_to_json(artifact)` revalidates every field, then emits compact JSON
with sorted keys, ASCII escaping, exact integer tokens, and no trailing newline.
`annotations_from_json(text)` requires a string, rejects duplicate object keys and
nonfinite JSON numbers, revalidates the entire envelope and all records, and sorts
records. Altered datasets/schema versions, unknown fields, and invalid metadata
fail with `AnnotationError` (a `ValueError`). Returned dictionaries remain mutable;
serialization always revalidates them. This API is not a streaming or size-limited
untrusted-file ingestion service; callers must enforce their own payload limits.

## Synthetic example

```python
from microduck_connectome.annotations import (
    normalize_annotations, annotations_to_json, annotations_from_json,
)

artifact = normalize_annotations(
    [{"bodyId": 1, "type": "synthetic-type", "instance": "synthetic_R",
      "somaSide": None, "class": None}],
    dataset="male-cns:v1.0",
    source_note="Synthetic documentation fixture; no biological evidence",
    extraction_commit="a" * 40,  # Synthetic SHA; real extraction uses its real SHA.
)
encoded = annotations_to_json(artifact)
assert annotations_from_json(encoded) == artifact
assert artifact["records"][0]["soma_side"] is None
```

Run offline validation from the repository root:

```text
python -m unittest discover -s tests -v
```

The annotation tests cover provenance preservation, null semantics, ordering,
nonmutation, exact large IDs, JSON roundtrip, duplicate IDs/JSON keys, invalid
containers and metadata, and envelope tampering. P1-01's transport tests remain
part of the same suite. No network or credentials are used. Population selection,
graph extraction, live vocabulary verification, and biological interpretation
remain outside P1-02.
