# G8-R6 v1 preregistration — graph-v2 steering

This protocol is frozen by the first committed version of
`config/g8_r6_steering_v1.json` and the clean source commit used for the final
batch. Any post-result controller, scoring, threshold, seed, or graph change
requires a separately versioned remediation and a complete new final batch.

## Identity and architecture

- Base `origin/main`: `9b9a147ac143db50d21ee04b361b9fb852402122`.
- Dataset: `male-cns:v1.0`; canonical graph-v2 SHA256 and cache key:
  `c4160c42941163079b6b569d117bf67afcf8b45eaa128c444f7c96c2567593cc`.
- Official MicroDuck: `344925c9f8fa031f85428a305b1e8ec2eaae29c1`;
  `microduck_rl`: `cb70b792312d559a4da09064d92009079671815f`.
- All config and walking-policy hashes are in the JSON manifest. The trial
  process verifies each before motion. The graph is loaded by the frozen key.
- Camera rendering uses only scenario geometry and read-only body heading;
  evaluator target-bearing truth is used only by the scorer. The full chain is
  RGB → target detection → LC10a stimulation → graph-v2 runtime → DNa02
  readout → P7 steering decoder → SafetyClamp → Watchdog → RobotMotionAdapter
  → official robotd move API → MuJoCo heading. `robotd` owns actuation.

## Final matrix and decision rules

The committed manifest fixes 120 target and 40 no-target fresh-reset trials.
The target trials preserve the P7-v4 geometry, side, motion, and visual-noise
strata but use 160 distinct prospectively generated seeds. Historical G7
outcomes are not G8-R6 results. Each trial gets a fresh official `duck-sim`
down/up reset, policy load, one-second settle, and pose-tolerance check. At
most three fully recorded pretrial acquisition attempts are permitted; there
are no replacements after trial start. All attempted and started trials remain
in the raw journal, including failures.

Target scoring uses the first sustained 0.2-second pose-heading response with
absolute change at least 0.02 rad and at least 80% same-sign increments. The
heading direction must match evaluator-only target bearing at response onset
with target visible and outside the 0.05-rad center tolerance. Wrong turns and
no responses are evaluated failures. At least 100 valid target trials and
correct-direction rate ≥0.90 are required. No-target false turn is official
robot-facing absolute yaw ≥0.10 rad/s sustained for ≥0.2 s after the first
0.6 s warmup. All 40 no-target trials must be valid; rate ≤0.05. Both batches
require zero safety-limit violations, no started-trial harness failure, and
successful simulator cleanup.

Invalidity is limited to the manifest's simulator, pretrial pose, fixture,
post-command state/heading, control deadline, and scheduler health rules.
Fault stops and invalid trials cannot be counted as clean true negatives.
Graph-v2 left and right target causal traces must each show LC10a input,
DNa02 activity, decoder yaw, safety/watchdog output, applied robotd yaw, and
signed MuJoCo heading change; at least three independent fresh resets per
side will be inspected. Quantitative PASS alone does not replace this lineage
check. No graph, neural, population, decoder, safety, or motion thresholds are
changed in this task.

## Artifact discipline

Final Thor output goes under
`/home/juper007/projects/microduck-connectome-thor/evidence/g8-r6/` with
separate target and no-target directories. Each trial retains its spec,
pretrial acquisition log, `trace.jsonl`, summary, and command/log files.
Batch journals and summaries include source head and hashes; final evidence
lists path, byte size, record count, SHA256, and reproduction commands.
Started failures remain in place. A batch failure is reported as FAIL and
cannot be repaired by replacing seeds or rescoring under this protocol.
