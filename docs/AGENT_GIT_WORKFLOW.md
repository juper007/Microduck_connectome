# Mandatory Agent Git Workflow

This policy applies to **every agent and every repository change** in MicroDuck Connectome, including code, configuration, experiments, documentation, CI, and research artifacts.

## 1. Checkout / start work

Before modifying the repository:

1. Start from the latest `main`.
2. Record the base commit SHA.
3. Create a new branch for the task.
4. Never implement directly on `main`.
5. Never reuse a branch that was already merged for a different task.

Recommended branch names:

```text
feature/<task-id>-<short-name>
fix/<task-id>-<short-name>
docs/<task-id>-<short-name>
chore/<task-id>-<short-name>
experiment/<task-id>-<short-name>
```

If no formal task ID exists yet, use a concise descriptive name and have `$microduck-pm-architect` map it to the WBS when appropriate.

## 2. During implementation

- Keep work scoped to the task.
- Commit only on the task branch.
- Keep architecture, safety, dataset, and experiment constraints from `AGENTS.md` intact.
- Run relevant tests/validation before requesting integration.
- Record commands, results, configuration, and seeds when applicable.

## 3. Mandatory code review

Before work can be merged:

1. Review the complete branch diff against `main`.
2. The authoring agent must not be the sole approver of its own work.
3. Use `$independent-phase-reviewer` for phase-affecting, safety-affecting, scientific, integration, or substantial code changes.
4. A different independent reviewing agent may review small low-risk changes when appropriate.
5. Classify findings by severity and explicitly identify blocking findings.
6. Fix all blocking findings on the same task branch.
7. Rerun tests affected by review changes.
8. Re-review material changes before merge.

A review must check, as applicable:

- correctness and regressions,
- architecture boundaries,
- tests and completion criteria,
- safety behavior and failure modes,
- biological/scientific evidence and overclaims,
- reproducibility and version/seed capture,
- documentation accuracy,
- accidental secrets, generated junk, or unrelated changes.

## 4. Mandatory Pull Request

**Every check-in to `main` must use a Pull Request. Direct commits to `main` are prohibited.**

The PR must include:

- task/phase ID when applicable,
- branch and base commit,
- purpose and scope,
- changed files/artifacts,
- test/validation commands and outcomes,
- code-review outcome and reviewer,
- safety implications,
- scientific/biological implications when applicable,
- known limitations,
- unresolved risks or follow-up work.

## 5. Merge gate

A PR may be merged only when:

- required review is complete,
- no blocking finding remains,
- required tests/validation pass,
- task-specific completion criteria are satisfied or the PR clearly states that it is an intermediate change,
- safety gates are satisfied for any hardware-affecting change.

Do not merge merely because the demo appears to work.

## 6. After merge

- Treat the merged branch as finished.
- Begin the next task from updated `main` on a new branch.
- Do not continue unrelated work on the old branch.
- Include the merged PR/commit in the next agent handoff when it is an input dependency.

## 7. Emergency changes

Even urgent fixes must use a new branch, review, and PR. Urgency may shorten the review cycle but does not permit bypassing it.

## 8. Handoff checklist

Every implementation handoff should state:

```text
Task/Phase:
Base commit:
Working branch:
Changes:
Tests/validation:
Reviewer:
Review status:
PR:
Known limitations:
Unresolved risks:
Next owner:
```
