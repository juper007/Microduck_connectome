# MDN backward-locomotion pathway card — v1

Task P2-04; dataset **male-cns:v1.0**; checked 2026-09-17.
Decision: **accept the exact MDN population as a biologically supported candidate
backward-intent readout for future simulation research**. Reject a frozen reverse
controller, automatic obstacle-to-MDN encoding, and an MVP backward-walking
requirement. Independent review is pending; this card does not itself pass G2.

## Pinned identity and source sides

| Readout | Body ID | Raw somaSide | Raw instance |
| --- | ---: | --- | --- |
| MDN | 10763 | R | MDN_R |
| MDN | 11288 | L | MDN_L |
| MDN | 11332 | R | MDN_R |
| MDN | 12348 | L | MDN_L |

All four exact `type=MDN` records have `superclass=descending_neuron`,
`class=null`, and `somaNeuromere=null`. Two cells per soma side means four
readouts, not a single bilateral pair. L/R are literal soma annotations;
instances and numerical ID order do not determine side or axonal laterality.
Unknown somaNeuromere does not imply missing VNC projections.

Authority: official public minconf-0.5 flat sources pinned in
[pathway-source-v1.json](../../data/manifests/pathway-source-v1.json), whose MDN
inventory agrees exactly with the committed [G1 evidence](../evidence/g1/README.md).
Population refers to annotation rows, not a neuPrint `Neuron`-label census.
The [compact evidence](../evidence/p2-04/mdn-v1.json) retains exact raw fields,
source hashes, row counts, aliases and extraction semantics. The source is the
adult male *Drosophila melanogaster* CNS; it is anatomical data from a specimen,
not behavioral recordings from these body IDs. Identity confidence: high within
this pinned release; physiological equivalence across specimens: untested.

## Structural downstream evidence

The complete scan retains **18,796 outgoing rows**, totaling **39,119** weight.
The four readouts have the following totals:

| MDN ID (soma side) | Target bodies | All output weight | VNC-intrinsic weight |
| --- | ---: | ---: | ---: |
| 10763 (R) | 4729 | 9968 | 2318 |
| 11288 (L) | 4923 | 9920 | 2385 |
| 11332 (R) | 4751 | 10232 | 2592 |
| 12348 (L) | 4393 | 8999 | 2088 |

The exact LBL40 targets are `801214` (soma R, `LBL40_R`) and `801246`
(soma L, `LBL40_L`), both `vnc_intrinsic`, `somaNeuromere=T3`, `class=null`,
`status=Traced`, `statusLabel=Reviewed`. All four direct edges are:

| MDN body | LBL40 body | Raw weight |
| ---: | ---: | ---: |
| 10763 | 801246 | 129 |
| 11288 | 801214 | 121 |
| 11332 | 801246 | 117 |
| 12348 | 801214 | 96 |

The sum is **463**. Opposite soma labels do not establish where these synapses
lie or a contralateral motor effect. This is concrete structural support for an
adult MDN-to-LBL40 route; causal function comes from independent experiments.
**LUL130 has zero exact-type annotation matches**. The explicit token search in
`type`, `instance`, `synonyms`, `hemibrainType`, `flywireType`, and `mancType` also
finds no LUL130 or Pair1 matches. No adult LUL130/Pair1 identity or edge is accepted.

All MDNs carry `status=Traced` but `statusLabel=Prelim Roughly traced`; neither
label is upgraded to a completeness guarantee. **25,002 / 39,119** output weight
lands on bodies absent from the annotation table, limiting typed circuit coverage.
There are also 22 total weight onto source-labeled `vnc_motor` targets. These small
counts neither prove a functional direct motor command nor negate the source
observation. The compact artifact is a bounded summary, not every output edge.

All reported weights are raw directed source connection counts. They are neither
firing rates, signed efficacy, causal strengths nor independent replicates.
The extractor scans every outgoing MDN row, aggregates duplicate body pairs,
retains exact LBL40/LUL130 inventories and edges, and summarizes all output
superclasses, including null labels and unannotated targets separately. Top-ten
targets per MDN use descending weight then ascending body ID only for inspection;
this truncation does not affect full output totals or the exact-type edge tables.
Soma segment is not the ROI where a connection lies. No ROI localization,
complete downstream subgraph, path sign or motor-neuron control is inferred.

