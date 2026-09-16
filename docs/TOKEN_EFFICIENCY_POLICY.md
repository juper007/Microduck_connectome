# Token and Context Efficiency Policy

Status: **MANDATORY for agent work**  
Version: 1.0  
Date: 2026-09-15

## 1. Goal

Use GPT-6 Astra (and other project models) for the smallest sufficient context and reasoning effort needed to complete a task correctly. Large context windows are capacity, not a target.

The repository is the durable source of truth. Long chat/session history is not project memory.

## 2. Core rule: lazy context loading

Every agent starts with only:

1. `AGENTS.md`,
2. its own selected `SKILL.md`,
3. the task packet,
4. the smallest task-specific files/sections needed to begin.

Do **not** preload the entire `docs/` tree, all skill files, all source files, or all previous logs.

Load more context only when a concrete uncertainty, failing test, interface dependency, or review finding requires it.

## 3. Context budget targets

These are planning targets, not correctness limits:

| Task class | Target input context |
|---|---:|
| Formatting, config, small docs | < 10K tokens |
| Normal coding/test task | < 25K tokens |
| Complex integration/debugging | < 50K tokens |
| Architecture/scientific review | < 80K tokens |
| >100K tokens | Must be justified in the task handoff |

If a task appears to need >100K tokens, first ask whether the task can be split, summarized, indexed, or narrowed to specific sections/files.

## 4. Task packets are mandatory

The PM/architect should assign work using the compact structure in `docs/TASK_PACKET_TEMPLATE.md`.

A task packet must identify:

- task/phase ID,
- one measurable goal,
- owner skill,
- exact required inputs,
- exact files/sections to read first,
- files explicitly not to preload when useful,
- outputs,
- acceptance criteria,
- context budget,
- recommended reasoning effort,
- reviewer.

The packet should normally be hundreds of tokens, not thousands.

## 5. Role-specific context map

Use `docs/AGENT_CONTEXT_MAP.md` to choose the default documents and recommended reasoning effort for each skill.

The map is a starting point, not permission to read every listed document in full. Prefer headings, line ranges, diffs, or focused searches.

## 6. Reasoning-effort policy

Use the lowest effort that reliably satisfies the task.

Project defaults:

- `low`: mechanical edits, formatting, simple CI/config, repetitive changes,
- `medium`: normal coding, data plumbing, integration, PM decomposition,
- `high`: neuroscience interpretation, neural dynamics, safety, experimental design, difficult control logic, independent review,
- `xhigh/max`: only for unusually hard blocked tasks after medium/high is insufficient.

Astra should not default to the highest effort for routine tasks.

## 7. Repository navigation

Prefer this order:

1. task packet,
2. exact task/WBS entry,
3. exact relevant heading in a contract/spec,
4. targeted code search,
5. modified/dependent files,
6. broader repository exploration only if needed.

Do not read a complete large document when one section answers the task.

## 8. Tool and data output discipline

Never feed large raw data/tool outputs to the model when a compact summary can preserve the decision-relevant information.

Examples:

- Large neuPrint result -> store/cache the data; provide row counts, selected IDs, edge counts, validation failures, and artifact path/hash.
- Test output -> provide pass/fail counts and failing stack traces, not thousands of passing lines.
- Runtime log -> provide the failure window plus a short tail/head when needed.
- Telemetry -> compute metrics first; pass summaries and suspicious intervals.
- Large JSON -> extract the required fields before model review.

Raw artifacts remain available for targeted follow-up.

## 9. Log limits

Default diagnostic payload:

- last 100 relevant log lines, or
- the exception plus 30 lines before/after, or
- a structured summary with links/paths to the full artifact.

Increase only when the smaller window is insufficient.

## 10. Review context policy

The independent reviewer should begin with:

1. task packet / acceptance criteria,
2. PR diff,
3. changed files,
4. test/validation summary,
5. relevant contract section(s).

The reviewer should inspect unrelated repository files only when a detected risk or dependency requires them.

A small PR should not trigger a full-repository reread.

## 11. Session lifecycle

Prefer a fresh agent session/task context for each WBS task or logically independent PR.

Carry forward durable state through:

- Git commits and PRs,
- task packets,
- ADRs/specs,
- issues,
- experiment manifests,
- artifacts and hashes.

Do not depend on a long conversation transcript to preserve project decisions.

## 12. Prompt/cache-friendly structure

Keep stable global instructions compact and stable:

- `AGENTS.md` = routing and mandatory rules,
- `SKILL.md` = role-specific workflow,
- detailed knowledge = linked project docs,
- task-specific instructions = task packet.

Avoid copying the same long policy text into every skill. This reduces both context size and instruction drift.

## 13. PM responsibilities

The PM/architect must:

- split oversized tasks,
- create compact task packets,
- state a context budget,
- state recommended reasoning effort,
- list only necessary starting context,
- prevent broad exploratory reading when an exact source is known,
- require summaries instead of raw large tool output.

## 14. Agent responsibilities

Every executing agent must:

- stay within the assigned context scope where practical,
- not preload unrelated docs,
- summarize large outputs before handing them off,
- request/inspect additional context only when justified,
- record newly discovered dependencies for the next task packet,
- flag when the context budget is insufficient rather than silently reading the whole repository.

## 15. Reviewer responsibilities

The reviewer must evaluate whether unnecessary context expansion occurred when it materially increases cost or hides the actual evidence trail.

Token efficiency never overrides correctness, safety, scientific traceability, or reproducibility. If more context is required to establish those, load it and record why.

## 16. Success metrics

Track qualitatively at first:

- how many documents/files were loaded per task,
- whether a task packet was used,
- whether large logs/data were summarized,
- whether >100K context was justified,
- whether task scope had to be split because context was too broad.

Do not spend more tokens measuring tokens than the measurement can save.
