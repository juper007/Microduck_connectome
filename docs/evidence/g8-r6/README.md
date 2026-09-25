# G8-R6 graph-v2 closed-loop steering recertification

**Task result: PASS, pending independent exact-head review.** This result
recertifies steering for canonical graph v2 on official Thor `duck-sim` / robotd /
MuJoCo. It does not turn historical graph-v1 G7 evidence into graph-v2 evidence,
complete Phase 8, or establish biological/topology superiority.

## Handoff and frozen identity

| Field | Value |
| --- | --- |
| Task / owner skill | G8-R6 / `$microduck-integration-engineer` |
| Supporting skill | `$behavior-control-engineer` read-only failure/decoder analysis; PM coordination |
| Fetched `origin/main` base | `9b9a147ac143db50d21ee04b361b9fb852402122` |
| Branch / isolated local worktree | `test/g8-r6-graph-v2-steering-regression` / `C:\projects\Microduck_connectome\.worktrees\g8-r6-graph-v2-steering` |
| Isolated Thor checkout | `/home/juper007/projects/microduck-connectome-thor/g8-r6-graph-v2-steering` |
| Frozen final source head | `8e44fa387feab711c79cebfc2e9a276ed314cc76` |
| Protocol | [`config/g8_r6_steering_v1.json`](../../../config/g8_r6_steering_v1.json), SHA256 `4a5c11546984dd949d2c96a23c6c39c6c0d5b75214448f2de7306c0ef69bcc7e` |
| Dataset / graph | `male-cns:v1.0` / graph SHA256 `c4160c42941163079b6b569d117bf67afcf8b45eaa128c444f7c96c2567593cc` |
| Pinned upstream | MicroDuck `344925c9f8fa031f85428a305b1e8ec2eaae29c1`; `microduck_rl` `cb70b792312d559a4da09064d92009079671815f` |
| Walking policy | SHA256 `98c3ea73fa6bb196bcf16586cf38b9fffb782787447d638fa1c1028df9082c1a` |
| Reviewer / reviewed head / PR / merge | Pending independent review, PR, fresh-main check, and merge |

The [preregistration](../../tasks/G8-R6-PROTOCOL.md) and source were frozen
before scored trials. The graph and population IDs, neural weights, decoder,
safety limits, and motion adapter were unchanged. Each final trial used a fresh
official simulator down/up reset and the hash-verified walk policy. The
controller received RGB target features, not evaluator target bearing.
The target/no-target batch summaries retain the reused P7-v4 harness schema
labels; their source head, G8-R6 experiment SHA, graph identity in every
trial, and new prospective seed matrix identify these as graph-v2 runs.

## Quantitative result

| Frozen metric | Result | Criterion |
| --- | ---: | ---: |
| Target planned / attempted / started / valid | 120 / 120 / 120 / 120 | ≥100 valid; all planned accounted |
| Correct / incorrect / no-response | 108 / 11 / 1 | Correct direction ≥90% |
| Correct-direction rate | **108/120 = 0.9000** | ≥0.9000 |
| Response latency median / p95 | 0.7672 / 0.8268 s | Recorded |
| No-target planned / attempted / started / valid | 40 / 40 / 40 / 40 | All planned accounted |
| No-target false turns | **0/40 = 0.0000** | ≤0.0500 |
| Safety-limit violations / scheduler exceptions / watchdog deadline misses | **0 / 0 / 0** | 0 |
| Unhealthy robotd before/after / started-trial harness failures | **0 / 0** | 0 |
| Final official simulator down exit | **0** in both batches | 0 |

The raw [target summary](target-summary-v1.json), [no-target summary](no-target-summary-v1.json),
[160-trial journals](target-results-v1.jsonl), and [machine-readable aggregate](steering-summary-v1.json)
retain all outcomes. The no-target journal is [separate](no-target-results-v1.jsonl).
Target batch summary SHA256 is `025932029db2db8371e0dfd5752814d68996c202efc9fa8a426e7b0a0bb24bb7`;
no-target summary is `4b5e76a573be3801953b7c602ee700620736ac68577b3987a08bc7b02e50df1f`.
The corresponding journal hashes are `6c4ceb620e6c0717e6525fd615113ea0520e94261fa60e3f36ca2ea8afdc890d`
and `4cf9203900ae7dda3868841ab21a40907835d83ab7bc713a8719c12c49635f6a`.

## Neural-to-body lineage

