# Connectivity extraction v1 (P1-03)

`microduck_connectome.connectivity.extract_connectivity` produces a bounded,
offline induced edge table. It applies the full-source outgoing normalization in
NEURAL_MODEL_SPEC §§4–5 and the manifest requirements in
DATA_AND_REPRODUCIBILITY_POLICY §§6–7. No dependencies are added.

## Inputs and completeness

```python
extract_connectivity(
    annotation_artifact, rows, *, dataset, source_sha256, confidence_filter,
    extraction_commit, created_utc, query_or_extraction_config,
    seed_populations, readout_populations, selection_rules,
)
```

The complete validated [P1-02 annotation artifact](ANNOTATION_SCHEMA.md) defines
the selected body-ID set. The function revalidates its envelope and every record,
retains a canonical copy and all provenance, and makes no type or side inference.
Null cell types remain null. Selected nodes without edges remain in the artifact.

`rows` is a list/tuple of mappings with exactly `body_pre`, `body_post`, `weight`.
Endpoints are exact Python integers in `1..2**63-1`; weights are positive Python
integers. Strings, floats, booleans, zero/negative values, missing/extra fields,
and duplicate `(body_pre, body_post)` pairs fail. Parallel source contributions
must be explicitly aggregated upstream into one exact weight per directed pair;
the extractor never silently deduplicates or aggregates duplicates. Self edges
are supported. All supplied rows are validated, including unselected sources.

**The caller must provide all retained-confidence outgoing rows for every selected
source before target selection.** External targets do not require annotations.
Rows from unselected sources are permitted but not required. Their weights do
not contribute to selected-source sums. The caller must assert true zero-outgoing
status when a selected source has no rows. The API cannot distinguish an omitted
row from an absent edge and does not independently verify source completeness,
confidence rules, source hashes, or code SHA existence. It applies no confidence
or weight threshold of its own. Partial target-filtered queries are invalid input
even though this boundary cannot detect them.

Explicit metadata:

| Argument | Contract |
|---|---|
| `dataset` | Exactly `male-cns:v1.0`, matching annotations |
| `source_sha256` | 64 lowercase hex characters identifying the upstream source file/artifact; caller supplied, not recalculated from provided rows |
| `confidence_filter` | Nonblank Unicode description/reference of the frozen confidence and weight rules defining source outgoing totals |
| `extraction_commit` | Full lowercase 40-hex extraction implementation Git SHA |
| `created_utc` | Valid timestamp, exactly `YYYY-MM-DDTHH:MM:SSZ`; supplied by caller |
| `query_or_extraction_config` | Nonblank Unicode path/hash or explicit description identifying the source extraction configuration |
| `seed_populations`, `readout_populations` | Lists/tuples of distinct nonblank population names, sorted canonically; empty means no role assigned, not inferred |
| `selection_rules` | Nonblank Unicode description/reference of node selection and path/depth/filter rules; explicitly state when no path/depth expansion is performed |

Source queries and transformations must be traceable through the configuration
and provenance notes. Do not put credentials in these strings. Synthetic inputs
must be identified as synthetic. Population names are provenance labels, not a
membership resolver or a claim that the selected nodes have biological roles.

## Output and reproducible identity

The fresh mutable dictionary contains exactly `schema_version` (`connectivity-v1`),
`annotations`, `edges`, `full_outgoing_sums`, and `manifest`. No input containers
are mutated or shared with output. The function is deterministic for identical
input content and metadata; no clock, random seed, network, or filesystem is used.

`edges`, sorted numerically by source then target ID, includes only pairs whose
two endpoints are selected. Each record contains `source_body_id`,
`target_body_id`, exact `raw_synapse_weight`, `normalized_weight`, `source_type`,
`target_type`, and `provenance_dataset`. Normalization divides the raw weight by
the selected source's sum over **all supplied outgoing targets**, not merely
selected targets. Consequently shrinking the selected target set does not change
surviving weights when complete outgoing rows and filters stay fixed.

