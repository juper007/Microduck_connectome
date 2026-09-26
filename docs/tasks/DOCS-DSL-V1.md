# DOCS-DSL-V1 — Compact Task DSL

```yaml
task_id: DOCS-DSL-V1
phase: project-infrastructure
title: Add compact task invocation DSL
owner_skill: microduck-pm-architect
reviewer_skill: independent-phase-reviewer
base:
  origin_main: 0652b114a477ea0ff1e20cd90d13691ae2d87693
goal: >-
  Add a versioned compact invocation layer that references existing AGENTS.md,
  SKILL.md, task-packet, Git, review, safety, and reproducibility contracts
  without duplicating them in each prompt.
read_first:
  - AGENTS.md
  - docs/TASK_PACKET_TEMPLATE.md
  - docs/TOKEN_EFFICIENCY_POLICY.md
outputs:
  - docs/MICRODUCK_TASK_DSL.md
  - docs/dsl/profiles/P8R3.yaml
  - docs/dsl/profiles/P8FINAL.yaml
  - AGENTS.md compact DSL section
acceptance:
  - DSL cannot weaken normative repository contracts
  - unknown syntax is rejected rather than guessed
  - skill aliases require actual repo-scoped skill execution
  - base=latest requires fresh origin/main
  - wf=std resolves to the complete mandatory Git/review workflow
  - exact-head independent review remains mandatory where required
  - compact examples can invoke a task without restating stable policy
context_budget: "<10K input tokens"
reasoning_effort: low
```
