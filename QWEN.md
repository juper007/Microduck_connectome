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


## Thor-local execution mode

When a task specifies `host=thor-local`, Qwen Code is running **on the Jetson Thor that owns the simulator/runtime environment**.

Rules:

- Do not use SSH, SCP, rsync, remote shells, or a second controller host for normal task execution.
- Resolve the current repository with `git rev-parse --show-toplevel`; edit, test, run the simulator, run `robotd`, execute evidence scripts, and hash artifacts directly on this host.
- Keep the mandatory Git isolation model. `thor-local` does **not** mean modifying a dirty `main` checkout. Prefer a task-specific local `git worktree` based on freshly fetched `origin/main`.
- Scored/final experiment execution must use a clean worktree at the exact independently reviewed execution head required by the task protocol.
- Existing frozen task/protocol absolute paths remain authoritative unless a separately versioned protocol explicitly changes them. A path under `/home/juper007/projects/microduck-connectome-thor/` is a **local Thor path**, not evidence of remote orchestration.
- Large raw runtime artifacts may remain on Thor at the protocol-defined evidence path. Commit summaries, manifests, hashes, metrics, and other repository-required evidence; do not copy large raw logs into Git unless the task contract requires it.
- Before authoritative simulator evidence, verify the task-required host/runtime identity (for current P8 work: Thor and Python 3.12), exact source head, upstream pins, config/artifact hashes, ports/state, and clean worktree.
- Independent review remains isolated from implementation even though both run on the same physical Thor. Use the Qwen independent-review subagent/session and exact final-head rules from `AGENTS.md`.

Compact invocation:

```text
@run <TASK> host=thor-local isolation=worktree
```
