# P2-03 deterministic DNp01/GF evidence

Card: [DNp01-GF-v1](../../pathways/DNp01-GF-v1.md). Task: [P2-03](../../tasks/P2-03.md).
Base: `8fb7d635e4227e88d4894505d59359ed3e037df2`.
Evidence-producing commit: `30c80fad9dcd454b78247da19abf1d9e2cf9f3ed`.
Later changes add evidence, card and regression checks; producer source is unchanged.
The report records SHA256 of its module, reused flat-file validator and lockfile;
these exact file hashes bind its code without a manually supplied commit label.

| Artifact | SHA256 |
| --- | --- |
| `dnp01-report.json` | `c42502d854a1ad9e73412ed82f5a66d4da478a0f653e84f68f10a06b260dfdc6` |
| Full annotation source, 211,577 rows | `2177e246113e4cfbf1e7772ec37c6da1955ff22e8063d0b1f833101f99a9a3b2` |
| Full weight source, 151,856,684 rows | `e35da783d1c686b2b58b3b87cd6a403ae43bfcfba8bff28e08ef752c1a56afc1` |

The [committed manifest](../../../data/manifests/pathway-source-v1.json) supplies
public URLs and project-observed hashes, not upstream signed checksums. Both
sources are checked before extraction; row counts and core column types/positive
IDs/weights are checked. No token, private cache, timestamp or random seed is
required. The JSON report is 113,945 bytes.

## Rebuild on Linux, Python 3.12

From a clean checkout of the PR or producer (producer lacks the later saved report):

```sh
uv sync --locked
for run in run1 run2; do
  uv run --locked python -m microduck_connectome.dnp01_evidence \
    --annotations data/cache/body-annotations.feather \
    --weights data/cache/connectome-weights.feather \
    --output results/dnp01-$run.json --download
done
cmp results/dnp01-run1.json results/dnp01-run2.json
cmp results/dnp01-run1.json docs/evidence/p2-03/dnp01-report.json
sha256sum results/dnp01-run1.json
uv run --locked python -m unittest discover -s tests
```

The saved-report comparison applies to the final PR checkout. Producer hashes are
byte hashes of the Linux checkout; use LF for portable artifact reproduction.
Source fields remain raw. Absent exact GF type is separate from alias matches;
selection always uses exact DNp01. Only six declared alias fields are scanned,
using the explicit token-bounded pattern in report `config`. Connectivity selects
directed body pairs without graph normalization. Output summaries include all
outgoing rows, unknown targets and null labels; only top-20 targets are individually
retained. All input records and 311 direct visual edges are retained, sorted by ID.

## Observed validation and review state

Thor, Python 3.12 locked Phase-1 environment: producer **103 tests passed**;
two separate full scans of hash-verified public files produced the same report hash,
and `cmp` succeeded. Final regression tests additionally bind the saved report/code
hashes, verify G1 ID/side/field agreement for all three populations, and recompute
input summaries. Final full-suite result is recorded in the PR.

Tests distinguish aliases from selection, reject missing sides, preserve unknown
outputs, check direction/duplicate aggregation and verify input-order invariance.
Full source runs are opt-in; unit tests do not download data. Independent
scientific/code review is pending. G2 and robot behavior gates are not certified.
