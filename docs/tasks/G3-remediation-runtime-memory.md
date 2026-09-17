# G3 Remediation Task Packet — Runtime validation and memory evidence

```yaml
task_id: G3-REMEDIATION-RUNTIME-MEMORY
phase: 3
title: Resolve G3 edge-ID validation and memory benchmark blockers
owner_skill: neural-runtime-engineer
reviewer_skill: independent-phase-reviewer

base:
  repo_commit: dbf392500336b4f725d5759209264644554cec55
  dataset: male-cns:v1.0

goal: >-
  Resolve the two G3 blocking findings without changing the frozen neural model:
  enforce exact MaleCNS body-ID types on runtime edges, add a supported Python 3.12
  memory benchmark, and bind P3-06/P3-07 workload hashes to executable definitions.

read_first:
  - docs/COMPLETION_CRITERIA.md#gate-g3--neural-runtime-stable
  - docs/preflight/NEURAL_MODEL_SPEC.md#11-numerical-safety
  - docs/preflight/NEURAL_MODEL_SPEC.md#12-performance-gates
  - microduck_connectome/sparse_runtime.py
  - microduck_connectome/performance.py
  - microduck_connectome/soak.py

do_not_preload:
  - perception implementation
  - robot integration internals
  - biological literature
  - experiment-result corpus

outputs:
  - exact edge endpoint validation + regression tests
  - executable workload identity helpers for P3-06/P3-07
  - supported-environment latency + memory benchmark evidence
  - exact-head zero/bounded soak revalidation
  - updated Phase 3 focused CI

acceptance:
  - bool/float/string/zero/negative/out-of-range/unknown edge body IDs are rejected
  - valid integer edge endpoints preserve existing float32/synchronous semantics
  - supported Python 3.12 report includes p50/p95/p99 and process RSS memory fields
  - p95 target remains <= 18 ms and is not relaxed
  - P3-06/P3-07 workload SHA256 values are computed from canonical executable definitions
  - changing a workload parameter changes its SHA256
  - committed evidence hashes match executable workload definitions
  - Phase 3 focused tests pass on supported Python 3.12
  - exact-head zero and bounded 30,000-step soaks pass
  - no neural-model, readout, stimulus, robotd, or robot-control contract changes

context_budget: "<50K input tokens target"
reasoning_effort: high
```

## Scope note

This is one bounded G3 remediation task. Memory values are environment-dependent evidence, not a new acceptance threshold. Synthetic matched-scale workloads remain explicitly non-biological and are not claims about actual full MaleCNS topology.
