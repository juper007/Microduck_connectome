# Codex Agent Routing for MicroDuck Connectome

This repository uses repo-scoped Codex skills under `.agents/skills/`.

## Role routing

Use the narrowest matching skill for the work:

- `$microduck-pm-architect` — roadmap, architecture, task decomposition, phase gates, cross-role coordination.
- `$connectome-researcher` — MaleCNS cell types, body IDs, pathway evidence, literature, biological provenance.
- `$connectome-data-engineer` — neuPrint ingestion, schemas, caches, graph extraction, reproducible datasets.
- `$neural-runtime-engineer` — connectome dynamics, LIF/leaky runtime, sparse execution, CPU/GPU performance.
- `$perception-sensory-encoder` — camera/ToF features, target/looming detection, feature-to-neural stimulation mapping.
- `$behavior-control-engineer` — descending-neuron readout, filtering, high-level motion intents, decoder behavior.
- `$microduck-integration-engineer` — official MicroDuck runtime, robotd IPC, MuJoCo, 50 Hz loop integration.
- `$robot-safety-engineer` — watchdogs, stale-command handling, limits, fault injection, hardware promotion safety.
- `$experiment-evaluation-scientist` — hypotheses, baselines, ablations, metrics, statistics, scientific conclusions.
- `$reproducibility-devops-engineer` — environment pinning, CI, manifests, seeds, config hashes, artifact/log discipline.
- `$independent-phase-reviewer` — defect-first independent review and phase-gate verification.

## Mandatory Git workflow for every agent

These rules apply to every agent, every task, including documentation-only changes.

### Checkout / start-of-work rules

1. Never begin implementation directly on `main`.
2. Before changing files, start from the latest `main` and create a **new task-specific branch**.
3. Do not reuse an old branch for an unrelated task.
4. Use descriptive branch names such as:
   - `feature/<task-id>-<short-name>`
   - `fix/<task-id>-<short-name>`
   - `docs/<task-id>-<short-name>`
   - `chore/<task-id>-<short-name>`
5. Record the base commit SHA in the task handoff or PR description.

### Check-in / completion rules

1. Never push task changes directly to `main`.
2. Commit changes only to the task branch.
3. Run the relevant tests, validation, or document checks before requesting integration.
4. Perform a code review before merge. For project work, use `$independent-phase-reviewer` or another independent reviewing agent that did not author the change.
5. Resolve all blocking review findings before merge.
6. **Every check-in to `main` must go through a Pull Request.** Direct commits to `main` are prohibited.
7. The PR must state:
   - task/phase ID when applicable,
   - base commit or branch,
   - summary of changes,
   - files/artifacts changed,
   - tests/validation run and results,
   - safety/scientific implications when applicable,
   - known limitations and remaining risks,
   - reviewer outcome.
8. A PR must not be merged until the required review is complete and blocking findings are resolved.
9. If review requires changes, update the same task branch, rerun affected tests, and request review again.
10. After merge, use a new branch for the next task rather than continuing work on the merged branch.

Detailed procedure: `docs/AGENT_GIT_WORKFLOW.md`.

## Mandatory project constraints

1. Read the relevant project docs before changing architecture or interfaces: `docs/ARCHITECTURE.md`, `docs/PROJECT_EXECUTION_PLAN.md`, `docs/COMPLETION_CRITERIA.md`, and `docs/RISK_REGISTER.md`.
2. MaleCNS-derived control selects behavior intent; it must not directly command servos.
3. `robotd` and the existing MicroDuck motion/safety stack retain motor ownership.
4. Simulation precedes physical robot testing.
5. Biological claims require traceable evidence; engineering mappings must be labeled as engineering choices.
6. A task is not done without evidence matching its task/phase completion criterion.
7. Do not silently relax safety limits, acceptance thresholds, dataset versions, or baseline definitions.

## Multi-agent handoff contract

Every handoff must state:
- input commit/version,
- working branch name,
- configuration and random seed when applicable,
- files/artifacts produced,
- tests/commands run and outcomes,
- code-review status and reviewer,
- PR URL/number when submitted,
- known limitations,
- unresolved risks,
- completion/gate status.

Use `$independent-phase-reviewer` before declaring a phase gate complete.