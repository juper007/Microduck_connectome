# Task Packet Template

Use this template to hand one bounded task to one primary agent skill.

```yaml
task_id: P1-03
phase: 1
title: Extract reproducible MaleCNS connectivity graph
owner_skill: connectome-data-engineer
reviewer_skill: independent-phase-reviewer

base:
  repo_commit: <sha>
  dataset: male-cns:v1.0

goal: >-
  Produce a deterministic graph artifact and API for the selected MaleCNS
  population with provenance and validation tests.

read_first:
  - docs/TASK_BREAKDOWN.md#P1-03
  - docs/preflight/DATA_AND_REPRODUCIBILITY_POLICY.md#derived-data
  - docs/preflight/NEURAL_MODEL_SPEC.md#graph-representation

do_not_preload:
  - docs/TEST_AND_EVALUATION_PLAN.md
  - docs/preflight/EXPERIMENT_PROTOCOL.md
  - unrelated robot integration files

inputs:
  - official neuPrint male-cns:v1.0
  - selected population/body IDs from the research handoff

outputs:
  - src/malecns/graph.py
  - tests/test_graph.py
  - graph/cache manifest with source version and hash

acceptance:
  - repeated extraction produces identical IDs/counts
  - every edge endpoint is valid
  - provenance and source version are embedded
  - tests pass

context_budget: "<25K input tokens target"
reasoning_effort: medium

handoff:
  include:
    - files changed
    - tests and results
    - artifact/hash
    - newly discovered dependencies
    - known limitations
```

## Rules

- Keep `goal` singular and measurable.
- `read_first` should point to exact sections whenever possible.
- Do not include a document in `read_first` merely because it may become relevant later.
- Use `do_not_preload` when agents are likely to over-read adjacent material.
- If the task needs >100K context, split it or document why it cannot be split.
- A task packet is not a substitute for acceptance criteria or Git review policy.
