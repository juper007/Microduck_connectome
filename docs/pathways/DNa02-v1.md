# DNa02 steering pathway card — v1

Task: P2-02. Dataset: **male-cns:v1.0**. Evidence checked: 2026-09-17.
Decision: **accept the source-resolved bilateral DNa02 pair as a candidate steering
readout for simulation; functional transfer and the tracking input remain hypotheses**.
Independent review is pending; this card alone does not pass G2.

## Identity and source laterality

| Readout | Body ID | Raw `somaSide` | Raw `instance` | Raw `superclass` |
| --- | ---: | --- | --- | --- |
| Left DNa02 | 523769 | L | DNa02_L | descending_neuron |
| Right DNa02 | 10360 | R | DNa02_R | descending_neuron |

Both records have exact `type=DNa02`, `class=null`, `somaNeuromere=null`.
Laterality is the explicit **soma** annotation, converted only by L -> left,
R -> right. Neither numerical ID order, query order, instance suffix nor a
projection crossing determines side. Unknown somaNeuromere does not establish
soma location or absence of a VNC projection.

Authority: the hash-verified official flat annotation source retained by
[G1](../evidence/g1/README.md), not a fresh inference from the name or explorer
thumbnail. The complete exact-type inventory has two bodies. The compact
[machine evidence](../evidence/p2-02/dna02-v1.json) preserves both raw rows,
source URLs/checksums, producer commit and graph identity; its validator checks
all three pinned G1 report hashes before deriving this slice. Population means
all flat-file annotation rows, not a neuPrint `Neuron` label query.

Confidence: high for identity within this pinned release. No FANC, FlyWire,
hemibrain or MANC body ID is substituted for either MaleCNS ID. Literature
homology at the named cell-type level does not prove identical connectivity,
physiology or individual anatomy across specimens. DNa01, DNa03, DNg02 and DNg13
are different types, not aliases for DNa02.

## Input and intermediate evidence: structural, not causal

The reviewed G1 selection is LC10a -> annotated intermediate -> DNa02. In its
570-node induced graph, at minimum raw edge weight 1 and at most two directed
hops, the source reports give:

| DNa02 side | Reachable LC10a bodies | Simple two-edge paths |
| --- | ---: | ---: |
| Left | 275 | 3361 |
| Right | 272 | 3210 |

These are counts, not efficacy, probabilities or independent experimental
replicates. The deterministic evidence retains one lexicographic example per
side solely to make a route inspectable; it is not a strongest-path choice.
The source records of every example body are included. Two-hop enumeration
may include a seed/readout as the intermediate, as specified by the G1 API.
No new extraction, weight normalization or neurotransmitter sign assignment is
performed here. Paths to both sides cannot establish a target-bearing decoder.
P2-05 must compare tracking inputs and their lateralized evidence separately.

## Downstream anatomy: official source observation

