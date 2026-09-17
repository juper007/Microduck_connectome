# P2-01 v1 — LC4/LPLC2 structural evidence

Interpretation and scoped decision: [pathway card](../../pathways/LC4-LPLC2-v1.md).
Task/base: [P2-01 packet](../../tasks/P2-01.md),
`8fb7d635e4227e88d4894505d59359ed3e037df2`.
Evidence-producing executable commit:
`ab867874b4019471e1dd5a6cfd28d69b32774d70`.
Later documentation/evidence commits preserve the extraction code and source
manifest. Keep this producer identity when comparing exact evidence bytes.

## Reproduce

Use Python 3.12 and `uv sync --locked` in a clean checkout of the producer above.
The source files are public, pinned in
[`pathway-source-v1.json`](../../../data/manifests/pathway-source-v1.json), and
acquired using the existing G1 download/rebuild procedure if not already cached.
The P2 query requires local source files; it never silently substitutes a live
neuPrint release or downloads a different annotation version.

```sh
uv sync --locked
producer=ab867874b4019471e1dd5a6cfd28d69b32774d70
for run in run1 run2; do
  uv run --locked python -m microduck_connectome.looming_evidence \
    --annotations data/cache/body-annotations.feather \
    --weights data/cache/connectome-weights.feather \
    --code-commit "$producer" --output results/p2-01/$run.json
done
cmp results/p2-01/run1.json results/p2-01/run2.json
cmp results/p2-01/run1.json docs/evidence/p2-01/direct-evidence-v1.json
sha256sum results/p2-01/run1.json
uv run --locked python -m unittest discover -s tests
```

The versioned result is added after the producer commit. For the second `cmp`,
use the reviewed final branch or copy its evidence file into the producer checkout;
verify executable and manifest equality before retaining the producer SHA.

## Provenance and query semantics

Every byte of both Feather files is hash checked using the G1 source adapter.
Annotation schema, distinct body IDs, full weight row count, and positive integer
weight fields are checked. Exact LC4/LPLC2/DNp01 source records must match the G1
inventory, including sides, before any result is produced. Hashes prove consistency
with project-pinned public downloads, not an upstream signature.

| Input | Rows | SHA256 |
| --- | ---: | --- |
| Official annotations | 211,577 | `2177e246113e4cfbf1e7772ec37c6da1955ff22e8063d0b1f833101f99a9a3b2` |
| Official weights | 151,856,684 | `e35da783d1c686b2b58b3b87cd6a403ae43bfcfba8bff28e08ef752c1a56afc1` |
| Committed G1 pathway inventory | — | `5eeed1f5fb5c43af80f08f42c8eaebac97e3d8c8c4c39f7d70d6902b9d7d6407` |

Dataset is `male-cns:v1.0`; weights are the official `minconf-0.5` file. Selection
is all 311 exact LC4/LPLC2 bodies to both exact DNp01 bodies, directed and direct
only. There is no additional weight threshold. Duplicate body pairs, if present,
are summed. All outgoing weights from each input type are counted before target
filtering. No normalized runtime graph or inferred neurotransmitter sign is made.
The evidence embeds the full source manifest, configuration, their SHA256 values,
G1 inventory hash, and producer SHA. No random seed is needed.

## Validation and observed results

The coordinating agent ran the producer on Thor in the existing locked Python
3.12 environment: **105/105 tests passed** (99 existing plus 6 P2-01 tests).
Two complete source extractions were byte-identical. This is author-team
validation, not independent scientific/code review. The returned evidence hash
was independently checked against the local file before committing.

`direct-evidence-v1.json` SHA256:
`6a291dff90ddbe14916f814d2181135758f12d402bb05653dfc395aa3dd1d878`.
Config SHA256: `59ae5aeac35388eb185adfb32c578bb4cc3b5335817916d53addb244db45141b`.
Canonical source-manifest SHA256:
`ac287e6c54e0fe689e4ed66f347a99fcf2fc3c7f27c179ee5eb19ec3d5bd0c14`.

One scan examined 151,856,684 weight rows, including 270,629 rows originating
from the selected inputs. The result contains 311 unique direct body pairs.

| Input type | Raw soma side | Input cells | Target body (soma side) | Connected inputs | Raw weight |
| --- | --- | ---: | --- | ---: | ---: |
| LC4 | L | 71 | 10001 (R) | 0 | 0 |
| LC4 | L | 71 | 10010 (L) | 71 | 3,782 |
| LC4 | R | 55 | 10001 (R) | 55 | 2,580 |
| LC4 | R | 55 | 10010 (L) | 0 | 0 |
| LPLC2 | L | 94 | 10001 (R) | 0 | 0 |
| LPLC2 | L | 94 | 10010 (L) | 94 | 2,642 |
| LPLC2 | R | 91 | 10001 (R) | 91 | 2,220 |
| LPLC2 | R | 91 | 10010 (L) | 0 | 0 |

All-outgoing raw weights are LC4 **258,240** and LPLC2 **347,196**. The queried
targets receive 6,362 and 4,862 respectively. These denominators describe source
output counts, not neuronal efficacy, postsynaptic response, or sign. Every input
cell has a recorded same-soma-side direct target in this release. The cross-side
zeros concern this one-edge query and this source filter only; they do not imply
absent cross-eye integration or absent indirect connections.

The synthetic tests exercise directed selection, exact type matching, duplicate
pair aggregation, unannotated-target denominators, unknown soma sides, zero
connections, deterministic bytes, source-hash/row-count drift, G1 identity drift,
dataset/manifest mismatches, and malformed producer identity. Local `py_compile`
and `git diff --check` also passed. No simulator or hardware test applies to this
research/evidence-only change.

## Scientific limits and next handoff

This is a reproducible structural probe, not a complete pathway reconstruction.
Only DNp01 is queried downstream. Intermediate routes, other descending targets,
electrical coupling, projection-side anatomy, and sensorimotor response dynamics
remain outside its scope. The raw source instance contains `GF`, but interpreting
that as the physiological GF and choosing a robot readout remains P2-03 work.
The pathway card separates demonstrated literature claims, MaleCNS structural
inference, and the engineered looming-to-stop proposal. No hardware behavior,
motor ownership, safety limits, or runtime normalization changes.

Independent review and final-head approval are pending. Neither this report nor
its author declares Gate G2 complete.
