---
task_id: P8-V2-EARLY-TRIGGER-PROBE
owner_skill: microduck-integration-engineer
support_skills: [perception-sensory-encoder, neural-runtime-engineer, behavior-control-engineer, robot-safety-engineer, experiment-evaluation-scientist, reproducibility-devops-engineer]
base_origin_main: 34b48af891c508f83bf50eb9f8accd1f0a57bd22
branch: experiment/p8-v2-early-trigger-probe
worktree: C:\projects\Microduck_connectome\.worktrees\p8-v2-early-trigger-probe
phase: Phase 8 development probe before P8-v2 preregistration
---

# P8-v2 early-boundary development probe

G8-R5d established moving-body causal neural stop transport, but its three
frozen healthy neural triggers occurred at evaluator center distances
0.19837, 0.22041, and 0.20137 m, below P8-01's frozen 0.25 m boundary.
This task finds a safe, reproducible observation window for P8-02 **before**
freezing final P8-v2 seeds or running a final trial. It is development evidence,
not a P8-02 numerator or G8 PASS claim.

## Inputs and invariants

- Fresh base above; graph v2 SHA256
  `c4160c42941163079b6b569d117bf67afcf8b45eaa128c444f7c96c2567593cc`,
  dataset `male-cns:v1.0`, MicroDuck `344925c9f8fa031f85428a305b1e8ec2eaae29c1`,
  microduck_rl `cb70b792312d559a4da09064d92009079671815f`.
- Official Thor duck-sim, robotd, MuJoCo, robot.stop motor transport, current
  50 Hz watchdog/control and 500 ms robotd deadman. Do not alter graph topology,
  LPLC2/DNp01 IDs, weights, decoder threshold, SafetyClamp limits, or 0.25 m
  evaluator-only boundary.
- Read only targeted G8-R5d trial/config/evidence and P8-01 scenario code;
  preserve the separate P8-v2 protocol draft as DRAFT.

## Probe work

1. Use development-only seeds outside planned P8-v2 final ranges. Record **all**
   attempts, failures, code/config revisions, and raw logs. No development
   attempt becomes a final benchmark trial.
2. Implement/measure official moving-body precondition plus acknowledged
   positive-motion refresh while waiting for the first healthy neural stop.
   Stop positive moves atomically on first stop or fault; no preemptive zero
   twist, scripted stop, deadman stop, or post-stop robot.move may be credited.
3. Probe earlier visual arm times on the continuous P8-01 world-anchored RGB
   approach. Log official pose, evaluator-only center distance and margin at
   every sampled event; raw pixel area, frame IDs/source timestamps/gaps,
   looming, LPLC2, runtime step, DNp01, pre/post SafetyClamp, Watchdog,
   robot.stop request/ACK, applied velocity, pose stop, and stop refresh.
4. Verify that the first healthy neural stop occurs while actual pose motion
   and applied vx are present and strictly before the frozen 0.25 m boundary;
   record ACK/cessation margins separately. Post-trigger virtual crossing is
   reported, not relabeled as a safety violation.
5. If feasible, recommend exact arm/cadence/trial-duration and post-ACK visual
   policy values to the P8-v2 scientist **before protocol freeze**, including
   observed distributions and failure modes. If infeasible, retain raw failure
   and report a versioned remediation need; do not weaken thresholds.

## Evidence and handoff

Versioned code/config and a Thor raw hash manifest are required for any PR.
Report base/branch/frozen source, raw paths/hash/record counts, tests, simulator
cleanup, every development run and result, current-main freshness, known
limitations, reviewer/exact-head status, and whether the probe is fit to guide
P8-v2 preregistration. An independent reviewer must examine the exact final
head before a PASS probe PR is merged. The final P8-v2 protocol must be
reviewed and merged before any P8-02 final trial.
