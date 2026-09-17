# Read-only graph API (P1-05)

`microduck_connectome.graph.ConnectomeGraph` exposes validated `connectivity-v1`
artifacts to future consumers. It uses the existing `graph_cache_key` validation
boundary and adds no schema, biological inference, dynamics, or persistent format.

```python
from microduck_connectome.graph import ConnectomeGraph

graph = ConnectomeGraph(artifact)  # detached snapshot; validates the entire artifact
# Or: graph = ConnectomeGraph.from_cache(cache_directory, expected_key)
population = graph.select_type("exact source cell type")
view = graph.induced(population)
for body_id in view.body_ids:
    annotation = view.node(body_id)
    for edge in view.outgoing(body_id):
        raw = edge["raw_synapse_weight"]
        normalized = edge["normalized_weight"]
```

| API | Result |
| --- | --- |
| `body_ids` | Sorted tuple of current IDs, including isolates |
| `nodes()`, `node(id)` | Tuple of annotation dictionaries, or one dictionary |
| `edges()`, `edge(source, target)` | Tuple of directed edges, or one edge/`None` |
| `incoming(id)`, `outgoing(id)` | Edge tuples ordered by source/target ID |
| `select_type(name)` | Sorted IDs with exactly that source `cell_type` |
| `select_type(None)` | IDs explicitly annotated with unknown (`null`) type |
| `full_outgoing_sum(id)` | Exact integer source normalization denominator |
| `induced(ids)` | Read-only view on selected current nodes and connecting edges |
| `root_key` | Original artifact's validated cache/content identity |
| `root_manifest` | Detached original extraction manifest |
| `annotation_provenance` | Detached original annotation metadata, excluding records |

All body IDs must be Python integers in `1..2**63-1`; booleans, floats, strings,
and out-of-range IDs raise `ValueError`. Valid IDs absent from the current graph
raise `KeyError`, including either endpoint of an edge lookup. A missing edge
between present nodes returns `None`. Type matching is case-sensitive and exact:
there is no trimming, wildcard, or inferred type. Nonblank Unicode strings and
`None` are supported; other values raise `ValueError`. Unmatched names return `()`.

Nodes are ordered by ID; edges by `(source, target)`. Induction accepts an iterable,
deduplicates IDs after validating each value, and preserves isolated nodes.
Nested views may only select current nodes; they cannot recover excluded nodes.
Empty views and self-loops are supported. Input and returned dictionary mutations
cannot change the internal graph or another view. The public API has no mutation
methods; private implementation attributes are not an access contract.

Surviving raw/normalized weights and full-source outgoing sums remain exact copies
of the root artifact. They are never recalculated for a view. Queries see only
edges present in the artifact/current view, not all source connectivity. Source
completeness remains the extraction's caller-supplied assertion, not a guarantee
added by validation or this API.

`root_key`, `root_manifest`, and `annotation_provenance` retain the original root
through every nested view. Root counts/hashes describe the original artifact,
not the view; use `len(view.body_ids)` and `len(view.edges())` for current counts.
A root key alone does not uniquely identify a view; its sorted IDs must also be
retained when describing a selection. Views have no extraction-artifact serializer
and must not be passed to `store_graph` as if freshly extracted.

Construction validates and indexes the bounded artifact in O(nodes + edges) time
apart from canonical JSON encoding/hashing. Views scan current edges and build
their own adjacency indexes, sharing private root records. Records returned by
queries are copies; this API is not a bulk graph loader or sparse neural runtime.

Validation: `python -m unittest discover -s tests -p 'test_graph*.py' -v`.
Tests include the committed P1-03 real artifact through cache loading and nested
views, alongside synthetic directed, isolated, empty, self-loop, mutation, invalid
input, exact-large-integer and normalization cases. Passing these tests does not
complete the independent Phase 1 gate.
