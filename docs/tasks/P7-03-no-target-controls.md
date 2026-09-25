# P7-03 no-target control task packet

```yaml
task_id: P7-03
phase: 7
title: Run independent no-target and visual-noise controls
owner_skill: microduck-integration-engineer
reviewer_skill: independent-phase-reviewer
base:
  repo_commit: 41a9849325e2a52714ecd23fd75c2a394c28c658
  branch: experiment/p7-03-no-target-controls
  worktree: /home/juper007/projects/microduck-connectome-thor/p703-no-target-controls-41a9849
  parent_target_manifest_sha256: f24170521f049cec6a65a88285925343316f84ce9bdaf59a1a668257db5460cd
goal: >-
  Preregister and, only after independent prelaunch review, run 40 new
  official-Thor no-target controls to measure sustained false steering
  under the unchanged P7 controller, model1250 policy, and safety limits.
read_first:
  - docs/TASK_BREAKDOWN.md#P7-03
  - docs/preflight/EXPERIMENT_PROTOCOL.md#Behavior-A
  - docs/COMPLETION_CRITERIA.md#G7
  - docs/tasks/P7-02-remediation.md#V4-execution-boundary
  - docs/evidence/p7-02/v4-final-handoff.md#Early-no-target-control-run
  - scripts/p7_no_target_batch_v4.py
do_not_preload:
  - Phase 8 or hardware documents
  - all P7-02 development traces
  - unrelated connectome biology
inputs:
  - merged P7-02 target branch on origin/main
  - P7-02 final target summary 120 valid and 108 correct, SHA256 8f2e7d797b1bf01a4249f9cad9e17ca8c57e4574750e653d7d56a438347192ca
  - P7-02 target journal SHA256 f9379d4911cc2075d28e09f579c583dca87403dd1617e0bde487adf79f54225b
  - exact model1250 ONNX SHA256 98c3ea73fa6bb196bcf16586cf38b9fffb782787447d638fa1c1028df9082c1a
  - early 40/0 control run, diagnostic only; its seeds and trial IDs are excluded
outputs:
  - config/steering_no_target_p7_03_v1.json
  - scripts/p7_03_preregister.py
  - scripts/p7_03_no_target_batch.py
  - tests/test_p7_03_no_target_batch.py
  - after separate prelaunch GO, complete official Thor raw traces, journal, summary, and review
acceptance:
  - new preregistered set has 40 unique seeds and IDs disjoint from all 160 P7-02 v4 seeds and IDs
  - 20 clean and 20 moderate-noise control trials in frozen shuffled order
  - unchanged controller/config hashes, policy, yaw sign, stop, TTL, validity, safety, and false-turn rule
  - official run has 40 valid no-target trials with no replacement of a started trial
  - false-turn rate <= 0.05 and safety-limit violations == 0
  - every scored trace is bound to trial summary SHA and record count, manifest-derived spec, policy, and journal hashes
  - full raw evidence and uncertainty are retained; independent exact-head review passes before P7-03 completion
context_budget: "<30K input tokens target"
reasoning_effort: medium
handoff:
  include:
    - fetched origin/main base and task branch SHA
    - manifest, controller, policy, and evidence hashes
    - all changed files and focused test outcomes
    - independent review state and known limitations
```

The merged P7-02 target batch is reused as **P7-02 evidence**, without
rerunning or rescoring its 120 target seeds. It used the same controller
configuration and exact model1250 ONNX as this task. Its 108/120 result
already satisfies the target component of the frozen steering criterion;
P7-03 measures the separate no-target false-steer component on **new**
independent seeds. The P7-02 early 40/0 no-target run happened before the
required P7-03 sequence and remains a diagnostic record only. It cannot be
substituted for this task's formal control run.

The new manifest uses the existing `steering-experiment-v4` runtime schema
for compatibility with the unchanged trial runner. Its distinct
`experiment_version` and `p7_03` block identify the P7-03 protocol.
The only changed trial inputs are the 40 no-target seeds, IDs, and shuffled
clean/moderate-noise order. The P7-02 120 target specifications remain
byte-equivalent in the new manifest as historical reference, not a request
to execute them. The visual-noise conditions are no-target controls; the
current scenario does not add a separate rendered decoy object. Any new
decoy geometry would require its own preregistration before evidence runs.

Before any official 40-trial run, independent review must approve the exact
committed manifest and harness head. This preparation task stops at commit
and source-only tests. No physical hardware, Phase 8, PR push, or merge is
authorized here.
