# DNp01 / giant fiber pathway card v1

Task [P2-03](../tasks/P2-03.md); dataset `male-cns:v1.0`; assessed 2026-09-17.
Status: **accepted as an identifiable, literature-supported urgent-escape
candidate for independent G2 review**. A robot stop mapping remains an engineering
hypothesis; runtime selection and behavior validation remain open. This card does
not declare a phase gate passed.

## Exact population and alias resolution

The [official MaleCNS download](https://male-cns.janelia.org/download/) provides
pinned annotation and minconf-0.5 weight files. This is the full flat-file annotation
population, not a query restricted to the neuPrint `Neuron` label. The
[report](../evidence/p2-03/dnp01-report.json) preserves source fields, hashes,
all 311 selected sensory IDs/sides and all direct sensory-to-DNp01 edges.

| Role | Exact type / instance | MaleCNS body ID | Source somaSide |
| --- | --- | --- | --- |
| Right readout | DNp01 / DNp01(GF)_R | 10001 | R |
| Left readout | DNp01 / DNp01(GF)_L | 10010 | L |
| Candidate input | LC4 | 126 IDs in `input_records` | 55 R, 71 L |
| Candidate input | LPLC2 | 185 IDs in `input_records` | 91 R, 94 L |

Both readouts have `superclass = descending_neuron`, `class = null`,
`somaNeuromere = null`, `status = Traced`, and `statusLabel = Roughly traced`.
Do not treat `Traced` as proof of completeness. Side comes from `somaSide`, not
body ID or inferred projection anatomy.

There are **zero exact `type = GF` records** in the pinned annotations.
This does not mean giant fibers are absent: both DNp01 records explicitly contain
`(GF)` in `instance`, `hemibrainType = Giant Fiber`, and
`synonyms = Kennedy and Broadie 2018: GF`; `flywireType` and `mancType` are DNp01.
The token-bounded GF/giant-fiber audit across `type`, `instance`, `synonyms`,
`hemibrainType`, `flywireType`, and `mancType` finds only these two body IDs.
That is a bounded field audit, not an exhaustive search of every possible alias.
Foreign-dataset labels are cross-references, not interchangeable body IDs.
The literature nomenclature independently identifies GF as DNp01:
[Namiki et al., 2018, eLife](https://doi.org/10.7554/eLife.34272).

## Structural evidence in this pinned release

The builder scans all 151,856,684 weight rows, retains 11,380 rows incident to
the exact DNp01 bodies, and aggregates duplicate body pairs if any. No additional
threshold or graph normalization is applied. Weights are source connection weights,
not conductances, spike probabilities or behavioral effect sizes.

| Presynaptic type | Postsynaptic DNp01 | Connected source bodies | Sum of weights |
| --- | --- | ---: | ---: |
| LC4 | 10001 R | 55 | 2,580 |
| LPLC2 | 10001 R | 91 | 2,220 |
| LC4 | 10010 L | 71 | 3,782 |
| LPLC2 | 10010 L | 94 | 2,642 |

All 311 source-annotated LC4/LPLC2 bodies have a direct edge in this selection.
No intermediate is required for these observed connections. This verifies
structural access, not looming tuning, response timing or synaptic sign in the
imaged male. Soma-side connections cannot establish eye or control laterality:
[Jang et al., 2023](https://doi.org/10.1242/jeb.244790) experimentally found
bilateral visual integration in GF responses and left contralateral routes
unresolved. Direct inputs alone do not capture every visual pathway.

Relevant descending outputs exist. Source annotations identify direct targets
800146 as `TTMn_R` (`vnc_motor`, weight 70 from 10001), and 804642 as `TTMn_L`
(`vnc_motor`, weight 20 from 10010). The report retains the 20 highest-weight
targets per readout and complete totals grouped by target superclass. DNp01 R has
89 annotated `vnc_intrinsic` targets (weight 478); DNp01 L has 105 (552).
These labels support a structural connection to VNC populations, without
assigning synapse locations from soma metadata or claiming a complete motor chain.

There are 2,859 total output targets (weight 4,491) from 10001 and 2,722 (4,382)
from 10010. Respectively 2,540 (weight 3,298) and 2,368 (2,983) lack annotation
records. Unknown targets remain in totals; the annotated minority cannot represent
the whole output. Missing records and records with null superclass are distinct.

## Function, inference and engineering interpretation

| Claim and evidence class | Support | Confidence and boundary |
| --- | --- | --- |
| **Experimentally demonstrated in Drosophila:** GF activity and spike timing participate in short-mode escape takeoff selection. | [von Reyn et al., 2014, Nature Neuroscience](https://doi.org/10.1038/nn.3741), recordings and activation/silencing experiments. | Strong for studied fly behavior; not demonstrated in this MaleCNS specimen or a robot. GF is not necessary for every escape mode. |
| **Experimentally demonstrated / literature supported, not demonstrated in MaleCNS:** LC4 supplies looming angular-velocity information; LPLC2 supplies a size component to GF. | [von Reyn et al., 2017, Neuron](https://doi.org/10.1016/j.neuron.2017.05.036); [Ache et al., 2019, Current Biology](https://doi.org/10.1016/j.cub.2019.01.079), physiology, silencing and EM. | Strong within those preparations. The unresolved size input in 2017 was addressed by 2019; labels alone do not transfer quantitative tuning. |
| **Connectomic inference:** pinned DNp01 is a plausible readout downstream of LC4/LPLC2 and connects to source-labeled VNC targets. | Exact aliases, direct edges and output annotations above. | High confidence in recorded identity/edges; limited completeness and causal interpretation. No activity, latency or escape threshold was measured. |
| **Project engineering hypothesis:** combine bilateral DNp01 readout with a validated looming encoder to request safe stop in simulation. | Consistent with the frozen looming-stop interface; no fly experiment establishes this mapping. | Untested. Side combination, filters, thresholds, gains and stop transport require separate freeze/validation. No yaw, jump, backward motion or servo command follows from these IDs. |

## Decision, uncertainty and rejection scope

Accept the two exact DNp01 IDs and their GF alias as source-supported; accept
LC4/LPLC2-to-DNp01 as a structurally supported candidate, pending independent
review. This corroborates committed G1 inventory and extends it to alias fields
and a fresh whole-source incident-edge scan.

Reject selecting a nonexistent `type = GF` population, adding a second GF pool,
or importing foreign IDs. Reject equating fly urgent escape with robot stopping
or backing away, or treating every escape mode as GF-mediated. Reject a
quantitative reconstruction of the full fast motor circuit from this report:
it lacks transmitter/sign validation, electrical-coupling parameters, synapse
locations, physiological timing and completeness guarantees. The top-20 output
list cannot establish absence of unlisted partners. Left/right weight differences
are observations of this specimen, not a functional asymmetry claim. TTMn names
are source labels here; no robot muscle/actuator mapping is made.

Before implementation freeze, independent G2 review must assess this candidate
alongside P2-01 sensory validation. Data engineering must build the chosen recurrent
graph under frozen normalization/provenance rules; this audit is not a runtime
graph. Runtime/decoder and simulation tests must establish a stop response against
controls. `robotd` and the existing safety stack retain motor ownership.

## Reproducibility

See [evidence README](../evidence/p2-03/README.md) for exact source hashes,
producer identity, rebuild commands and validation. Official MaleCNS source data
are [CC-BY](https://male-cns.janelia.org/download/); this report is a derived
annotation/connectivity selection with source attribution.
