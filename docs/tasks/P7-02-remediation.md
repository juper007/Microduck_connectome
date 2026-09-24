# P7-02 remediation task packet

```yaml
task_id: P7-02-R1
phase: 7
title: Diagnose and remediate the failed Thor steering chain
owner_skills: [microduck-integration-engineer, behavior-control-engineer]
reviewer_skill: independent-phase-reviewer
base:
  repo_commit: 34c8857251e14f83a9dff9697f947599781ff01e
  failed_branch_head: 369fd00402dc228f37d99c4dd4fd3429398e8cd1
  failed_experiment: p7-steering-v3
goal: >-
  Identify each measured loss of sustained, target-directed body rotation,
  repair it without changing P6 safety or P7 success criteria, and run a newly
  preregistered full official-Thor target batch before requesting P7-02 PASS.
read_first:
  - docs/evidence/p7-02/README.md#Result
  - docs/evidence/p6-03/README.md#bounded-motion-calibration-evidence
  - docs/COMPLETION_CRITERIA.md#G7
  - docs/preflight/EXPERIMENT_PROTOCOL.md#Behavior-A
  - microduck_connectome/steering_decoder.py
  - microduck_connectome/safety_clamp.py
do_not_preload: [Phase 8+, Phase 9 baselines, unrelated neuroscience]
inputs:
  - Thor frozen v3 raw traces and exact source/config hashes
  - pinned official robotd and MuJoCo diagnostic response traces
outputs:
  - versioned P7 temporal DN decoder and focused tests
  - traceable official locomotion-policy remedy if a safe one is demonstrated
  - new preregistration with target and future no-target seeds
  - complete target Thor evidence and exact-head review record
acceptance:
  - root-cause evidence separates DN, safety, robotd applied command, and body response
  - no change to P6 yaw sign, SafetyClamp, TTL, watchdog, stop transport, or G7 thresholds
  - at least 100 valid target trials meet the frozen steering and safety metrics
  - no-target final trials remain P7-03 scope after P7-02 PASS and merge
  - exact-head independent review passes before merge
context_budget: <50K input tokens per specialist task
reasoning_effort: high
```

The failed v3 batch and draft PR #49 remain immutable historical evidence.
Official policy selection or a new official policy version requires its own
hash, provenance, affected P6 recalibration, safety checks, and a full new
experiment version. Development diagnostics are never substituted for G7 trials.

## V4 execution boundary

The candidate policy must first pass repeated matched ±0.5 rad/s official
robotd/MuJoCo body-response diagnostics at the unchanged 0.02 rad per 200 ms
criterion. A selected ONNX artifact, training checkpoint, recipe, seed, source
commit, and exporter are then pinned by SHA256 in the v4 manifest. Until that
evidence exists, the v4 manifest is not generated and no final batch starts.

The v4 manifest reserves 120 independently seeded target trials (five for each
side × eccentricity × motion × noise combination) to preserve the ≥100 valid
target floor after occasional pretrial reset failures. The 40 reserved no-target
trials remain P7-03 work. The frozen v3 response rule, 0.90 target rate, zero
safety violations, and initial-pose tolerances are copied exactly.

Before each target trial, the official simulator is restarted, the candidate
walk policy is loaded and read back through `robot.policies`, and the actual
loaded file's SHA256 is checked. After a fixed one-second settle, initial pose
is numerically checked. At most three fully logged official restart attempts
are allowed **before** a trial starts; no started trial is replaced. If all
attempts fail, that trial is invalid and remains in the journal. The trial
script checks the pose again before sending any controller command.

Promotion from the policy diagnostic to the P7 target batch requires fresh
affected P6 evidence on that exact ONNX hash: paired signed-yaw calibration,
bounded vx/yaw and slew, acknowledged stop and stale-command behavior,
controller reconnect/robotd restart safe-stop boundary, and the autonomous
10-minute official-simulator soak with complete telemetry. Any failed item
blocks the batch. This revalidation does not edit P6's external controller
limits or reinterpret the previous G6 decision.
