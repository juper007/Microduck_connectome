# DOCS-QWEN-THOR-LOCAL-V1 — Thor-local Qwen execution mode

```yaml
task_id: DOCS-QWEN-THOR-LOCAL-V1
phase: project-infrastructure
title: Define local Qwen Code execution on Jetson Thor
owner_skill: reproducibility-devops-engineer
reviewer_skill: independent-phase-reviewer
base:
  origin_main: e74e69228b83900bf7c5ced086e6774847381c7e
goal: >-
  Make Qwen Code execute repository editing, tests, MicroDuck simulation,
  robotd, and evidence collection directly on the current Thor host while
  preserving clean-worktree, exact-head review, safety, and experiment rules.
outputs:
  - QWEN.md Thor-local execution contract
  - docs/MICRODUCK_TASK_DSL.md v1.1 host/isolation directives
  - docs/dsl/profiles/P8FINAL.yaml Thor-local defaults
  - .qwen/agents/implementation.md local-execution guidance
acceptance:
  - host=thor-local explicitly forbids ordinary SSH/SCP/remote orchestration
  - isolation=worktree preserves fresh origin/main task isolation
  - final/scored evidence runs from exact independently reviewed head
  - frozen task/protocol paths and scientific/safety criteria are not silently changed
  - independent review remains separate on the same physical host
  - P8FINAL profile selects Thor-local worktree execution
context_budget: "<10K input tokens"
reasoning_effort: low
```
