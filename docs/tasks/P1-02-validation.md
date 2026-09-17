# P1-02 validation handoff

- Task: P1-02 annotation schema; status REVIEW (not a Phase 1 gate claim).
- Input/fetched origin/main base: `6fa4680adcf964402061c1f8e0f8dfd55296eca1`.
- Branch: `feature/p1-02-annotation-schema`; isolated `work/p1-02-annotation-schema`.
- Context: AGENTS, data-engineer skill, task packet, token/context policy, WBS row,
  data/repro policy §7/§13/§14, package client/constants and existing test style.
  Narrow scope; no whole architecture/docs preload; <25K target; medium task effort.
- Configuration: Python 3.13, stdlib only, synthetic fixtures, no network; seed N/A.
- Files: task packet, annotations module, annotation tests, schema documentation,
  this validation handoff. No transport or robot changes.
- Local command: `python -m unittest discover -s tests -v` — 30 tests pass
  (15 annotation tests and 15 existing client tests); subsequent quiet suite also
  passed after explicit signed-64-bit boundary coverage. `git diff --check` passed.
- Contract: exact five-key input projection; explicit nulls; side vocabulary
  left/right/null is local and not asserted to enumerate live source values;
  source_note/extraction_commit/dataset envelope retained, no scientific inference.
- Limitations: no real annotation query or source vocabulary validation; caller
  provenance is validated structurally, not authenticated; integer-preserving JSON
  consumers required. Query/transform lineage belongs in source note/referenced
  manifest. No population or biological conclusions.
- Independent review: pending PM orchestration against final head. Thor validation:
  pending PM. PR: not submitted. Pre-merge freshness: PM must refetch and verify.
- Unresolved risks: live projection adapter must establish actual field/vocabulary
  semantics before ingestion; derived records must retain the provenance envelope.
