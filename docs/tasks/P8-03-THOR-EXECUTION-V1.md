# P8-03 official static and receding control handoff v1

Status: **REMOTE PREPARATION; NO P8-03 FINAL SEED RUN**. P8-02-R1 is the merged
prerequisite at PR #78, with published Release `p8-02-r1-evidence-v1` and
independent exact-head PASS at `eb51807c8f3904dcb4f8e0a3197e33e2be0bfef7`.
This handoff is valid only after independent review of the P8-03 execution
source, tests, and preflight. The reviewed PR head, not a locally guessed SHA,
is `P8_HEAD` below. Record that 40-character SHA and PR URL in the Thor run
record before any S00 output or assignment. The input base is
`57161251c63be912a002d236d18e7c13cd48b1cc`.

## Frozen contract

Use [P8-V2 final protocol](P8-V2-FINAL-PROTOCOL.md) and
`config/p8_v2_final_protocol_v1.json` as the normative matrix. This task adds
`config/p8_03_execution_v1.json`; it does not alter the selected V2.4
renderer, estimator, graph, DNp01 threshold, decoder, safety, Watchdog,
scheduler, motor boundary, seeds, or acceptance limits. The controller sees
only fractional 8×8 RGB and frozen ToF. The pose-derived synthetic center and
0.85 m / increasing-range truth are evaluator inputs, never neural inputs.

S00–S19 use 881000–881019; R00–R19 use 882000–882019, each in its own official
duck-sim reset. Each has the protocol's 2.0/2.6/3.0 s arm-cycle metadata and a
1,000 ms scored window. A healthy neural stop at any time in that window is a
false positive. Fault, deadman, stale input, fixture geometry, scheduler, or
unresolved acquisition failure blocks PASS. The fixed gate is S ≤1/20, R
≤1/20, pooled ≤2/40, all 40 accounted, and zero safety-limit violations.

## Thor setup and preflight

Run on `jetsonthor` with Python 3.12, authenticated `gh`, the pinned official
MicroDuck and microduck_rl checkouts, graph-v2 JSON and ONNX policy. The
following are shell commands; replace **only** `P8_HEAD` with the reviewed
exact PR head and `P8_PR` with its URL, then retain the literal command log.
The execution config freezes every other source, upstream, output, state,
port, and audit path. Any path/hash/head mismatch aborts before output or ID
assignment. Do not edit the frozen config to match an operator path.

```bash
set -euo pipefail
P8_HEAD='<exact independently reviewed P8-03 PR head SHA>'
P8_PR='<P8-03 PR URL>'
THOR_ROOT=/home/juper007/projects/microduck-connectome-thor
SOURCE="$THOR_ROOT/p8-03-source"
EVIDENCE="$THOR_ROOT/evidence/p8-v2-final"
MICRODUCK="$THOR_ROOT/microduck"
RL="$THOR_ROOT/microduck_rl"
GRAPH="$THOR_ROOT/evidence/g8-r1/graph-v2/c4160c42941163079b6b569d117bf67afcf8b45eaa128c444f7c96c2567593cc.json"
POLICY="$THOR_ROOT/evidence/p7-02/policy-development-6012390-20260924/checkpoint1250-diagnostic/model1250.onnx"
SIM="$MICRODUCK/scripts/duck-sim"
STATE=/tmp/p8-03-state
AUDIT="$EVIDENCE/p8-03-preflight-audit.jsonl"
SROOT="$EVIDENCE/p8-03-static-v1"
RROOT="$EVIDENCE/p8-03-receding-v1"
test ! -e "$SOURCE"
test ! -e "$SROOT"
test ! -e "$RROOT"
git clone https://github.com/juper007/Microduck_connectome.git "$SOURCE"
git -C "$SOURCE" fetch --prune origin
git -C "$SOURCE" checkout --detach "$P8_HEAD"
test "$(git -C "$SOURCE" rev-parse HEAD)" = "$P8_HEAD"
test -z "$(git -C "$SOURCE" status --porcelain)"
test "$(git -C "$MICRODUCK" rev-parse HEAD)" = 344925c9f8fa031f85428a305b1e8ec2eaae29c1
test "$(git -C "$RL" rev-parse HEAD)" = cb70b792312d559a4da09064d92009079671815f
test "$(sha256sum "$GRAPH" | cut -d' ' -f1)" = c4160c42941163079b6b569d117bf67afcf8b45eaa128c444f7c96c2567593cc
test "$(sha256sum "$POLICY" | cut -d' ' -f1)" = 98c3ea73fa6bb196bcf16586cf38b9fffb782787447d638fa1c1028df9082c1a
python3.12 --version
cd "$SOURCE"
PYTHONPATH=. python3.12 -B -m unittest tests.test_p8_03_controls -q
```

