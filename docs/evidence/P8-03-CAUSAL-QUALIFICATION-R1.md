# P8-03 causal qualification R1: development probe evidence

Task: `P8-03-CAUSAL-PRECONDITION-R1-QUALIFICATION-SEMANTICS`.
Status: **PASS for the causal precondition probe only**. The separately
reviewed 50 Hz timing probe is next. No behavioral ARM, scored timing
interval, second behavioral development gate, final P8 IDs, or P8-04 work ran.

## Identity and decision

| Field | Result |
| --- | --- |
| Fetched `origin/main` base | `57161251c63be912a002d236d18e7c13cd48b1cc` |
| Input causal probe source | `fbe77021c982318c6bc2d26fc795043f384b5146` |
| Reviewed exact probe head | `7d89438731e5eb2c81e2163e33babbe69e1f7a08` |
| PR #94 / #95 heads | `66754b489f526a2f3f62eef50c3c3c7f4884a395` / `8683a8d3dc28c5f7e2a273c27aa2deeac94e4e90` |
| Upstream pinned / candidate | `344925c9f8fa031f85428a305b1e8ec2eaae29c1` / `c47085a57770c52ed4cd00d5960b17598df2d7af` |
| Upstream candidate patch SHA-256 | `828ff2619ee378d4fe49fe358944dcc9b5aa9b6583e7aef1afe43a353411655a` |
| First causal low-vx cause | robotd per-tick EMA at alpha 0.2: 0.07 requested → 0.014 applied |
| Original applied-vx meaning | fresh endpoint at least 0.04 immediately before ARM |
| Causal monitoring window | PASS; first consumed positive generation through eligibility, all ticks safety monitored |
| Qualifying moving window | PASS; begins after applied ≥0.04, walk policy, and fresh pose speed ≥0.015 |
| Duration start | FIRST_CAUSAL_TICK; frozen 1.5 s of 20 ms commands |
| Applied vx threshold | 0.04 m/s, unchanged |
| No-deadman rule | unchanged |
| `limited_by` schema | omitted or `[]` means empty; `null`, malformed, or nonempty limiter fails |
| Limited-by evaluator fix | YES, prospective v2 only |
| Behavioral acceptance change | NO |

The [R1 decision](../decisions/P8-03-CAUSAL-QUALIFICATION-SEMANTICS-R1.md)
contains the first 15 CPDEV-001 causal tick ledger and exact source
attribution. `CPDEV-001` remains immutable FAIL; its archive SHA-256 remains
`161f8fdb3427fabfb1b7c468199d9b38298d2d7e1e1d9d0e0f501c8ebe97f0a6`.
No historical evaluator result or raw state was changed.

## Fresh development-only labels

Every label used the same reviewed head, official simulator, frozen
`config/p8_03_timing_probe_v2.json` moving gate, pinned walking policy,
robotd candidate metadata, and unmodified high-level 0.07 m/s move request.
The simulator was down between labels. No random seed is applicable; the
official simulator reset and per-reset local-reference capture were used.

| Label | First causal tick / gen | First qualifying tick / gen | Ramp ms | Causal s | Qualifying s | Postqualifying displacement m | Result |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| `CPDEV-002` | 396 / 1 | 407 / 12 | 220.154 | 1.800630 | 1.580477 | 0.051541 | PASS |
| `CPDEV-003` | 394 / 1 | 404 / 11 | 200.223 | 1.799493 | 1.599270 | 0.050167 | PASS |
| `CPDEV-004` | 394 / 1 | 405 / 12 | 220.235 | 1.800790 | 1.580555 | 0.049859 | PASS |

| Label | First causal applied vx | First qualifying applied vx | Causal min / median / max applied vx (m/s) |
| --- | ---: | ---: | --- |
| `CPDEV-002` | 0.014000 | 0.065190 | 0.014000 / 0.069998 / 0.070000 |
| `CPDEV-003` | 0.014000 | 0.063987 | 0.014000 / 0.069998 / 0.070000 |
| `CPDEV-004` | 0.014000 | 0.065190 | 0.014000 / 0.069998 / 0.070000 |

Each label recorded 91 request/ACK pairs, 94 contiguous state frames, 90
commands counted after first causal consumption, 0 causal deadman states, 0
fault/safety states, and 0 tick gaps. The evaluator checked 0.04 applied vx,
walk policy, fresh state/pose, at least 0.015 m/s pose speed for 200 ms,
0.01 m postqualification displacement, full 1.5 s causal command duration
and cadence, generation lineage, and clean stop transition. Each final
`duck-sim down` exited zero with socket absent and body port free.

Pose-speed minima after qualification were 0.025783, 0.019212, and
0.019203 m/s for `CPDEV-002`, `003`, and `004`; medians were
0.106846, 0.099702, and 0.098996 m/s. The source records preserve every
causal ramp tick, generation, command request/ACK, robotd state, and
independent body pose packet. The full local-reference result and policy
readback are included for each label.

## Archive and validation

Thor evidence root:
`/home/juper007/projects/microduck-connectome-thor/evidence/p8-03-causal-qualification-r1`.
Packaged archive:
`p8-03-causal-qualification-r1.tar.gz`, SHA-256
`0a9eb48785d0d0395addd94016e03e4609ec807826ac894e1c74d43ea1c044da`.
The embedded `manifest.json` SHA-256 is
`6d64ff57591167c8acb40e1df8f3c9ea1949dbb12f6ab31d7088bc5467dea1e1`.
It lists SHA-256 and byte counts for all 24 probe files. The archive was
downloaded and every embedded file was rehashed successfully.

Pre-execution independent reviewer: `$independent-phase-reviewer`, PASS on
exact probe head `7d89438731e5eb2c81e2163e33babbe69e1f7a08`. The
reviewer found and required a fix for prequalification body movement being
counted toward the gate; the final reviewed head recomputes displacement
and sustained speed only from pose samples after qualification. Targeted
Thor tests: 50 passed (`test_p8_03_causal_precondition_v1.py` and
`test_p8_03_causal_precondition_v2.py`). Source syntax and `git diff
--check` passed.

No timing probe, behavioral development run, final P8 ID, or P8-04 task
was started. Next: create a separately reviewed 50 Hz timing probe using
the proven causal/qualifying precondition.