Three fresh-reset left trials (`002`, `003`, `004`) and three right trials
(`001`, `007`, `009`) were inspected directly from raw traces. In each,
the visually lateralized target produced same-side LC10a stimulus `1.0`,
graph-v2 DNa02 steering readout `0.2`, and bounded decoder/safety/healthy
watchdog yaw of `+0.5` rad/s for left or `−0.5` rad/s for right. The command
passed through `RobotMotionAdapter` as official `robotd` move transport; the
MuJoCo body heading changed `+0.0443`, `+0.0445`, `+0.0455` rad for the left
examples and `−0.0206`, `−0.0249`, `−0.0235` rad for right. The complete
time-aligned perception, stimulus, DNa, pre/post safety, watchdog, robotd,
applied state, and pose records remain in each `trace.jsonl`. This supports a
graph-v2 action-selection path and high-level motor interface; it does not
identify a unique biological causal mechanism.

## Preserved failures and limits

All 12 valid target failures remain in the journal and raw traces. Ten
`incorrect` left/slow-crossing/near-center trials had a left turn but target
bearing at response onset within the frozen `0.05` rad center tolerance.
`g8-r6-target-072` turned left after a crossing target lay to its right at
response onset. `g8-r6-target-060` is a no-response under the frozen sustained
heading rule. None were deleted, relabeled, or replaced. Correct-direction
performance is exactly at the 90% threshold, with a Wilson 95% interval
`[0.8333, 0.9419]`; the left and near-center strata score 80% and 75%.
No-target observed 0/40 satisfies the preregistered observed-rate threshold,
but its Wilson 95% upper bound is 0.0876, so this batch alone does not
establish a population false-turn rate below 5% at 95% confidence.

Before any scored trial, a Thor Python 3.12 test exposed a Windows CRLF hash
difference, fixed in the frozen source. A later pretrial acquisition under
the superseded commit `1488ca3` was stopped to put the existing 100-valid
minimum explicitly into the manifest. Its journal has **zero records**, and
no trial started. Both launch/pretrial logs and all 12 files are retained at
`/home/juper007/projects/microduck-connectome-thor/evidence/g8-r6/final-1488ca3-20260925-1/`;
the [preflight manifest](preflight-manifest-v1.json) SHA256 is
`e1e9e1ca87c7e02df2dd5d24f71f23cb136c199812eb3ffe246c4b8bf7e07477`.

## Raw artifact integrity and reproduction

Final raw root:
`/home/juper007/projects/microduck-connectome-thor/evidence/g8-r6/final-8e44fa3-20260925-1/`.
The [artifact manifest](artifact-manifest-v1.json) lists all **1,868** files,
each path, byte count, applicable line/record count, and SHA256. Manifest
SHA256 is `835e2fcaca62e5536165615e7f0738b4e2acd4a26e6af7eaf11af64958ba06cf`.
An independent pass matched every one of 160 per-trial trace and summary hashes
to its journal, matched each trace record count to the trial summary, matched
both journal hashes to their batch summaries, and confirmed all 160 trials
started, were valid, and had zero safety violations.

On the frozen Thor checkout, focused regression command:

```sh
python3.12 -m unittest tests.test_g8_r6_protocol tests.test_p7_target_batch_v4 tests.test_p7_no_target_batch_v4 tests.test_p7_steering_trial -q
```

Result: **20 passed**. With `B=/home/juper007/projects/microduck-connectome-thor`
and `R=$B/g8-r6-graph-v2-steering`, the official final batch commands were:

```sh
PYTHONPATH="$R" python3.12 -m scripts.p7_target_batch_v4 \
  --root "$R" --experiment "$R/config/g8_r6_steering_v1.json" \
  --output "$B/evidence/g8-r6/final-8e44fa3-20260925-1/target" \
  --graph-cache "$B/evidence/g8-r1/graph-v2" \
  --sim-script "$B/microduck/scripts/duck-sim" \
  --state-dir /tmp/g8-r6-state --microduck "$B/microduck" \
  --microduck-rl "$B/microduck_rl" --body-port 7896

PYTHONPATH="$R" python3.12 -m scripts.p7_no_target_batch_v4 \
  --root "$R" --experiment "$R/config/g8_r6_steering_v1.json" \
  --output "$B/evidence/g8-r6/final-8e44fa3-20260925-1/no-target" \
  --graph-cache "$B/evidence/g8-r1/graph-v2" \
  --sim-script "$B/microduck/scripts/duck-sim" \
  --state-dir /tmp/g8-r6-state --microduck "$B/microduck" \
  --microduck-rl "$B/microduck_rl" --body-port 7896
```

The evidence-only commit after the frozen run does not change the controller,
graph, manifest, or scoring code. Independent review must bind its decision
to that final exact head. A fresh-main check and PR merge remain pending.
