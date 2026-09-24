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
  preregistered full official-Thor batch before requesting P7-02 PASS.
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
  - new preregistration, complete target/no-target Thor evidence, review record
acceptance:
  - root-cause evidence separates DN, safety, robotd applied command, and body response
  - no change to P6 yaw sign, SafetyClamp, TTL, watchdog, stop transport, or G7 thresholds
  - at least 100 valid target and 40 no-target trials meet all frozen G7 metrics
  - exact-head independent review passes before merge
context_budget: <50K input tokens per specialist task
reasoning_effort: high
```

The failed v3 batch and draft PR #49 remain immutable historical evidence.
Official policy selection or a new official policy version requires its own
hash, provenance, affected P6 recalibration, safety checks, and a full new
experiment version. Development diagnostics are never substituted for G7 trials.