The official [MDN explorer](https://reiserlab.github.io/celltype-explorer-drosophila-male-cns/types/MDN.html)
uses the published alias DNp50. The source alias scan records matching annotation
fields but never silently substitutes an alias for exact `type=MDN`. Familiar
names across FlyWire, FANC, MANC, larval reconstructions and MaleCNS do not license
body-ID conversion. Exact-type absence means annotation non-resolution, not
biological absence. Alias matches require separate homology review before use.

## Functional evidence and preparation limits

**Experimentally demonstrated in flies; literature-supported for these MaleCNS
IDs.** [Bidaye et al., Science 2014, doi:10.1126/science.1249964](https://pubmed.ncbi.nlm.nih.gov/24700860/)
reports that MDN activation elicits backward walking and MDN activity is required
for retreat at an impassable barrier. This supports a context-specific walking
direction role, not necessity for every backward movement. The accessed abstract
and bibliographic record do not resolve sex by assay; male and female indexing
is insufficient to assert male-specific experimental validation. No quantitative
transfer from that experiment to this male specimen is claimed.

[Feng et al., Nature Communications 2020, doi:10.1038/s41467-020-19936-x](https://www.nature.com/articles/s41467-020-19936-x)
combines trans-Tango anatomy, calcium responses, activation and silencing in adult
*Drosophila*. LBL40 contributes hindleg stance power; LUL130 contributes leg lifting
at the stance-to-swing transition. The study used both sexes for Fly Bowl and
tethered activation assays, but females only for ex vivo CNS calcium imaging,
MDN-amputation and GtACR2 epistasis experiments (Methods). Those preparations
and distributed local leg effects differ from a fixed adult male connectome and
a biped robot. Trans-Tango labeling and calcium responses are not equivalent to
EM-resolved monosynaptic weight, and no direct motor-neuron labeling in that
trans-Tango experiment does not prove the absence of every EM motor connection.
This card claims neither a universal command signal nor a two-cell complete
backward-walking circuit.

**Developmental mismatch.** [Carreira-Rosario et al., eLife 2018,
doi:10.7554/eLife.38554](https://elifesciences.org/articles/38554)
links larval MDNs to backward-active A18b and to Pair1-mediated suppression of
forward circuitry. Its larval EM and optogenetic/calcium evidence must not be
recast as an adult MaleCNS A18b/Pair1 pathway. Larval sex is not resolved here.
Developmental persistence of a named neuron does not preserve every partner,
locomotor mechanism or body ID. No larval premotor ID is selected for this card.

A newer primary [Current Biology study (2026), doi:10.1016/j.cub.2026.06.045](https://www.sciencedirect.com/science/article/pii/S0960982226007918)
reports bilateral antennal input and flight-dependent suppression of walking
pathways. The accessible publisher summary supports behavioral-state dependence;
full figure/method review was not available here, so it supplies no quantitative
mapping, sex-specific conclusion or selected sensory population in this card.

Confidence: high for experimentally supported adult fly backward-locomotion
involvement; moderate for linking named experimental target types to this
anatomical specimen; low for any quantitative robot interpretation.

## Engineering interpretation and acceptance boundaries

No sensory input population is selected. MDN is the proposed readout population;
LBL40/LUL130 are literature-linked downstream candidates, not robot actuators.
A future experiment could compare pooled activity across all four MDNs with a
baseline to propose an abstract backward intent. Pooling, filters, gains,
thresholds, persistence and behavioral arbitration are engineering hypotheses.
There is no justified left-minus-right turning law for these four cells and no
justified mapping from a synapse count to robot speed.

Accept the population only while all four pinned IDs, explicit two-L/two-R
metadata, exact type and source hashes agree. Reject missing or ambiguous sides,
a forced one-pair simplification, unreviewed alias substitution, and causal claims
based solely on directed connectivity. Any source change requires revalidation
and a new card version. Unresolved LUL130 identity cannot be filled using another
dataset's ID. The card supports pathway cataloging without selecting a runtime
graph, physiology model, sensory encoder or controller parameters.

Backward walking remains outside MVP acceptance (`preflight/MVP_SCOPE.md`).
Simulation validation must precede any hardware consideration. Neural output may
supply behavior intent only; robotd and the existing motion/safety stack retain
motor ownership. No servo, gait or safety contract changes are authorized here.

## Reproduce and review

Producer commit: `92eda9921f60f2539990ca5c3518fe1ad7921507`. Subsequent card,
evidence and test commits retain the producer executable unchanged. Thor's
locked Python 3.12 environment passed **108 tests at the producer** and two full
raw-source scans produced identical bytes. Evidence SHA256:
`df95b7d6cc8348e04c6c0cdb6ea747ceb89e738155d6047f32f5778e362dda36`.

Annotation SHA256: `2177e246113e4cfbf1e7772ec37c6da1955ff22e8063d0b1f833101f99a9a3b2`
(211,577 rows); weights SHA256:
`e35da783d1c686b2b58b3b87cd6a403ae43bfcfba8bff28e08ef752c1a56afc1`
(151,856,684 rows). Full report hashes bind source manifest, producer files and
lockfile. Code-file hashes refer to checkout bytes on the Linux producer; retain
LF line endings for byte-identical cross-platform reproduction.

From the repository root in Python 3.12 with `uv sync --locked`:

```sh
for run in run1 run2; do
  uv run --locked python -m microduck_connectome.mdn_evidence \
    --annotations data/cache/body-annotations.feather \
    --weights data/cache/connectome-weights.feather \
    --output results/$run/mdn-v1.json --download
done
cmp results/run1/mdn-v1.json results/run2/mdn-v1.json
cmp results/run1/mdn-v1.json docs/evidence/p2-04/mdn-v1.json
sha256sum results/run1/mdn-v1.json
python -m unittest discover -s tests -p test_mdn_evidence.py
python -m unittest discover -s tests
```

The focused tests need only Python and committed evidence; the complete source
rebuild uses locked dependencies and the two public Feather files. Existing
hash-matching caches may be reused. No hidden credentials or private input is
needed. Windows locked dependency installation failed with TLS HandshakeFailure;
focused local tests ran on Python 3.12.13, while full validation ran on Thor.

The script is bounded research evidence support built on the G1 source adapter;
it is not a general ETL or runtime interface. Official download URLs remain in
the report. Project-observed checksums are not upstream signed attestations.
Source hashes/counts, explicit identity, positive edge values and provenance are
validated before publication. Tests reject invalid sides/IDs/classes, alias
substitution, bad edges, duplicate annotations and output/source collisions;
they also verify deterministic aggregation and preserved unknown annotations.
Literature and prose require independent human scientific review.
