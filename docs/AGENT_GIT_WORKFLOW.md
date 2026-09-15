# Mandatory Agent Git Workflow

This policy applies to **every agent and every repository change** in MicroDuck Connectome, including code, configuration, experiments, documentation, CI, and research artifacts.

## 1. Checkout / start work

Before modifying the repository, the agent must establish a fresh and isolated task base.

### Required sequence

1. Fetch the remote state:

```bash
git fetch --prune origin
```

2. Verify the current working directory is clean:

```bash
git status --porcelain
```

The command must produce no output. If there are uncommitted or untracked files, stop and resolve ownership of those changes. **Do not automatically stash, discard, or carry them into the new task branch.**

3. Record the fetched base SHA:

```bash
git rev-parse origin/main
```

4. Create a new task branch **from `origin/main`, not from a possibly stale local `main`**:

```bash
git switch -c <task-branch> origin/main
```

Equivalent tooling is acceptable only if it creates the branch from the freshly fetched remote base.

5. Record the branch name and base SHA in the task handoff or PR description.

### Multi-agent isolation

When multiple agents may work concurrently, use a dedicated git worktree or otherwise isolated checkout for each agent/task whenever possible.

Example:

```bash
git fetch --prune origin
git worktree add ../wt-<task-name> -b <task-branch> origin/main
```

Rules:

- two agents must not concurrently mutate the same working directory;
- do not reuse a worktree that contains unrelated uncommitted changes;
- do not auto-stash another agent's work;
- a branch already merged must not be reused for a different task.

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
- Do not merge unrelated cleanup into the task merely because it is nearby.

## 3. Preparing for review

Before requesting code review:

1. Fetch `origin` again.
2. Check whether `origin/main` has advanced since the recorded base.
3. If it has advanced and the new `main` may affect interfaces, assumptions, dependencies, generated artifacts, tests, or safety behavior, update the task branch before review.
4. Run all relevant tests/validation against the resulting branch.
5. Record the exact head SHA to be reviewed:

```bash
git rev-parse HEAD
```

The reviewer must review the complete final branch diff against the appropriate current `main`, not only individual commits in isolation.

## 4. Mandatory code review

Before work can be merged:

1. Review the complete branch diff against `main`.
2. The authoring agent must not be the sole approver of its own work.
3. Use `$independent-phase-reviewer` for phase-affecting, safety-affecting, scientific, integration, or substantial code changes.
4. A different independent reviewing agent may review small low-risk changes when appropriate.
5. Classify findings by severity and explicitly identify blocking findings.
6. Fix all blocking findings on the same task branch.
7. Rerun tests affected by review changes.
8. Record the reviewed head SHA in the review/PR.

### Review invalidation rule

**Any commit added to the task branch after a completed review invalidates that review.**

This includes:

- code changes,
- documentation changes committed to the branch,
- conflict-resolution commits,
- merge/rebase results that change the branch head,
- generated-file updates,
- test-fix commits.

After any such commit, the final branch diff must be reviewed again and the new head SHA recorded.

Changes that do not alter the branch head—such as editing only the PR description or adding a discussion comment—do not invalidate review.

A review must check, as applicable:

- correctness and regressions,
- architecture boundaries,
- tests and completion criteria,
- safety behavior and failure modes,
- biological/scientific evidence and overclaims,
- reproducibility and version/seed capture,
- documentation accuracy,
- accidental secrets, generated junk, or unrelated changes.

## 5. Mandatory Pull Request

**Every check-in to `main` must use a Pull Request. Direct commits to `main` are prohibited.**

The PR must include:

- task/phase ID when applicable,
- task branch,
- fetched `origin/main` base SHA,
- purpose and scope,
- changed files/artifacts,
- test/validation commands and outcomes,
- code-review outcome and reviewer,
- reviewed head SHA,
- safety implications,
- scientific/biological implications when applicable,
- known limitations,
- unresolved risks or follow-up work.

## 6. Final merge freshness gate

Immediately before merge, perform a final remote freshness check.

1. Fetch `origin` again:

```bash
git fetch --prune origin
```

2. Verify that current `origin/main` is contained in the task branch history:

```bash
git merge-base --is-ancestor origin/main HEAD
```

If this check fails, `main` advanced after the task branch was synchronized. Update the task branch using the repository's accepted merge/rebase strategy, resolve any conflicts, and rerun affected tests.

3. Because synchronizing with a newer `main` changes the branch head, **the previous review is invalidated**. Review the final diff again and record the new reviewed head SHA.

4. Verify no commits were pushed after that final review.

5. Merge only when all of the following are true:

- the required review covers the current final head SHA;
- current `origin/main` has been incorporated/accounted for;
- no blocking finding remains;
- required tests/validation pass after the final synchronization;
- task-specific completion criteria are satisfied or the PR clearly states that it is an intermediate change;
- safety gates are satisfied for any hardware-affecting change.

Do not merge merely because the demo appears to work.

## 7. After merge

- Treat the merged branch as finished.
- Fetch `origin` again before the next task.
- Begin the next task from the newly fetched `origin/main` on a new branch/worktree.
- Do not continue unrelated work on the old branch.
- Include the merged PR/commit in the next agent handoff when it is an input dependency.

## 8. Emergency changes

Even urgent fixes must use a fresh branch from fetched `origin/main`, clean/isolate the working directory, receive review, pass the final freshness gate, and use a PR. Urgency may shorten the review cycle but does not permit bypassing it.

## 9. Handoff checklist

Every implementation handoff should state:

```text
Task/Phase:
Fetched origin/main base SHA:
Working branch:
Worktree/checkout:
Changes:
Tests/validation:
Reviewer:
Reviewed head SHA:
Review status:
PR:
Pre-merge origin/main SHA:
Freshness/sync status:
Known limitations:
Unresolved risks:
Next owner:
```
