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
2. Before changing files, fetch the remote state (`git fetch --prune origin` or equivalent) and use the freshly fetched `origin/main` as the task base. Do not assume a local `main` is current.
3. Before creating the branch, require a clean working tree (`git status --porcelain` must be empty). Do not auto-stash or carry unrelated local changes into a new task branch.
4. In shared/multi-agent environments, use a dedicated git worktree or otherwise isolated checkout per agent/task whenever possible. Two agents must not concurrently mutate the same working directory.
5. Create a **new task-specific branch directly from the fetched `origin/main`** and record that base SHA.
6. Do not reuse an old branch for an unrelated task.
7. Use descriptive branch names such as:
   - `feature/<task-id>-<short-name>`
   - `fix/<task-id>-<short-name>`
   - `docs/<task-id>-<short-name>`
   - `chore/<task-id>-<short-name>`
8. Record the base commit SHA in the task handoff or PR description.

### Check-in / completion rules

1. Never push task changes directly to `main`.
2. Commit changes only to the task branch.
3. Run the relevant tests, validation, or document checks before requesting integration.
4. Perform a code review before merge. For project work, use `$independent-phase-reviewer` or another independent reviewing agent that did not author the change.
5. Resolve all blocking review findings before merge.
6. **Any commit added to the task branch after a completed review invalidates that review and requires a new review of the final branch diff.** Do not rely on an approval of an older head SHA.
7. **Every check-in to `main` must go through a Pull Request.** Direct commits to `main` are prohibited.
8. The PR must state:
   - task/phase ID when applicable,
   - base commit or branch,
   - summary of changes,
   - files/artifacts changed,
   - tests/validation run and results,
   - safety/scientific implications when applicable,
   - known limitations and remaining risks,
   - reviewer outcome and reviewed head SHA.
9. Before merge, fetch `origin` again and verify the PR branch is based on the current `origin/main`. If `main` advanced, update/rebase/merge the task branch as appropriate, resolve conflicts, rerun affected tests, and perform a new review of the resulting final diff.
10. A PR must not be merged until the required review is current for the final head SHA, current `main` has been accounted for, and all blocking findings are resolved.
11. After merge, use a new branch from newly fetched `origin/main` for the next task rather than continuing work on the merged branch.

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
- fetched `origin/main` base SHA,
- working branch name,
- isolated worktree/checkout when applicable,
- configuration and random seed when applicable,
- files/artifacts produced,
- tests/commands run and outcomes,
- code-review status, reviewer, and reviewed head SHA,
- PR URL/number when submitted,
- pre-merge freshness/sync status,
- known limitations,
- unresolved risks,
- completion/gate status.

Use `$independent-phase-reviewer` before declaring a phase gate complete.