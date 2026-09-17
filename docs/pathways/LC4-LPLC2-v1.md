# P2-01 pathway card v1 — LC4 and LPLC2

Dataset: **male-cns:v1.0**, official flat-connectome `minconf-0.5` release.
Owner: connectome-researcher. Independent review: pending; this card does not
declare Gate G2 passed. Task: [P2-01](../tasks/P2-01.md).

## Decision and scope

**Accept LPLC2 as the initial looming sensory candidate** for the MVP evidence
handoff. **Accept LC4 as a complementary sensory candidate** for comparison and
future size/velocity experiments. Exact source identities and direct connectivity
can be checked independently of functional interpretation. Neither type is
interchangeable with the other merely because both respond to looming.

**Reject promotion of this card into a complete validated stop pathway.** No
descending robot readout is selected here. The two source-annotated DNp01 bodies
are connectivity probe targets, not an approved decoder. P2-03 must separately
validate the GF/DNp01 interpretation; the MVP descending-readout gate stays open.
No sensory current, gain, threshold, sign, or robot command is frozen by this card.

## Exact release identities

The machine-readable [direct-evidence-v1.json](../evidence/p2-01/direct-evidence-v1.json)
contains **every body ID with its exact type, instance, raw somaSide, class,
superclass, and somaNeuromere** under `populations`. This is the complete identity
enumeration, not a representative list. Its rows are checked against the committed
[G1 inventory](../evidence/g1/pathway-report.json) before extracting connectivity.

| Exact type | Total | somaSide L | somaSide R | Source superclass | Role here |
| --- | ---: | ---: | ---: | --- | --- |
| LC4 | 126 | 71 | 55 | visual_projection | Complementary sensory candidate |
| LPLC2 | 185 | 94 | 91 | visual_projection | Initial sensory candidate |
| DNp01 | 2 | 1 | 1 | descending_neuron | Structural query target only |

DNp01 body `10001` has `somaSide=R`, `instance=DNp01(GF)_R`; body `10010`
has `somaSide=L`, `instance=DNp01(GF)_L`. The parenthetical GF string is source
annotation evidence, not an independent homology, physiology, or robot mapping
validation. No alias search, FlyWire/FANC ID substitution, or literature-derived
body number is used. L/R means the recorded soma side, not receptive-field or
axonal side. All LC4/LPLC2 `class` and `somaNeuromere` fields are null; this does
not establish absent anatomy. Counts refer to the flat annotation population,
not a neuPrint `Neuron` label selection. Unequal left/right counts are preserved;
no cells are invented or discarded to force symmetry.

## Biological evidence and strength

| Claim | Primary evidence | Strength and boundary |
| --- | --- | --- |
| LPLC2 detects focal outward motion through radial motion opponency. | Klapoetke et al. 2017, [DOI:10.1038/nature24626](https://doi.org/10.1038/nature24626); [author institution record](https://www.janelia.org/publication/ultra-selective-looming-detection-radial-motion-opponency). Single-cell anatomy and in vivo calcium imaging relate dendrite arrangement to looming selectivity. | **Experimentally demonstrated** in that study; **literature-supported but not demonstrated in MaleCNS** for these 185 exact cells. High confidence in type-level sensory candidacy. |
| LC4 and LPLC2 provide different components of the GF looming response. | Ache et al. 2019, [DOI:10.1016/j.cub.2019.01.079](https://doi.org/10.1016/j.cub.2019.01.079); [author institution record](https://www.janelia.org/publication/neural-basis-for-looming-size-and-velocity-encoding-in-the-drosophila-giant-fiber-escape). EM reconstruction identifies direct input; silencing and patch clamp support the LPLC2 size component and LC4 velocity component. | **Experimentally demonstrated** in the cited preparations; **literature-supported but not demonstrated in MaleCNS**. The model and response decomposition do not specify robot gain or a universal stimulus-response law. |
| The selected exact MaleCNS sensory bodies connect directly to source type DNp01. | Hash-verified official source query in [reproduction record](../evidence/p2-01/README.md), with pair-level weights and complete input identities. | **Connectomic inference** only. High confidence in recorded structural edges at the pinned confidence filter; no inference of causal effect, transmitter sign, or escape probability. |
| A direct, unilateral sensory-to-GF description is incomplete. | Jang et al. 2023, [DOI:10.1242/jeb.244790](https://doi.org/10.1242/jeb.244790); [primary article abstract](https://pubmed.ncbi.nlm.nih.gov/37066993/). Electrophysiology demonstrates bilateral visual integration, including contralateral input through an unidentified route. | **Experimentally demonstrated** in the cited study; **literature-supported but not demonstrated in MaleCNS**. This limits interpretation of the bounded direct-edge query. |

Sources were accessed 2026-09-17. Literature here supports functional candidacy;
it does not transfer a different specimen's IDs, synapse counts, or experimental
parameters into MaleCNS. No assertion of exhaustive literature coverage is made.

## Downstream connectivity

The versioned query selects all exact LC4 and LPLC2 bodies and both exact DNp01
bodies. It scans the full pinned weight source once, retains directed one-edge
input-to-target connections, and sums duplicate body pairs. It records all outgoing
weights from each input type, including targets absent from the annotation file,
so an input's projection to DNp01 is not falsely normalized to 100%.

The [evidence record](../evidence/p2-01/README.md) tabulates every input-side/target
combination, connected input counts, and raw weights. `direct_edges` contains the
underlying body pairs; zero-count combinations are explicit. This is a targeted
downstream test, not an exhaustive inventory of escape pathways, other descending
neurons, intermediate neurons, neuropils, electrical connections, or VNC outputs.

## Contradictions and uncertainty

- **No functional contradiction resolved by counting synapses:** the literature's
  separate size/velocity contributions cannot be reconstructed from edge count
  alone. We do not rank LC4 versus LPLC2 efficacy by their total raw weights.
- **Bilateral integration challenges a unilateral simplification:** Jang et al.
  show contralateral contributions. A missing direct cross-soma-side edge in this
  query would not imply absent contralateral visual influence, nor does soma side
  identify the stimulus eye. Intermediate routes remain untested.
- **Coverage differs from exclusivity:** direct LC4/LPLC2 input to DNp01 does not
  establish these are the only looming-responsive populations or destinations.
  The source filter omits lower-confidence synapses and the graph is one specimen.
- **Annotation correspondence is provisional at the functional level:** exact
  type strings and the GF instance tag support lookup, but no physiological
  measurement in the MaleCNS specimen is available here. P2-03 owns the separate
  GF/DNp01 interpretation; an annotation mismatch must reopen that decision.
- **Missing anatomy and dynamics:** null somaNeuromere/class, no receptor-specific
  sign, membrane parameters, delays, or state dependence are resolved by this
  extraction. No robot performance or safety claim follows.

## Engineering mapping — hypothesis only

Proposed future mapping: camera/ToF approach evidence produces an engineered
`looming_strength` feature, which stimulates the validated LPLC2 candidate
population. A separately validated network/readout may later produce stop intent
through the existing safety gate and one frozen stop transport mechanism. LC4 can
be a separately parameterized comparison input when expansion velocity is measured;
this card does not drive both populations with identical currents.

That abstraction replaces fly retinal processing and maps escape-related evidence
to a robot **stop**, a project choice rather than a demonstrated biological
equivalence. Required follow-ups are sensory encoding/ablation tests, P2-03 and
final descending-readout validation, simulation, and the existing safety checks.
`robotd` retains motor ownership. No direct servo command or hardware experiment
is authorized by this research decision.
