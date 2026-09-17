# P0 bootstrap handoff

- Owner: reproducibility-devops-engineer; coordination: microduck-pm-architect.
- Task scope: P0-01/P0-02 records; P0-03/P0-04 bootstrap subset.
- Base: `6056aa892abc4bcc8879d2f1e76bcdee077ef495` (freshly fetched origin/main).
- Branch: `chore/p0-version-baseline`; dedicated project checkout under `work/`.
- Context: AGENTS, PM/DevOps skills, P0 WBS and execution criteria, data policy,
  upstream environment metadata and simulator launch instructions. No raw data.
- Outputs: version manifest, uv project/lock, smoke script, CI, setup guide.
- Acceptance for this change: immutable upstream IDs; locked Linux data-client
  install; offline import success; missing online credential fails explicitly.
- Biological facts are limited to official dataset access documentation.
  No neural model, sensory mapping, robot commands or safety limits changed.
- Phase status: IN_PROGRESS; online dataset access requires NEUPRINT_TOKEN.
- Review status and validation evidence are recorded in the review handoff.
- P0-03/P0-04 and the overall phase remain incomplete; see PHASE0_SETUP.md.
