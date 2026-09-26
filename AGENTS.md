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

P11 SO-101 work is a cross-role extension rather than a new repo-scoped skill: route architecture through `$microduck-pm-architect`, task-intent/control semantics through `$behavior-control-engineer`, hardware/fault boundaries through `$robot-safety-engineer`, reproducibility through `$reproducibility-devops-engineer`, and final gate review through `$independent-phase-reviewer`. Do not route SO-101 low-level motor control into the MaleCNS/connectome layer.

## Mandatory token/context efficiency

These rules apply to every agent and are subordinate only to correctness, safety, scientific traceability, and reproducibility.

1. Use **lazy context loading**. Start with `AGENTS.md`, the selected `SKILL.md`, the task packet, and only the exact task-specific sections/files needed to begin.
2. Do not preload the whole `docs/` tree, all skill files, the whole repository, long chat history, raw datasets, or full logs without a concrete need.
3. PM-assigned implementation/research work should use a compact task packet based on `docs/TASK_PACKET_TEMPLATE.md`.
4. Use `docs/AGENT_CONTEXT_MAP.md` for role-specific starting context and recommended reasoning effort.
5. Follow the context-budget targets in `docs/TOKEN_EFFICIENCY_POLICY.md`; tasks expected to exceed 100K input tokens should be split or explicitly justified.
6. Summarize large tool/data/log outputs before handing them to another agent. Keep raw artifacts by path/hash for targeted follow-up.
7. Reviewers begin with acceptance criteria, PR diff, changed files, validation summary, and relevant contract sections; expand to unrelated files only when a finding/dependency requires it.
8. Prefer a fresh task/session for each independent WBS task or PR. Durable state lives in Git, issues, task packets, ADRs/specs, manifests, and artifacts—not in accumulated conversation history.
9. Use the lowest reasoning effort that reliably completes the task. `xhigh/max` is exceptional rather than a default.

Detailed policy: `docs/TOKEN_EFFICIENCY_POLICY.md`.

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

1. Read only the relevant sections needed for the task before changing architecture or interfaces; use the task packet/context map to locate them. Expand context when necessary rather than preloading `docs/ARCHITECTURE.md`, `docs/PROJECT_EXECUTION_PLAN.md`, `docs/COMPLETION_CRITERIA.md`, and `docs/RISK_REGISTER.md` in full.
2. MaleCNS-derived control selects behavior intent; it must not directly command servos.
3. For MicroDuck, `robotd` and the existing motion/safety stack retain motor ownership. For SO-101 P11 work, the supported Hugging Face LeRobot `Robot` interface and the dedicated SO-101 adapter own robot action delivery; connectome/perception/neural layers must not write directly to the Feetech motor bus.
4. Simulation precedes physical robot testing.
5. Biological claims require traceable evidence; engineering mappings must be labeled as engineering choices.
6. A task is not done without evidence matching its task/phase completion criterion.
7. Do not silently relax safety limits, acceptance thresholds, dataset versions, or baseline definitions.

## Multi-agent handoff contract

Every handoff must state:
- task packet/task ID,
- input commit/version,
- fetched `origin/main` base SHA,
- working branch name,
- isolated worktree/checkout when applicable,
- context scope/budget and any exceptional expansion,
- recommended/used reasoning effort when materially relevant,
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


## Compact Task DSL

Short task invocations may use `docs/MICRODUCK_TASK_DSL.md`.

Example:

```text
@run P8-R3
profile=P8R3
continue=G8
```

The DSL is only a compact reference layer. It does not replace or weaken this file, selected repo-scoped `SKILL.md` contracts, task/phase acceptance criteria, Git/review rules, safety constraints, scientific traceability, or reproducibility requirements.

For DSL tasks:

1. Parse only syntax explicitly defined in `docs/MICRODUCK_TASK_DSL.md`.
2. Resolve `base=latest` by freshly fetching `origin/main`; never use conversation memory as the base.
3. Resolve the task packet/profile, then load only this file, the actual owner `SKILL.md`, and minimum task-specific context first.
4. `owner` and `support` aliases require actual use of the corresponding repo-scoped skills; aliases are not descriptive labels.
5. `wf=std` means the complete mandatory Git/review workflow in this file.
6. `review=independent` requires a separate `$independent-phase-reviewer`; the authoring agent/session cannot self-satisfy independent review.
7. Existing normative acceptance criteria override abbreviated DSL gates or profile defaults.
8. Unknown or ambiguous DSL tokens must not be guessed.
9. Durable task state belongs in Git, PRs, task packets, manifests, and evidence rather than the invoking prompt.
10. Compact prompting never reduces required test, evidence, safety, or scientific rigor.
