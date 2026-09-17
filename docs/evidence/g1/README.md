# G1 remediation: versioned pathway and rebuild evidence

## Scope and lineage

Resolves audit findings F1 (path/anatomy queries), F2 (pathway handoff), and F3
(portable source adapter/rebuild) for P1-02/P1-03/P1-05. Task packet:
[../../tasks/G1-remediation.md](../../tasks/G1-remediation.md).
Base: `72ffb1bf6921ce36d7c5073c1a97a8a15226f881`.
Evidence-producing executable commit: `bfddc9822630240a92b28359c1914792a8158ac7`.
Subsequent evidence-only commits do not change that executable tree. The producer
SHA is intentionally frozen; substituting the later documentation commit changes
provenance bytes and therefore hashes. Final-head independent gate review is
reported in the PR, avoiding a self-referential reviewed-commit claim here.

## Reproduce from a clean checkout

Use Python 3.12 and the committed `uv.lock`; run from the repository root. The
public inputs require no credential. `--download` downloads missing source files
and verifies their pinned SHA256. Existing hash-matching files may be reused.

```sh
uv sync --locked
producer=bfddc9822630240a92b28359c1914792a8158ac7
# Checkout the producer above, or verify the final evidence-only commit has
# identical executable/config/manifest/lock content before retaining this SHA.
for run in run1 run2; do
  uv run --locked python -m microduck_connectome.rebuild_pathway \
    --annotations data/cache/body-annotations.feather \
    --weights data/cache/connectome-weights.feather \
    --output-dir results/$run --code-commit "$producer" --download
  uv run --locked python -m microduck_connectome.query_pathway_report \
    --report results/$run/pathway-report.json \
    --output results/$run/query-report.json --code-commit "$producer"
done
for file in pathway-report.json query-report.json source-metadata.json; do
  cmp results/run1/$file results/run2/$file
  cmp results/run1/$file docs/evidence/g1/$file
  sha256sum results/run1/$file
done
uv run --locked python -m unittest discover -s tests
```

The graph cache is generated under each output directory and intentionally not
versioned. Source files and large caches are not included in this evidence.
The configuration timestamp is a fixed reproducibility label, not execution time.

## Validation observed on Thor

Python 3.12.3, locked project environment: **99 tests passed**. The implementation
team ran the full public-source pipeline twice. A non-author reviewer independently
extracted a clean producer archive, ran all 99 tests and the full pipeline twice.
All four executions produced the same three report hashes below. The reviewer's
local Git archive and pre-existing Thor archive independently matched SHA256
`a901905733ac89fc11349cc1d50503cb8383273bec4b9f3d9896aa8c3b02b4be`.

| Versioned artifact | SHA256 |
| --- | --- |
| pathway-report.json | `5eeed1f5fb5c43af80f08f42c8eaebac97e3d8c8c4c39f7d70d6902b9d7d6407` |
| query-report.json | `bf7cb25c774e08415f76dfc63b77d17acf2ada0671317ffb755888d38d6c5d1e` |
| source-metadata.json | `4748b141ba5a6c28f093ad225a610c59abc4a934c2318377ec8b9ad1c7ed2a99` |

Source dataset is `male-cns:v1.0`. Annotation source: 211,577 rows, SHA256
`2177e246113e4cfbf1e7772ec37c6da1955ff22e8063d0b1f833101f99a9a3b2`.
Weight source: 151,856,684 rows, SHA256
`e35da783d1c686b2b58b3b87cd6a403ae43bfcfba8bff28e08ef752c1a56afc1`.
The committed source manifest records download URLs; the report embeds the
manifest, selection config, hashes, code identity and graph manifest.

## Pathway handoff and limits

Exact annotation type counts: LC10a 275, LC4 126, LPLC2 185, DNa02 2, DNp01 2,
DNge104 2, MDN 4. Full body IDs and source annotation records are in the report.
This inventory refers to the flat-file annotation population, not a neuPrint
`Neuron` label population.

The engineering selection LC10a -> annotated intermediate -> DNa02 contains
570 nodes (275 seeds, 293 intermediates, 2 readouts) and 21,142 induced edges.
All 947,198 outgoing source rows of selected bodies contribute to normalization
before subgraph filtering; surviving edges are not renormalized.
Graph cache key: `340f6a3180026f6c61f19ebc016ae8610ec9f4a07af2af589e4d6d89e5b31f70`.
Queries find 547 reachable seed/readout pairs and 6,571 simple two-edge paths.

Raw L/R side annotations are explicitly adapted to left/right; raw values remain
in the evidence. No side is inferred from body IDs, query order or type names.
The selected graph has 11 source-labeled descending neurons. Its superclass
population contains no `vnc_intrinsic` nodes, so the cross-population query is
empty **within this selected graph**. This is not evidence that whole MaleCNS
lacks brain/VNC connections. Only 14 selected bodies have a known somaNeuromere
(CG); 556 are unknown. Soma location is not projection anatomy.

These are structural observations and an engineering graph selection, not proof
of pathway function, activation sign, sensory mapping, behavior or robot control.
Phase 2 must validate those claims and broaden/extract other candidate pathways
where required. The query API supports explicit source-label selection in either
direction; it does not infer projection anatomy. No actuator/robotd ownership or
frozen neural normalization rule changes.

Prior non-blocking audit F4 remains: the older annotation probe summary omits its
producing code SHA. This new pathway/metadata/query evidence records code identity;
the precursor probe's provenance improvement remains a separate follow-up.