`full_outgoing_sums` is a body-ID-sorted list of `{body_id, raw_weight_sum}` records
for every selected node, including zeros. Raw weights and sums use arbitrary
precision Python integers (no int64 accumulation overflow). Normalized weights
use Python float rounding; pathological positive ratios that underflow to zero
fail explicitly. JSON consumers must preserve integer tokens rather than parse
IDs or counts through JavaScript Number. Callers must bound payload sizes and
respect Python's integer-to-JSON size limits; this is not a bulk/streaming or
untrusted-input service.

The manifest contains all required graph fields: `dataset`,
`extraction_tool_version` (the extraction commit), `query_or_extraction_config`,
`created_utc`, `node_count`, `edge_count`, `raw_weight_sum`, `body_id_set_hash`,
`edge_table_hash`, `seed_populations`, `readout_populations`, and `selection_rules`.
It also retains `source_sha256`, `confidence_filter`, `normalization_scope`, an
explicit caller-assertion `source_completeness` statement, and these measured
counts/hashes:

| Field | Hashed/counted content |
|---|---|
| `node_count`, `edge_count`, `raw_weight_sum` | Selected annotation nodes, induced edges, sum of induced raw edge weights |
| `body_id_set_hash` | Sorted selected integer ID list |
| `edge_table_hash` | Entire sorted induced edge list, including types, dataset and normalized values |
| `annotation_artifact_hash` | Entire canonical validated annotation artifact, including annotation provenance |
| `source_edge_count`, `source_raw_weight_sum` | All supplied source rows, including any rows from unselected sources |
| `source_edge_table_hash` | All supplied source rows, sorted by `(body_pre, body_post)` |
| `full_outgoing_sums_hash` | Entire sorted selected-source denominator list |

Each computed hash is SHA-256 of UTF-8 bytes from Python `json.dumps` with
`sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False` and
no trailing newline. `source_sha256` identifies the upstream file; it is distinct
from `source_edge_table_hash`, which identifies the caller's provided projection
(possibly only selected-source outgoing rows). Neither is proof of completeness.
The table hashes exclude the graph creation timestamp and extraction provenance;
preserve the entire manifest and annotation envelope, not just `edge_table_hash`,
for experiment identity. Changing confidence provenance can leave a content hash
unchanged if the actual edge table does not change.

Invalid boundary inputs raise `ConnectivityError` (`ValueError`). Output remains
mutable and has no storage reader/writer or post-mutation validation API in this
task. Persist freshly returned artifacts with standard JSON and retain their
manifest; do not edit outputs and assume recorded hashes are still valid.

## Synthetic example and validation

```python
from microduck_connectome.annotations import normalize_annotations
from microduck_connectome.connectivity import extract_connectivity

annotations = normalize_annotations(
    [{"bodyId": i, "type": "synthetic", "instance": None,
      "somaSide": None, "class": None} for i in (1, 2, 3)],
    dataset="male-cns:v1.0", source_note="Synthetic documentation fixture",
    extraction_commit="a" * 40,
)
graph = extract_connectivity(
    annotations,
    [{"body_pre": 1, "body_post": 2, "weight": 3},
     {"body_pre": 1, "body_post": 99, "weight": 7}],
    dataset="male-cns:v1.0", source_sha256="b" * 64,
    confidence_filter="Synthetic fixture: retain all supplied edges",
    extraction_commit="a" * 40, created_utc="2026-09-17T00:00:00Z",
    query_or_extraction_config="Synthetic complete outgoing fixture",
    seed_populations=[], readout_populations=[],
    selection_rules="Synthetic annotation IDs; no path/depth expansion",
)
assert graph["edges"][0]["normalized_weight"] == 0.3
assert graph["full_outgoing_sums"][-1] == {"body_id": 3, "raw_weight_sum": 0}
```

Run `python -m unittest discover -s tests -p test_connectivity.py -v` for the
synthetic boundary suite, or `python -m unittest discover -s tests -v` for all
unit tests. Tests cover external unannotated targets, subgraph invariance, row
permutations, exact large counts, empty graphs/isolates, duplicate identities,
provenance and annotation tampering, nonmutation, and independent hash checks.
Real-source validation is a separate handoff; synthetic results do not establish
biological connectivity, verified population selection, or complete full-CNS
extraction. Bulk loaders/caches, runtime graph APIs, P1-04 and P1-05 are separate.
