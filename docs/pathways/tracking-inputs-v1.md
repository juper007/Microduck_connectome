# Tracking-input decision record — v1

Task [P2-05](../tasks/P2-05.md), Phase 2 / G2, assessed 2026-09-17.
Dataset **male-cns:v1.0**, official flat-connectome minconf-0.5 release.
Decision: **freeze all 275 exact LC10a bodies as the tracking sensory candidate
for subsequent simulation**, using the existing bilateral DNa02 readout.
Independent scientific review remains pending; this record does not pass G2.

## Criteria declared before selection

The task packet requires (1) exact source IDs/types/soma sides and provenance,
(2) experimental target-tracking relevance, (3) plausible directed routes from
both source soma groups toward bilateral DNa02, (4) explicit evidence coverage
and uncertainty, and (5) evaluation of looming/escape roles. These are qualitative
gates, not a post-hoc weighted score. A type name or path count alone is insufficient.
Only research identity is frozen; physiological side selectivity is not a gate
claimed to be experimentally satisfied by this structural data.

| Criterion | LC10a | LC4 | LPLC2 |
| --- | --- | --- | --- |
| Exact G1 inventory, all explicit source L/R | 275: 135 L, 140 R | 126: 71 L, 55 R | 185: 94 L, 91 R |
| Tracking relevance in primary evidence | Male courtship pursuit; subtype-specific LC10a evidence below | Reviewed sources support looming velocity, not target-following | Reviewed sources support radial expansion/looming, not target-following |
| Plausible route toward DNa02 | Both source soma groups have directed paths to both readouts | Not tested by the merged G1 query | Not tested by the merged G1 query |
| Coverage and uncertainty | Complete source IDs and bounded routes; state-dependent function, no signed efficacy | Complete IDs/direct GF edges; unmatched tracking-route coverage | Complete IDs/direct GF edges; unmatched tracking-route coverage |
| Looming/escape overlap | Not shown to be exclusively tracking; responds to other stimuli; escape output not exhaustively audited | Strong documented GF/escape association | Strong documented GF/escape association |
| Decision | Select candidate identities | Do not select for tracking; retain complementary looming role | Do not select for tracking; retain initial looming role |

This comparison does **not** establish LC4/LPLC2 lack DNa02 paths or rank the
three types' steering efficacy. G1 deliberately selected an LC10a graph, so
cross-candidate structural coverage is asymmetric. Stronger tracking evidence
plus the required LC10a route gate suffices for a first candidate, not for an
optimality claim. Reopen the comparison if simulation fails or a new candidate
has stronger tracking evidence; any new route extraction belongs to the existing
data-engineering workflow with the same pinned sources and explicit query scope.

## Identity, provenance and freeze

The [frozen selection](../evidence/p2-05/tracking-selection-v1.json) enumerates
every selected LC10a body with exact source `type`, `instance`, `somaSide`,
`superclass`, `class`, and `somaNeuromere`; all alternative input IDs are also
enumerated by raw-source soma side. Selected LC10a records have
`superclass=visual_projection`, `class=null`, `somaNeuromere=null`. Nulls do not
establish absent anatomy. L/R maps literally to left/right; ID magnitude, order
and instance suffix never determine side. No symmetry balancing or reachability
filter discards cells. This is the flat annotation population, not a neuPrint
`Neuron`-label census. LC10, LC10b/c/d, and other datasets' IDs are not substitutes.

DNa02 remains `523769` with source `somaSide=L`, and `10360` with `somaSide=R`,
both exact source type DNa02 and superclass descending_neuron. Its steering
evidence and limitations remain those of [P2-02](DNa02-v1.md).

