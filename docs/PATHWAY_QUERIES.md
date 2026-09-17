# Bounded pathway and source anatomy queries

`microduck_connectome.pathway_queries` operates on `ConnectomeGraph` and its
induced views. Queries cannot recover connections excluded by the root extraction
or expand a nested view. Returned edges preserve raw weights, normalized weights,
and dataset provenance; the source denominator remains the root denominator.

```python
from microduck_connectome.pathway_queries import (
    shortest_path, descending_neurons, cross_region_edges,
)

path = shortest_path(graph, source_id, target_id, max_hops=2,
                     allowed_body_ids=graph.body_ids, min_raw_weight=1)
```

`shortest_path` returns a tuple of body IDs or `None`. Directed BFS minimizes hop
count and resolves ties by lexicographic body-ID order, independent of input row
order. `max_hops` is required, nonnegative and inclusive; a permitted identical
source/target returns a zero-hop path. A node is visited once, so cycles and
self-edges cannot cause unbounded traversal. Work is bounded by the current
graph and hop horizon, rather than enumeration of all possible paths.

Optional `allowed_body_ids` and `allowed_types` restrict **every** node, including
both endpoints. Type matching is exact and case-sensitive; include `None` to
permit unknown types. Empty allowed sets yield no path. `min_raw_weight` is a
positive integer inclusive edge threshold. This is not a weighted shortest-path
metric and never changes normalization. Invalid IDs/arguments raise `ValueError`;
IDs absent from the current view raise `KeyError`, including filter IDs.

Anatomical queries accept a separate source metadata envelope:

```python
source_metadata = {
    "dataset": "male-cns:v1.0",
    "source_sha256": annotation_source_sha256,
    "extraction_commit": extraction_code_commit,
    "source_note": "Hash-verified official annotation source; see source manifest",
    "records": raw_selected_annotation_records,
}
descending = descending_neurons(
    graph, source_metadata, superclass_labels=["descending_neuron"])
crossing = cross_region_edges(
    graph, source_metadata, region_field="superclass",
    source_regions=["cb_intrinsic"], target_regions=["vnc_intrinsic"])
```

The example vocabulary is taken from the project's pinned official MaleCNS v1.0
annotation source (`data/manifests/annotations-v1.json`); each caller must retain
the source and evidence for its selected vocabulary. `cb_intrinsic` to
`vnc_intrinsic` selects only those source-defined intrinsic populations. It does
not represent all brain-to-VNC connections or prove axonal projection anatomy.
No label defaults, prefix inference, laterality inference or missing-value
imputation are implemented. Reverse direction requires a separate call.

The envelope requires exactly `dataset`, `source_sha256`, `source_note`,
`extraction_commit`, and `records`. The extraction commit must be a full lowercase
40-character Git SHA. Dataset must match the graph. Source SHA-256 must be 64 lowercase hex
characters; callers are responsible for actually verifying source bytes against
that digest before constructing the envelope. The query validates the envelope,
not the file digest or the scientific truth of caller-provided metadata.

Each record requires a unique integer `bodyId` in 1..2**63-1. Recognized source
fields `superclass` and `somaNeuromere` must be nonblank strings or null; omitted
fields are unknown. Other raw source fields are accepted but not interpreted.
Do not coerce empty strings, arbitrary types or duplicate rows into evidence.
Superset metadata is allowed, but query results only include current-view nodes.

`descending_neurons` returns `body_ids`, `unknown_body_ids`, selected exact labels,
`source_provenance` and `root_key`. The latter identifies the root artifact, not
the current view. Absent rows and null/missing superclass fields appear in
`unknown_body_ids`; known nonmatching values do not. Label matching itself does
not validate a neuron's biological function.

`cross_region_edges` defaults to `region_field="somaNeuromere"`, and also accepts
`"superclass"`. It returns detached `edges`, `source_body_ids`, `target_body_ids`,
`unknown_body_ids`, label sets, chosen field and the same provenance keys.
Nonempty disjoint source and target label sets are required. Missing values for
the selected field are explicit unknowns and are excluded from matching edges.
Soma regions describe soma location, not axonal projection or neuropil overlap.
In particular, missing `somaNeuromere` must not be interpreted as brain location.

These are observational graph queries. They do not establish biological
pathway validity, functional direction, robot mappings, or a Phase 2 gate pass.

## Reproduce query evidence from a rebuilt pathway

```shell
python -m microduck_connectome.query_pathway_report --report /cache/pathway-report.json --output /cache/query-report.json --code-commit FULL_QUERY_CODE_SHA
```

The command verifies the metadata file SHA-256 and the graph's expected cache
key, then checks report/config/source identity consistency before querying.
Artifact paths must be portable relative paths within the report directory,
including after symlink resolution. Output cannot replace any input artifact.
The raw annotation and connection files are verified by the preceding rebuild;
this command verifies consistency of the resulting artifacts, not an independent
signature or the raw files themselves.

Output includes report/metadata hashes, root graph identity, extraction and query
code commits, shortest paths for every configured seed/readout pair (at most two
hops), all simple two-edge paths, source-defined descending selections,
`cb_intrinsic` ↔ `vnc_intrinsic` edges in both directions, and known/unknown soma
metadata coverage. Two-edge path enumeration includes any distinct intermediate
in the selected induced graph, even another seed/readout; it does not reapply the
extraction's intermediate selection rule. Zero matching cross-population edges
only describes the selected graph. Identical inputs and code identity produce
byte-identical output without timestamps or machine-specific paths.
