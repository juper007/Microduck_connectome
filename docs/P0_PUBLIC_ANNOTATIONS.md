# Public MaleCNS annotation probe

Scope: P0 dataset-access preparation / P1 annotation-ingestion precursor.
Base: `6056aa892abc4bcc8879d2f1e76bcdee077ef495`; branch:
`feature/p0-public-annotation-probe`. This branch is independent of bootstrap PR #5.

The [official download page](https://male-cns.janelia.org/download/) provides a
public annotation file. `data/manifests/annotations-v1.json` records its exact URL,
project-observed SHA-256, row count, attribution and limited interpretation.
The SHA is a local pin established from the official HTTPS download, not an
upstream-signed checksum. Raw data remains in ignored `data/cache/`.

## Run on Thor

Use the Python 3.12.3 data environment installed from bootstrap PR #5 (its lock
contains pyarrow 25.0.1). This branch does not duplicate that environment lock.
From this checkout, using that environment's absolute Python path:

```sh
DATA_PYTHON=/home/juper007/projects/microduck-connectome-thor/connectome/.venv/bin/python
"$DATA_PYTHON" -m unittest discover -s tests -v
"$DATA_PYTHON" scripts/probe_annotations.py --output results/local/annotations.json
```

The script downloads only when the cache is absent, rejects changed bytes,
checks required field types, rejects null/nonpositive/duplicate body IDs,
and extracts exact type matches in body-ID order. Soma side is retained from
`somaSide`; it is not inferred from names or promoted to a functional side.
Missing side metadata is reported as UNKNOWN. An absent candidate fails loudly.

## Evidence observed on 2026-09-17

Source row count: 211,577. Six unit tests pass. A separate fresh download
produced byte-identical summary JSON compared with the first cached extraction.

| Exact type | Total | Soma L | Soma R |
|---|---:|---:|---:|
| DNa02 | 2 | 1 | 1 |
| LC10a | 275 | 135 | 140 |
| LPLC2 | 185 | 94 | 91 |

No evidence of connectivity, synaptic direction, functional sufficiency or
sensor-to-readout causality is claimed. These are candidate inventory counts,
not frozen controller populations. No graph normalization or neural runtime is
implemented here. Full outgoing-source sums will be needed before a runtime
subgraph can use the frozen normalization rule.

## Remaining gates

Authenticated neuPrint known-neuron query remains pending credentials. Public
access is not substituted for that specific Phase 0 criterion. Graph fixture,
neural step, complete configuration schema and independent full-phase review
also remain outstanding. Simulator GUI operation was confirmed by the user;
Thor GPU smoke/export evidence was recorded separately, not a Phase 0 sign-off.

Reviewer scope: complete branch diff, six tests, manifest/source correspondence,
canonical ordering and conservative biological interpretation. No safety or
robot-facing behavior changes.
