# Derived graph cache (P1-04)

`microduck_connectome.graph_cache` provides a stdlib-only local cache for bounded
P1-03 `connectivity-v1` artifacts. This is a derived-artifact cache, separate from
raw source storage. Use an ignored directory such as `data/cache/graphs`.

```python
from microduck_connectome.graph_cache import graph_cache_key, store_graph, load_graph

expected_key = graph_cache_key(graph)
assert store_graph('data/cache/graphs', graph) == expected_key
restored = load_graph('data/cache/graphs', expected_key)
assert restored == graph
```

Store the expected key in the caller's trusted run/graph manifest. A read requires
that exact identity; there is no implicit latest entry or metadata-only lookup.
`graph_cache_key(graph)` validates without I/O; `store_graph(cache_dir, graph)`
validates and returns its key; `load_graph(cache_dir, expected_key)` returns a fresh
validated dictionary. Inputs are not mutated. Missing entries raise
`FileNotFoundError`, invalid graphs/keys/corruption raise `GraphCacheError`
(`ValueError`), and filesystem errors propagate as `OSError`.

## Identity and validation

The key is SHA-256 of the entire canonical graph JSON encoded as UTF-8, with
sorted object keys, separators `(',', ':')`, `ensure_ascii=True`,
`allow_nan=False`, and no newline. The entry is `<key>.json`; keys must contain
exactly 64 lowercase hexadecimal characters. Path-like keys fail before I/O.
The complete annotations, graph, outgoing sums and manifest are preserved.
Dataset, schema, source hash, extraction commit/configuration, selection/filter
rules, population labels, and creation timestamp all participate in identity.
A timestamp change intentionally creates another entry even when tables match.
No semantic deduplication across timestamps is promised. Unsupported datasets
and schemas are rejected, rather than sharing identities with supported data.

Both storage and reading validate the exact v1 fields, annotation records,
provenance syntax, fixed normalization/completeness statements, canonical list
ordering, unique edges, selected endpoints and their type/dataset labels, exact
integer counts, and normalization against full-source outgoing denominators.
They recompute the recoverable annotation, node-set, edge, and outgoing-sum
hashes and selected counts/weights. Source counts/weights must satisfy recoverable
lower bounds; when every source row is retained as an induced edge, its table
hash and totals are also recomputed. Reads additionally verify the exact file
byte digest against the expected identity, reject duplicate JSON keys and
nonfinite numbers, and require canonical bytes. Corrupt entries are never
returned or silently repaired by a subsequent write.

The original source table usually is not present. Its full hash, upstream file
hash, completeness, confidence provenance, code authenticity, and biological
validity cannot generally be verified from the derived graph. These remain
caller assertions. Self-consistent hashes provide integrity against an expected
identity, not proof of biological claims or upstream authenticity.

## Publication and limits

Writers serialize/validate first, create a unique temporary file in the selected
cache directory, write and flush it, call `fsync`, then atomically hard-link it to
the final name. Hard-link publication cannot replace an existing entry. A racing
winner is verified before success is returned. The temporary name is cleaned in
`finally`; a process killed before cleanup may leave an ignored `.graph-*.tmp`
file, never a partial final entry. Failed writes/fsync/publication leave previous
entries unchanged. Repeated storage validates an existing final entry.

The filesystem must support same-directory atomic hard links (e.g. NTFS and
ordinary Linux local filesystems); unsupported filesystems fail explicitly.
This is not a hostile shared-directory service: cache directories must be
trusted, and callers must bound artifact sizes. Symlink attacks, quotas, bulk
streaming, eviction, source downloads, migration, and crash cleanup are out of
scope. There is no directory fsync/power-loss durability guarantee: a power loss
may lose a newly published name; readers still verify all returned bytes.

## Validation

Run `python -m unittest discover -s tests -p test_graph_cache.py -v`.
The offline suite covers synthetic and committed real-graph roundtrips,
provenance/timestamp invalidation, invalid/path-like identities, malformed and
ambiguous JSON, corruption, semantic tampering with recomputed hashes,
empty graphs/isolates, large exact weights, fsync/publication failure injection,
and concurrent-winner validation. It needs no neuPrint access or new dependency.
Real-fixture roundtrip establishes storage fidelity only; it does not expand the
scientific claims of P1-03.
