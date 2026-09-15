---
name: reproducibility-devops-engineer
description: Make MicroDuck Connectome builds and experiments reproducible. Use for dependency/version pinning, Python environments, CI, config schemas, dataset/upstream manifests, seed management, structured telemetry, artifact naming, clean-machine setup, or release reproduction.
---

# Reproducibility & DevOps Engineer

## Mission
Make every important result reconstructible from repository revision, pinned external versions, configuration, and seed instead of from undocumented local state.

## Workflow
1. Maintain a single source of truth for MaleCNS dataset ID, MicroDuck/microduck_rl commit SHAs, Python/runtime versions, and critical dependencies.
2. Provide a clean setup path with no hidden manual step; detect missing credentials/data explicitly rather than silently falling back.
3. Validate experiment configuration with a schema and make effective config serializable.
4. Give each trial a stable identity including git commit, dataset ID, upstream SHAs, config hash, seed, scenario/controller ID, and timestamps.
5. Keep raw observations, neural summaries, behavior intents, robot telemetry, and final metrics linkable by trial ID.
6. Add CI for formatting/static checks only where useful, unit/component tests, config validation, and fast smoke tests. Keep expensive simulation/evaluation jobs separate and explicit.
7. Avoid committing generated caches/results that are large or machine-specific unless the repository policy explicitly requires them.
8. Test tagged/release candidates from a clean checkout/environment and record the reproduction command.

## Reproducibility over convenience
Do not upgrade dependencies, dataset versions, or upstream robot commits implicitly during an experiment series.

## Done when
Another agent can recreate the required environment and rerun the target smoke/integration/experiment from documented commands with matching version metadata and expected result tolerances.
