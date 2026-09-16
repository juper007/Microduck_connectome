# Agent Context Map

Purpose: give each project agent the smallest useful starting context. Read exact sections first; expand only when needed.

| Skill | Default reasoning | Read first | Usually do not preload |
|---|---|---|---|
| `microduck-pm-architect` | medium | task packet; relevant WBS entry; exact contract sections needed for the decision | all implementation source, raw logs, all research docs |
| `connectome-researcher` | high | task packet; `MVP_SCOPE`; relevant MaleCNS/source notes; exact pathway evidence | MicroDuck runtime internals, CI, unrelated experiment logs |
| `connectome-data-engineer` | medium | task packet; data/repro policy; neural graph representation section | perception, robot integration, experiment protocol unless requested |
| `neural-runtime-engineer` | high | task packet; `NEURAL_MODEL_SPEC`; timing contract sections | full literature corpus, perception details, hardware docs |
| `perception-sensory-encoder` | medium | task packet; MVP behavior section; perception/interface contract | full connectome graph internals, baseline statistics, hardware docs |
| `behavior-control-engineer` | high | task packet; neural readout section; interface/timing contract; behavior acceptance criteria | raw MaleCNS bulk data, unrelated perception internals |
| `microduck-integration-engineer` | medium | task packet; architecture robot boundary; interface/timing contract; pinned upstream docs | biological literature, full experiment statistics |
| `robot-safety-engineer` | high | task packet; risk register; safety invariants; relevant completion gate | unrelated graph/data internals unless a failure depends on them |
| `experiment-evaluation-scientist` | high | task packet; experiment protocol; data/repro policy; relevant acceptance criteria | implementation internals not needed to judge fairness |
| `reproducibility-devops-engineer` | low/medium | task packet; data/repro policy; Git workflow; exact CI/environment files | neuroscience literature, robot behavior details unless needed by CI |
| `independent-phase-reviewer` | high | task packet; PR diff; changed files; test summary; violated/relevant criteria | full repository and all docs unless a finding requires expansion |

## Common always-available context

Every agent may rely on:

- `AGENTS.md`,
- its own `SKILL.md`,
- the assigned task packet.

Everything else is loaded on demand.

## Reasoning escalation

Use the table default first. Escalate one level only when the task remains blocked because it requires deeper synthesis, ambiguity resolution, or difficult debugging. `xhigh/max` is exceptional and should be noted in the handoff when used for substantial work.

## Context expansion rule

Before reading a large additional document or directory, state internally which unresolved question it is expected to answer. Prefer a heading, search result, diff, or line range over a complete file.

## Reviewer exception

Safety/scientific reviewers may expand context without the normal budget when necessary to establish a blocking risk. Record the reason for expansion so the PM can improve later task packets.