Before S00, obtain an independent implementation review PASS of `P8_HEAD` and
retain the review URL/verdict. The batch's preflight checks clean reviewed
HEAD, committed bytes, frozen path and hash identities, available isolated
port/state, and unused output root. The S batch must PASS before R starts.
After each down/up and policy readback, the batch records two official MuJoCo
trunk poses before motion. S00's first fresh reset fixes the run's pose
reference before neural arm; both S and R compare every subsequent reset to
that reference using the scenario's frozen x/y/heading/z tolerances. A failed
reset tolerance aborts before arm and blocks the batch. The reference and each
`pose-reset.json` are retained in the journal and raw manifest.

## Official S then R execution

```bash
PYTHONPATH=. python3.12 -B scripts/p8_03_batch.py \
  --stage S --root "$SOURCE" --reviewed-head "$P8_HEAD" \
  --microduck "$MICRODUCK" --microduck-rl "$RL" --graph "$GRAPH" \
  --policy "$POLICY" --sim-executable "$SIM" --output "$SROOT" \
  --audit "$AUDIT" --sim-state "$STATE" --body-port 7894
PYTHONPATH=. python3.12 -B scripts/p8_03_batch.py \
  --stage R --root "$SOURCE" --reviewed-head "$P8_HEAD" \
  --microduck "$MICRODUCK" --microduck-rl "$RL" --graph "$GRAPH" \
  --policy "$POLICY" --sim-executable "$SIM" --output "$RROOT" \
  --audit "$AUDIT" --sim-state "$STATE" --body-port 7894
PYTHONPATH=. python3.12 -B scripts/p8_03_finalize.py \
  --static-root "$SROOT" --receding-root "$RROOT" \
  --master config/p8_v2_final_protocol_v1.json \
  --output "$EVIDENCE/p8-03-final-score-v1.json"
```

Do not rerun an armed trial or replace its seed. Only an exogenous simulator
`up` failure can consume the next of at most three logged same-seed pre-arm
attempts. Operator/config/policy errors abort. On SIGINT the supervisor sends
an authentic stop, checkpoints, runs final down/port probe, and exits FAIL.
After SIGKILL/power loss, run the same batch command with `--recover-only`;
it inventories untouched bytes and marks in-flight IDs unknown-arm for audit.
It never resumes an unknown armed ID. Preserve all failed raw data and use a
separately versioned remediation if the gate fails.

Each batch retains per-attempt simulator/policy/trial logs, `armed.json`, raw
events, neural and visual ledgers, summary, journal, SHA256/byte/line manifest,
raw score, final down log, and final port/socket probe. The standalone audit
log is outside the batch roots so preflight failures assign zero IDs.

## Durable evidence publication and independent verification

Only after the pooled final score and both manifests PASS, package the exact
bytes. Keep the archive immutable and publish it as a GitHub Release asset.
Use the measured byte count and SHA256 in the Release notes and versioned
evidence document. A reviewer downloads a fresh copy, verifies those bytes,
extracts it, checks every manifest entry, and reruns the pooled scorer. The
Release asset, not this handoff, is the authoritative official trial evidence.

```bash
tar -C "$EVIDENCE" -czf /tmp/p8-03-evidence-v1.tar.gz \
  p8-03-preflight-audit.jsonl p8-03-static-v1 p8-03-receding-v1 \
  p8-03-final-score-v1.json
sha256sum /tmp/p8-03-evidence-v1.tar.gz
stat -c%s /tmp/p8-03-evidence-v1.tar.gz
gh release create p8-03-evidence-v1 /tmp/p8-03-evidence-v1.tar.gz \
  --repo juper007/Microduck_connectome \
  --title 'P8-03 official static and receding evidence v1' \
  --notes "P8-03 official Thor evidence; source $P8_HEAD; PR $P8_PR; record archive SHA256 and bytes in versioned evidence document."
```

If any stage FAILS, retain and publish its negative evidence with a failure
label instead of the PASS Release name. P8-04 remains blocked. After a PASS
Release, remote review must verify published archive identity, complete raw
manifests, 40 IDs/journal attempts, raw per-ID classifications, S/R/pooled
Wilson 95% intervals, zero safety violations, final shutdown, current-main
freshness, and independent exact-head review before merging P8-03.
