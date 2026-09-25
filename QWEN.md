# Qwen Code Instructions — MicroDuck Connectome

Read `AGENTS.md` before project work. It is the authoritative repository-wide contract for architecture, safety, Git workflow, review, handoffs, and token/context efficiency.

## Qwen compatibility layer
- Project skills live under `.qwen/skills/` and delegate to the canonical repo skills under `.agents/skills/`.
- Use the narrowest matching skill. Do not preload all skills.
- Use subagents in `.qwen/agents/` when planning, implementation, safety review, or independent review benefits from isolated context.
- A subagent does not override `AGENTS.md` or the canonical selected `.agents/skills/<name>/SKILL.md`.

## Non-negotiable invariants
- MaleCNS/connectome output selects bounded high-level behavior intent; it never owns servos or the motor bus.
- MicroDuck motor ownership remains with `robotd` and the supported motion/safety stack.
- SO-101 action delivery remains behind its supported adapter and LeRobot `Robot` interface.
- Simulation precedes physical robot testing.
- Biological claims require traceable evidence; engineering mappings must be labeled as engineering choices.
- Do not declare a task/phase complete without evidence matching its acceptance criteria.
- Phase gates require an independent final-head review.

## Work discipline
Start with this file, `AGENTS.md`, the selected Qwen skill adapter, its canonical skill, and the task packet/acceptance criteria. Expand context only as needed. Follow `docs/TOKEN_EFFICIENCY_POLICY.md`, `docs/AGENT_CONTEXT_MAP.md`, and `docs/AGENT_GIT_WORKFLOW.md`.
