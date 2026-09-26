# MicroDuck Task DSL

Status: **versioned compact invocation contract**  
Version: **1.0**

## Purpose

MicroDuck Task DSL is a small prompt layer for repo-scoped agent work. It exists to avoid repeating stable project instructions in every prompt.

It does **not** replace or weaken:

- `AGENTS.md`
- selected `.agents/skills/*/SKILL.md`
- task packets
- phase/gate acceptance criteria
- Git/review policy
- safety/scientific constraints
- reproducibility requirements

Precedence:

```text
AGENTS.md
> selected SKILL.md
> normative task/phase contracts
> task packet/profile
> DSL invocation
```

If a shorter DSL instruction conflicts with a stronger repository contract, the repository contract wins.

## Minimal form

```text
@run <TASK>
```

Defaults:

```text
base=latest
wf=std
pm=auto
ctx=lazy
review=independent
scope=task
continue=task
merge=pass
evidence=full
```

Example:

```text
@run P8-R3
```

means: resolve the current task packet/profile from the repository, use fresh `origin/main`, route work through the actual repo-scoped skill(s), execute the mandatory Git/test/evidence/review workflow, and stop when that task reaches PASS/FAIL/BLOCKED.

## Syntax

One directive per line or compact space-separated key/value pairs:

```text
@run TASK
key=value
key=value
```

Example:

```text
@run P8-R3
profile=P8R3
continue=G8
```

Lists use commas:

```text
support=neural,behavior,integration,safety,eval,repro
```

Comments begin with `#`.

Unknown keys, aliases, or values must **not** be guessed. Use this specification or the canonical repository contract.

## Skill aliases

| Alias | Repo-scoped skill |
|---|---|
| `pm` | `$microduck-pm-architect` |
| `research` | `$connectome-researcher` |
| `data` | `$connectome-data-engineer` |
| `neural` | `$neural-runtime-engineer` |
| `perception` | `$perception-sensory-encoder` |
| `behavior` | `$behavior-control-engineer` |
| `integration` | `$microduck-integration-engineer` |
| `safety` | `$robot-safety-engineer` |
| `eval` | `$experiment-evaluation-scientist` |
| `repro` | `$reproducibility-devops-engineer` |
| `reviewer` | `$independent-phase-reviewer` |

Aliases are execution routing, not labels. When an alias is selected, the corresponding `SKILL.md` must be loaded and applied.

## Core aliases

### `base=latest`

Freshly fetch `origin/main` and use that fetched commit as the base. Never resolve `latest` from conversation memory or a stale checkout.

### `wf=std`

Resolve to the **complete mandatory Git workflow in `AGENTS.md`**, including:

```text
fetch -> clean tree -> fresh base -> new task branch/worktree
-> implement -> tests -> evidence -> commit/push -> PR
-> independent exact-head review -> resolve blockers
-> refresh/sync current main -> rerun affected checks
-> re-review changed head -> merge only on PASS
```

The DSL does not redefine those rules; it references them.

### `ctx=lazy`

Load only:

1. `AGENTS.md`
2. selected owner `SKILL.md`
3. task packet/profile
4. smallest exact task-specific context needed

Expand only for a concrete dependency, failing test, review finding, safety issue, or scientific uncertainty.

### `review=independent`

Use a separate `$independent-phase-reviewer`. The authoring agent/session cannot satisfy independent review itself.

### `pm=auto`

Use `$microduck-pm-architect` to resolve current durable repository state, dependencies, task packet, skill routing, and next gate. PM must not replace narrower specialist skills for implementation.

## Scope and continuation

Valid scope values:

```text
scope=task
scope=phase
scope=gate
```

Valid continuation forms:

```text
continue=task
continue=phase
continue=G8
continue=none
```

`continue=G8` means continue through repository-defined dependencies until G8 reaches a legitimate PASS/FAIL/BLOCKED decision. It does not authorize skipping intermediate task reviews or gates.

## Profiles

Profiles live under:

```text
docs/dsl/profiles/
```

Use:

```text
profile=<NAME>
```

Profiles contain durable routing/invariant defaults, not current result claims. Current state must still be resolved from Git/evidence.

## Frozen invariants

Compact form:

```text
keep=graph:v2,escape:0.5,boundary:0.25m,stop:robot.stop,motor:robotd
```

`keep=` means these factors are frozen for the task unless a separately versioned remediation explicitly changes them. Always verify the actual current config/hash before execution.

Common tokens:

```text
graph:v2
escape:0.5
boundary:0.25m
stop:robot.stop
motor:robotd
neural:v1
sensory:v1
watchdog:v1
```

## Gates

Compact syntax:

```text
gate.<name>=<condition-list>
```

Examples:

```text
gate.internal=approach:3/3,controls:0
gate.thor=preboundary:3/3,safety:0,deadman:0
gate.final=trigger>=0.95,fpr<=0.05,safety=0
```

These are compact references only. Existing normative acceptance criteria override abbreviated gate expressions.

## Failure policy

Default:

```text
fail=retain,stop
```

Optional remediation form:

```text
fail=retain,newver,retry
```

Meaning:

- retain failed raw evidence
- classify root cause
- do not relabel/rewrite the result
- create a separately versioned remediation when required
- use fresh development seeds when required
- rerun affected scope

This never authorizes result-driven threshold/boundary/seed manipulation.

## Merge policy

Default:

```text
merge=pass
```

Merge only after all required acceptance, tests/evidence, independent exact-head review, and main freshness checks pass.

Development/negative evidence may use:

```text
merge=never
```

There is no force-merge mode.

## Task packet resolution

For `@run TASK`:

1. Prefer an exact task packet under `docs/tasks/`.
2. If absent and `pm=auto`, PM creates the smallest sufficient packet from `docs/TASK_PACKET_TEMPLATE.md`.
3. Resolve acceptance from existing normative phase/task contracts.
4. Do not invent weaker criteria.
5. Durable state comes from Git, PRs, task packets, manifests, and evidence—not long prompt history.

## Evidence

`evidence=full` means the evidence required by the task contract, including applicable source/config hashes, seeds, commands, raw artifact paths, metrics, limitations, PR/review state, and reviewed SHA.

Compact prompting never reduces evidence requirements.

## Handoff shorthand

Agents may write:

```text
@handoff
task=<id>
skill=<alias>
base=<sha>
head=<sha>
branch=<branch>
result=PASS|FAIL|BLOCKED
tests=<summary>
evidence=<path>
pr=<number>
review=<status>:<sha>
fresh=<sha>
limits=<short-summary>
```

Large raw outputs remain referenced by path/hash.

## Examples

Task only:

```text
@run P8-R3
```

Task with profile:

```text
@run P8-R3
profile=P8R3
```

Continue through G8:

```text
@run P8-R3
profile=P8R3
continue=G8
```

Project audit only:

```text
@run AUDIT
owner=pm
base=latest
scope=phase
continue=none
merge=never
```

Final Phase-8 chain:

```text
@run P8-FINAL
profile=P8FINAL
continue=G8
```

## Design rule

Stable policy belongs in Git. Prompts should contain only the task delta.

Prefer:

```text
@run P8-R3 continue=G8
```

over copying thousands of tokens of stable repository instructions.
