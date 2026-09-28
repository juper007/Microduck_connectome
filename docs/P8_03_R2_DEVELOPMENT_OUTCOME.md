# P8-03-R2 development outcome and Thor handoff

**Status: FAIL / BLOCKED.** This record closes `p8-03-r2-protocol-v1` as a
development failure. No R2 held-out reset seed or final static/receding seed
was used. No R2 trial armed. PR #80 and Release `p8-03-r1-evidence-v1` remain
terminal R1 FAIL and were not modified. Draft PR #81 contains this R2 work;
it is not a merge candidate while the gate is blocked.

## Root-cause finding

R1 RS04's second pose differed by 0.098492625 rad from the R1 first-reset
reference, above the unchanged 0.08 rad limit. Its two reads were stable over
100 ms, policy readback matched earlier R1 runs, and robotd health was normal.
R1 did not retain `sim_time` for RS04, so that exact event cannot be assigned
to a specific startup tick. Across 64 later fresh exploratory resets, official
simulator time advanced and a deferred-policy SIT outlier appeared **before**
explicit policy load and remained stable afterward. HOME/STAND keyframes had
larger spreads. The best-supported cause is variable pose by the end of
`duck-sim up` / robotd stand-up. The precise physics, policy startup, or
contact mechanism remains unresolved. Explicit policy-load settling, a stale
body packet, and late post-load pose timing are inadequate as sole explanations
for the reproduced variation. The R1 first-seed reference semantics made that
variation a terminal pre-arm failure; R2 froze the R1 reference prospectively
instead of letting a final seed define it.

## Development evidence and decisions

All roots below are on Thor under
`/home/juper007/projects/microduck-connectome-thor/evidence/p8-v2-final/`.
The listed hashes are SHA256 of each root's `manifest.json` or
`diagnosis-manifest.json`. Independent review verified exact inventories,
hashes, cleanup, and causal limits.

| Root suffix | Executed source HEAD | Result | Manifest SHA256 |
| --- | --- | --- | --- |
| diagnosis-r1cadence-v1 | `9deefac82b65da12c1f3d093af24ca985ff975e3` | 12/12 observed | `3188ad67cabf91d6abcdea3b4539b0f357bcc99597448b573588998d348abced` |
| diagnosis-deferred-policy-v1 | `9deefac82b65da12c1f3d093af24ca985ff975e3` | 12/12 observed | `47a9173d70e74f587404ed5f006128f38624fb0d3b0f160777551a9d27ac8738` |
| diagnosis-home-v1 | `bed2b2bd3b0cd454b59b79884deb2e8e3dfa8fc1` | 20/20 observed | `f44b068778f7779905a46e0beb07749d9ecc85076443fe0b108f45e14bf642a0` |
| diagnosis-stand-v1 | `c05fb3afe08a65dfb3553f5b3a05423665013172` | 20/20 observed | `88bacd161c570b4e09592ba3bac0a5021baa4ba686a99d3dd5a14a817b260fe7` |
| reset-pilot-v1 | `f9851a5ba57887d438c653dcfb9f48b8707c96af` | 3/3 PASS, no alignment | `70ef20950d2b8837e9200cba334b10a300e36b75a47f5df71d78fdf9068bec6b` |
| alignment-perturbation-v1 | `f84ba316aed08e0b7c0e4916db35f30030c2da56` | FAIL 1/2; immediate pose precheck | `6c3955fceae227c77f7251f1f6aec5ddb7c02bf3f96f39e2ef822017beaca7eb` |
| alignment-perturbation-v2 | `4e01f6b9286f01eef53b53412265e97fb1bc070a` | FAIL 1/2; corrective divergence | `e1c42ea6b79566673c9efe0bf188c5d8c478f4ef48cc2fbe61f9686700437873` |
| alignment-perturbation-v3 | `ac030a3e4f80577be82c23351004c28bdc2946e0` | FAIL 1/2; perturbation deadline | `a17295eb68d33d81460c09e47c0c324d9ab8050bd46a0dd4709d779bb98e4475` |
| alignment-perturbation-v4 | `59f7c82732c46f2283e82e255067f90136669961` | FAIL 1/2; negative-side correction | `4d266ce471bafaafd2b888bf57ec9b24b006389cebfbfd6e4422ac0cd0a83c4c` |

In v4 D00, positive perturbation and negative correction succeeded, followed
by a 21-sample qualified dwell. In D01, negative perturbation succeeded and
stabilized. Seven positive corrective commands increased reference heading
error from 0.120655 to 0.155390 rad and triggered the frozen divergence
abort. That response does **not** identify whether actuator sign, robotd
application, body contact dynamics, or walking policy caused the divergence.
All v1–v4 stop ACKs, simulator downs, final probes, and port/socket checks
passed. Each failed root remains immutable; none may be retried or counted
as a qualification reset.

## Gate

