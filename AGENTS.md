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
- configuration and random seed when applicable,
- files/artifacts produced,
- tests/commands run and outcomes,
- known limitations,
- unresolved risks,
- completion/gate status.

Use `$independent-phase-reviewer` before declaring a phase gate complete.