Every selected record is checked against both G1 inventory and selected graph
metadata. The validator uses the existing DNa02 evidence API and pins all seven
merged G1/P2-01..04 report hashes. It preserves official source URLs, the source
annotation/weight hashes, and G1 producer commit. The official
[LC10a explorer](https://reiserlab.github.io/celltype-explorer-drosophila-male-cns/types/LC10a.html)
also reports 275 cells (135 left/140 right), checked 2026-09-17; this live page
corroborates counts but is not the byte-pinned identity authority.

P2-01/P2-03 establish direct looming-population input to DNp01/GF, motivating
the contamination comparison. P2-04 identifies backward-locomotion MDNs; those
are neither tracking sensory inputs nor a substitute for the DNa02 readout.
Their merged hashes record the evidence set considered, not a claim that all
four cards demonstrate an LC10a tracking chain.

## Directed lateralized structural evidence

**Connectomic inference:** in the reviewed 570-node, 21,142-edge G1 induced graph,
at raw weight >=1 and at most two directed hops:

| Source soma group | DNa02 soma/ID | Reachable input bodies | Simple two-edge paths |
| --- | --- | ---: | ---: |
| LC10a L | L / 523769 | 135 / 135 | 2,137 |
| LC10a L | R / 10360 | 135 / 135 | 941 |
| LC10a R | L / 523769 | 140 / 140 | 1,224 |
| LC10a R | R / 10360 | 137 / 140 | 2,269 |

The lexicographically first examples in these four groups are respectively:
`10573 LC10a L -> 11219 LT82a L -> 523769 DNa02 L`;
`10573 LC10a L -> 10070 AOTU019 L -> 10360 DNa02 R`;
`21065 LC10a R -> 10005 AOTU019 R -> 523769 DNa02 L`;
`21065 LC10a R -> 10406 AOTU012 R -> 10360 DNa02 R`.
All example source records are preserved in the selection. These are inspectable
examples, not strength-ranked or causally validated intermediates. The full path
list remains in the hash-pinned G1 query report. Its enumeration can include
another seed/readout as intermediate; it does not restrict every middle cell to
an intrinsic class. No new weights or normalization are computed here.

Right-source LC10a IDs `76174`, `86507`, `100368` have no <=2-hop route to right
DNa02 in this graph, but do have paths to left DNa02; they remain selected under
the predeclared all-exact-type rule. This does not exclude longer/full-source
routes. Same-soma-side path counts exceed opposite-side counts, but paths share
neurons, lack signs/dynamics and are not independent samples. This pattern is
**not** evidence of stronger ipsilateral gain. Source soma side is neither visual
hemifield nor synaptic location. Bilateral reachability supports anatomical
plausibility and cannot establish a left-target-to-left-turn transfer function.

## Primary biological evidence and its limits

**Experimentally demonstrated in flies; literature-supported for these exact
MaleCNS IDs.** [Ribeiro et al., Cell 2018,
doi:10.1016/j.cell.2018.06.020](https://pubmed.ncbi.nlm.nih.gov/30033367/)
reports small-moving-object responses, impaired orientation/proximity after
LC10 silencing, and orienting/wing-extension effects of unilateral activation
in male courtship. The paper's broad LC10 wording cannot by itself resolve
MaleCNS LC10a identity or exclude other subtypes.

[Hindmarsh Sten et al., Nature 2021,
doi:10.1038/s41586-021-03714-w](https://www.nature.com/articles/s41586-021-03714-w),
especially Extended Data 7–10, provides subtype-specific support: unilateral
LC10a silencing suppresses ipsilateral target-directed turns in courting males;
P1-associated courtship state increases visual gain. Yet LC10a activity can
persist without the corresponding turn in a two-target stimulus, and responses
extend beyond small targets to other stimulus classes, including expansion.
These experiments therefore support state-dependent pursuit, not an exclusive
tracking channel or a universal motor signal. Its female hemibrain anatomy and
male trans-Tango observations are different evidence from this adult male EM
specimen; no cross-dataset body IDs or synapse counts are transferred.

[Klapoetke et al., Nature 2017,
doi:10.1038/nature24626](https://www.janelia.org/publication/ultra-selective-looming-detection-radial-motion-opponency)
uses anatomy/calcium imaging to support LPLC2 radial-motion looming selectivity.
[Ache et al., Current Biology 2019,
doi:10.1016/j.cub.2019.01.079](https://www.janelia.org/publication/neural-basis-for-looming-size-and-velocity-encoding-in-the-drosophila-giant-fiber-escape)
supports distinct LC4 velocity and LPLC2 size contributions to GF responses.
The [merged looming card](LC4-LPLC2-v1.md) and [DNp01 card](DNp01-GF-v1.md)
document exact MaleCNS edges and bilateral integration uncertainty. Their evidence
supports retaining these as looming candidates, not assuming generic target
tracking from visual-projection identity. Sex by assay is not resolved from the
accessed looming abstracts; no male-specific physiological validation is claimed.
All cited primary/official sources were checked 2026-09-17; coverage is bounded,
not an exhaustive literature review.

Confidence: high for pinned identity and reported paths; moderate for choosing
a fly tracking-relevant type; low for quantitative transfer to this network/robot.
Neither cited experiment demonstrates the exact LC10a -> DNa02 -> robot chain.

## Engineering choice and acceptance boundary

**Project engineering hypothesis:** later sensory encoding may map `target_x`
to the two source-soma LC10a groups and assess DNa02 activity, preserving the MVP
steering interface. Whole-population injection abstracts away retinal/receptive
field structure and courtship state; equal per-cell input is not established.
The freeze contains IDs, dataset, graph identity and a canonical config digest.
It does not set input currents, signs, gains, pooling, normalization or dynamics.
Future tests must establish sensory-coordinate mapping, neural readout response,
and calibrated simulator yaw. Neural output supplies behavior intent only;
robotd retains motor ownership and simulation precedes hardware.

Reject this version on any source/hash/type/side mismatch. Reopen selection if
the bounded paths disappear, later functional evidence conflicts, or tracking
simulation cannot meet its independent acceptance criteria. Do not fix failure
by silently exchanging populations, pruning asymmetric cells, or converting
raw path counts into controller gains. Freeze changes require a new reviewed
version. Independent review must assess the scientific interpretation as well
as deterministic validation; byte equality does not review literature claims.

## Reproduce

No network, Feather files or new extraction is needed for this bounded artifact.
Run in the project's locked Python 3.12 environment from the repository root:

```sh
python -m microduck_connectome.tracking_selection --check docs/evidence/p2-05/tracking-selection-v1.json
python -m unittest discover -s tests -p test_tracking_selection.py
python -m unittest discover -s tests
```

Explicit regeneration (deterministic JSON, sorted keys, ASCII, two-space indent,
LF and final newline; the same serialization defines `config_sha256`):

```python
from pathlib import Path
from microduck_connectome.tracking_selection import build_selection, canonical
Path("docs/evidence/p2-05/tracking-selection-v1.json").write_bytes(
    canonical(build_selection("docs/evidence")))
```

Artifact SHA256: `fd622d63ca9f9bf7d12d97700f78d6fcbbd9653c33f5dbce35254be027386c80`.
Config SHA256: `45e02be5a1a7870c7868b27cf1d2a18049a5b03c907d415d2e91fbffa38a46c4`.
Five focused tests pass on Python 3.12.13. Local full-suite discovery ran 105
entries: 101 passed, four imports failed because `pyarrow` is unavailable in
that interpreter. Full locked-environment validation and exact reviewed head
are recorded in the PR before integration. Failure tests cover every source
digest, invalid/ambiguous side/type/ID, order/instance independence, modified
selected IDs/readouts/routes/config, and attempts to rehash changed selections.