- R2 protocol: `config/p8_03_r2_protocol_v1.json`, terminal development FAIL.
- Frozen tolerance: x/y 0.03 m, z 0.025 m, heading 0.08 rad. No limit widened.
- Stronger guard: heading 0.06 rad after one-second settle and 21 fresh 50 ms
  samples; 100 ms body-read age and 30–75 ms response intervals.
- Pilot: PASS 3/3, no yaw command path exercised.
- Polarity intervention: FAIL v4 1/2; positive correction from a negative
  heading offset was not reliable.
- Held-out development qualification: **NOT RUN**. Planned v1 seeds
  887400–887459 remain unused but are ineligible under failed protocol v1.
- Static final: **NOT RUN**. Planned v1 R2S00–19 seeds 887500–887519 unused.
- Receding final: **NOT RUN**. Planned v1 R2R00–19 seeds 887600–887619 unused.
- P8-03 gate: FAIL/BLOCKED; P8-04, final regression, and G8 NOT RUN.

## Exact Thor state and next handoff

Task packet P8-03-R2; input base `57161251c63be912a002d236d18e7c13cd48b1cc`
from freshly fetched `origin/main`; branch `codex/p8-03-r2-reset`.
Local managed worktree:
`C:\Users\juper\.codex\worktrees\p8-03-r2-reset\Microduck_connectome`.
Isolated Thor checkout:
`/home/juper007/projects/microduck-connectome-thor/p8-03-r2-source`.
Last executed R2 source is `59f7c82732c46f2283e82e255067f90136669961`;
subsequent documentation commits require their own final review before any
integration. Thor pins MicroDuck
`344925c9f8fa031f85428a305b1e8ec2eaae29c1`, microduck_rl
`cb70b792312d559a4da09064d92009079671815f`, graph SHA256
`c4160c42941163079b6b569d117bf67afcf8b45eaa128c444f7c96c2567593cc`,
and policy SHA256
`98c3ea73fa6bb196bcf16586cf38b9fffb782787447d638fa1c1028df9082c1a`.
Python 3.12, state `/tmp/p8-03-r2-reset-development-state`, body port 7898.
Latest independent review is a v4 development execution/evidence review at
that exact executed SHA; **no held-out or phase review PASS exists**.
Context scope was the R1 PR/Release, task packet, selected integration,
evaluation, reproducibility, and safety contracts, R1 reset harness, pinned
upstream simulator entry points, and these small Thor traces. No raw dataset
or unrelated docs tree was preloaded. No random seed was consumed by the
diagnosis, pilot, or polarity perturbations; trial seeds listed above remain
untouched. Used normal reasoning effort.

The next implementation must start on a **new task-specific branch from newly
fetched `origin/main`** and preserve this failed v1 protocol/PR/evidence.
First run a separately versioned **development-only sign and actuator
diagnostic**: bounded high-level robotd yaw probes in both directions, each
at most 0.2 rad/s for 0.20 s with 50 Hz refresh and 100 ms TTL; at most two
probes per direction and 0.08 rad total commanded yaw per fresh reset.
Require health and fresh advancing simulator pose throughout, acknowledged
stop, at least 0.5 s fixed settling, and a measured low angular-rate plateau
before interpreting sign. Abort on stale pose, stop failure, bounds breach,
or a preregistered wrong-sign increase. Retain command/ACK, applied
robot.state, full pose/time trace, stop latency, down, and final probe.
This diagnosis is not a corrective controller and uses no held-out seed.

If the diagnostic supports a correction strategy, freeze a **new versioned
controller and protocol** with a fixed reference, both-polarity response
criteria, maximum bursts/time, stop/settle gate, and untouched pose
tolerances. Obtain independent exact-head review, then use a new disjoint
development seed matrix for 60 consecutive fresh resets (all must PASS)
before selecting any new 20+20 final seeds. Review that development evidence
independently. Only a PASS unlocks final execution, immutable Release
publication, remote download/hash verification, independent raw re-score,
current-head review, and possible merge. Preserve all v1 negative roots.

Before any Thor command, inspect the process identity in the output run
marker, check `git status --porcelain` and exact source HEAD in the R2
checkout, verify the pinned material hashes, verify the isolated state
directory/socket/port are idle, and choose an unused versioned output root.
Never relaunch into v1–v4 roots. Do not execute
`--kind qualification` or any R2 final seed under the failed v1 protocol.
P8-04, final regression, and G8 remain blocked; Phase 9 must not start.

Known limitations: RS04 lacks simulator-time trace; exploratory first samples
occur after simulator up, so the exact startup onset remains unseen. The v4
negative-side response is a real failure of the current preparation strategy
but does not establish a single actuator or policy defect. No final efficacy
claim is available. Pre-merge freshness/sync and reviewed final-head status
are **not applicable** while PR #81 remains draft and unmerged.
