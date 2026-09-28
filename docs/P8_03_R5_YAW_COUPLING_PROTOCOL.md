# P8-03-R5 yaw and translation coupling diagnostic v1

Status: development-only preregistration. Base: freshly fetched
`origin/main` at `57161251c63be912a002d236d18e7c13cd48b1cc`.
Branch: `codex/p8-03-r5-yaw-coupling`. PRs #80–#83 remain open terminal
FAIL evidence. The published R1, R3, and R4 evidence Releases are unchanged.
R5 does not modify the final P8 reset tolerance (0.08 rad), R2 guard
(0.06 rad), false-positive thresholds, graph-v2, DNp01 threshold,
controller, decoder, SafetyClamp, Watchdog, robotd ownership, final seed
matrices, final geometry, or the 0.01 m diagnostic planar bound.

## Durable R4 observations and question

The published R4 archive `p8-03-r4-actuator-pose-evidence-v1.tar.gz` records
five attempted resets and a FAIL gate. Its first sham settled response was
0.0003987954 rad. Low positive yielded +0.003170025 rad and peak planar
0.003184977 m; low negative yielded +0.002564911 rad and 0.003136756 m.
Both were below the 0.005 rad floor. High positive yielded +0.052802559 rad
and 0.007372144 m in one reset. High negative crossed the 0.01 m bound:
retained trigger 0.011485978245908253 m. These observations establish
neither a global sign mapping nor a dose response. R5 asks how heading and
planar translation vary with sign, dose, policy state, and phase through the
frozen high-level `robot.move` / `robot.stop` path.

## Frozen development matrix

`config/p8_03_r5_yaw_coupling_v1.json` is the executable specification.
Six five-reset blocks contain one sham and one of each ±low and ±medium
condition. Even blocks use sham, +low, −low, +medium, −medium; odd blocks
reverse each sign pair. IDs C00–C29 use seeds 888200–888229 exactly once,
with no replacement or retry. Historical repo refs, final matrices, and
freshly downloaded R1/R3/R4 evidence archives were searched for this range;
no collision was found. Sham alternates 3/5 zero-yaw ticks. Low is 3 and
medium is 5 ticks at 20 ms/tick and |vyaw|=0.2 rad/s. Both are below R4's
unsafe 8-tick high exposure; 5 ticks was R4's low condition, not proven safe.
`vx=vy=0`, TTL=0.10 s, and bounded through-stop duration ≤0.30 s. The
0.08 rad command-integral cap remains. No feedback, second pulse, sign
reversal, dynamic tuning, or response-driven retry is allowed.

Stop the entire matrix after the first safety, timing, storage, stale-state,
ACK, cleanup, or raw-integrity failure. Later IDs remain PENDING. A complete
weak or wrong-sign response does not stop the matrix. No early PASS is
possible. No final static/receding seed or 60-reset qualification is run.

## Capture and safety

Use the pinned upstream MicroDuck and microduck_rl commits, model-1250 walk
policy, graph hash, Python 3.12, SIT reset, and clean reviewed source at
exact head. The runner checks idle state/socket/port and unused output root.
Every reset uses official down/up, policy load and readback, initial stop,
healthy robotd, and a stopped pre-command pose plateau. It samples pose and
state at 20 ms during command and for 1 s after stop ACK, with a separate
STOP_ACK pose, and uses the existing 50 ms plateau checks. Host request and
response timestamps, robotd clock, simulator time, full body packet,
quaternion, roll/pitch, requested/applied motion, limiter, policy, safety,
health, and phase are retained. The full robotd state retains any observable
gait or contact data. A state/pose join older than 100 ms is rejected.

For every read, append and fsync the raw pose/state row first; only then
compute and fsync derived displacement/heading; only then evaluate bounds.
The 0.01 m bound applies at **≥0.01 m** from either reset-start or
command-start origin. The exact trigger sample remains in raw. On violation,
issue authentic `robot.stop` immediately, preserve its ACK, send no further
move, complete official down and socket/port probe, and classify
SAFETY_ABORT. Missing/torn raw or failed cleanup cannot become VALID.

## Offline analysis and gate

`scripts/p8_03_r5_score.py` verifies the frozen matrix, journal sequence,
raw/derived order, stop and cleanup events, manifest inventory/hash/bytes,
and per-reset lifecycle. It independently reconstructs the threshold
crossing. It computes net x/y and heading changes for PRE_COMMAND,
DURING_COMMAND, COMMAND_TO_STOP_ACK, POST_STOP_0_250MS,
POST_STOP_250_500MS, and FINAL_SETTLE, plus peak command-start excursion,
additional post-stop excursion, and heading rebound. Segment net distances
are not added as path length. The final sham floor requires six valid shams:
`max(0.005 rad, max(abs(sham settled response)) + 0.002 rad)`. Active responses
are VALID above the signed floor, WRONG_SIGN below its negative, and
INCONCLUSIVE otherwise. An unsafe reset is SAFETY_ABORT; corrupt raw is
DATA_INTEGRITY_FAIL; launch/transport problems are INFRA_FAIL.

R5 PASS requires all 30 resets and interpretable verified raw from every
cell, including all six shams. It says only that the coupling is characterized
well enough to evaluate correction. Correction strategy eligibility is a
separate conservative screen: one common low or medium dose must show all
six responses above the signed floor in each direction and every such reset
must peak at ≤0.008 m from command start. Any incomplete matrix, hazard, or
unexplained asymmetry leaves eligibility NO. No correction is implemented
here, regardless of outcome.

## Execution and evidence handoff

An independent reviewer must PASS the exact final head before Thor execution.
Use a fresh isolated clean checkout at that head and verify pinned material,
socket/port, configuration hashes, and source cleanliness. The sole matrix
command is `python3.12 -m scripts.p8_03_r5_yaw_coupling --output
/home/juper007/projects/microduck-connectome-thor/evidence/p8-v2-final/p8-03-r5-yaw-coupling-v1
--reviewed-head <exact-sha>`. Retain every attempted raw journal, trace,
preflight, logs, manifest, gate, and PENDING IDs. Publish one new versioned
GitHub Release even on FAIL, preserving historical releases. Fresh-download
the archive, compare bytes and SHA256, test archive integrity and manifest
coverage, rerun the offline scorer, and reconstruct any trigger before final
independent evidence review. R5 does not authorize P8-03 final execution,
P8-04, or a correction implementation. A passing, eligible R5 stops and
routes any correction to a separately reviewed P8-03-R6 task.