The official [DNa02 explorer](https://reiserlab.github.io/celltype-explorer-drosophila-male-cns/types/DNa02.html)
lists these leading output partner types (combined L/R page, checked 2026-09-17):

| Partner type | Displayed `conns DNa02` | Displayed output fraction |
| --- | ---: | ---: |
| IN08A006 | 449.5 | 6.2% |
| Sternal anterior rotator MN | 388 | 5.4% |
| IN19A003 | 314.5 | 4.4% |
| IN13B001 | 241.5 | 3.4% |

Its ROI output totals include LegNp(T1): 1588, LegNp(T2): 998 and LegNp(T3):
1095. These support descending access to leg circuitry; they do not identify
which robot action a synapse should cause. The page predicts ACh, with 94.6%
confidence; that is a prediction, not measured signed synaptic efficacy.

The [official help](https://reiserlab.github.io/celltype-explorer-drosophila-male-cns/help.html)
identifies `male-cns:v1.0`; connection-table values are per-neuron aggregates,
not per-body edge weights or presynaptic T-bar counts. The partner `#` column is
type population size, not number actually connected. It is deliberately omitted
above. Page generation is 2026-09-09, neuView v2.7.34. These cited web observations
are not byte-pinned by the offline G1 validator and must be rechecked if reused
quantitatively. No downstream partner body IDs or complete output census are
claimed. A future downstream simulation needs a data-engineer extraction from
the pinned full-source weights and exact partner annotations, with source hash
checks and explicit side fields.

The G1 selected graph has no source-labeled `vnc_intrinsic` population. Its empty
brain/VNC query therefore cannot contradict these full-CNS outputs or mean that
DNa02 lacks VNC connectivity.

## Experimental facts and limits

**Experimentally demonstrated in living flies, literature-supported rather than
measured in the MaleCNS specimen.** [Rayshubskiy et al., eLife 2025,
10.7554/eLife.102230](https://elifesciences.org/articles/102230), Figures 2, 3 and
8: paired electrophysiology relates the right-minus-left firing difference to
turning velocity; DNa02 predicts relatively rapid, transient steering.
Unilateral activation biases turning toward the stimulated soma side. Bilateral
inhibition in freely walking flies did not significantly change rotational
speed. The authors report weak effects, driver off-target cells and differences
between treadmill and freely walking conditions. Thus correlation and activation
support a steering contribution, but do not demonstrate unique necessity or a
universal linear controller. Their FAFB/hemibrain input analysis is cross-dataset
connectomic evidence, not an independently validated MaleCNS path.

**Experimentally demonstrated limb effect.** [Yang et al., Cell 2024,
10.1016/j.cell.2024.08.033](https://www.sciencedirect.com/science/article/pii/S0092867424009620)
shows that DNa02 activation shortens strides on the inside of a turn, whereas
DNg13 lengthens outside strides. Their phase-dependent circuit account combines
physiology with anatomical interpretation. This supports specific leg modulation,
not a context-free angular-velocity output. These results are compatible with
multiple steering DNs and do not erase the inhibition null result above.

Confidence: moderate-to-high for a fly steering contribution; low for transferring
the firing-to-turning relationship quantitatively to a biped robot. Neither
paper demonstrates the complete project LC10a -> DNa02 -> robot chain.

## Project engineering hypothesis and decision boundary

Proposed readout: compare filtered activity of left `523769` and right `10360`.
For an explicitly *left-positive abstract intent*, `activity_left - activity_right`
is a candidate steering signal: larger left activity suggests a leftward bias.
This sign convention is an engineering definition, not a sign copied from a
paper's plot. The mapping from that intent to simulator `vyaw` must use the
required official-simulator calibration fixture. Gains, filtering, thresholds,
baseline subtraction and neural activity units require subsequent validation;
none are established by synapse count. Symmetric activity does not prove “no
behavior,” because bilateral manipulations can have locomotor effects.

This card authorizes no servo command or motor-neuron emulation. MaleCNS supplies
behavior intent; robotd and the existing motion/safety stack retain motor ownership.
Simulation precedes hardware. It does not select forward velocity or a stop rule.

Accept identity only while both pinned raw records agree and exactly one explicit
L and one explicit R are present. Reject a laterality claim if a side is missing,
ambiguous, duplicated, inferred from IDs or replaced with another dataset's ID.
Reject “sole steering command,” “necessary for all turns,” and “connectivity proves
causality.” Reject a frozen tracking controller until P2-05 evidence, runtime
readout tests and calibrated left/right simulator behavior are reviewed. Source
version/hash changes require a new card version and revalidation.

## Reproduction and review

Run from a clean checkout in the Python 3.12 locked project environment:

```sh
python -m microduck_connectome.dna02_evidence --check docs/evidence/p2-02/dna02-v1.json
python -m unittest discover -s tests -p test_dna02_evidence.py
python -m unittest discover -s tests
```

To regenerate explicitly (no network or hidden cache):

```python
from pathlib import Path
from microduck_connectome.dna02_evidence import build_evidence, canonical
Path("docs/evidence/p2-02/dna02-v1.json").write_bytes(
    canonical(build_evidence("docs/evidence/g1")))
```

The module is a research-evidence adapter, not a runtime configuration interface.
Changes to prose/literature need human review; the byte check validates the compact
G1-derived artifact only. Tests cover ID/side pins, order independence, no fallback
from instance/ID, ambiguous/missing/duplicate metadata, and each source digest.
Full raw-source G1 regeneration remains the documented G1 procedure, not repeated
by this task. Final PR records validation/head and pending independent review.
