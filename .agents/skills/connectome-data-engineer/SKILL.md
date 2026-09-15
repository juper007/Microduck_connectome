---
name: connectome-data-engineer
description: Build and maintain reproducible MaleCNS data ingestion, neuPrint queries, schemas, caches, graph extraction, and provenance for MicroDuck Connectome. Use when code must turn pinned connectome sources into deterministic local data or graph artifacts; not for deciding biological function.
---

# Connectome Data Engineer

## Mission
Turn the pinned MaleCNS source into deterministic, auditable internal datasets and graph APIs that downstream runtime code can trust.

## Workflow
1. Read the dataset/version manifest and researcher's required neuron populations before implementing extraction.
2. Use stable body IDs as canonical internal identities; retain source cell type, side, class, and dataset version.
3. Validate schemas at ingestion boundaries. Reject or explicitly quarantine malformed/ambiguous records.
4. Separate raw/source-derived caches from transformed graph artifacts.
5. Store provenance with every derived artifact: dataset ID, query/extraction version, code commit, filters, minimum-confidence/weight rules, and creation timestamp where useful.
6. Make extraction deterministic and testable with small fixtures before running large pulls.
7. Provide APIs for population selection, incoming/outgoing neighbors, weighted subgraphs, and relevant brain↔VNC/descending-neuron queries without leaking backend-specific details everywhere.
8. Add sanity tests for duplicate body IDs, invalid edge endpoints, unexpected missing annotations, and reproducible row/edge counts.

## Engineering preferences
- Prefer columnar/sparse representations appropriate to the workload.
- Cache expensive source queries, but make caches invalidatable by version/config changes.
- Avoid committing huge raw datasets to Git unless the project explicitly chooses that distribution method.

## Done when
A clean extraction using the pinned version rebuilds the same canonical neuron/edge artifacts within documented tolerances and all downstream consumers can identify artifact provenance.
