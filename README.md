# MicroDuck Connectome

**MaleCNS × Multi-Embodiment NeuroRobotics Project**

This project explores whether the complete adult male *Drosophila* central nervous system connectome (MaleCNS v1.0) can serve as a biologically structured high-level controller across multiple robot embodiments. MicroDuck remains the primary locomotion platform; SO-101 is the planned second embodiment for manipulation-oriented experiments.

The connectome **does not directly command servo joints**. Instead, it receives encoded sensory stimuli and produces high-level behavioral/task intent such as steering, stop/escape, target pursuit, orienting, or withdrawal. MicroDuck's existing `robotd`, safety layer, and reinforcement-learning motion policies remain responsible for balance, gait, and actuator control. For SO-101, a dedicated adapter will translate validated robot-neutral task intent through the supported Hugging Face LeRobot `Robot` interface; the connectome layer will not write directly to the Feetech motor bus.

## Project hypothesis

> Does the real MaleCNS connectivity provide useful inductive structure for embodied robot behavior compared with shuffled-connectome, random-reservoir, and conventional controller baselines?

## Target architecture

```text
Camera / ToF / IMU
        │
        ▼
Perception + Sensory Encoder
        │
        ▼
MaleCNS Runtime / Reservoir
        │
        ▼
Descending-Neuron Readout
        │
        ▼
Robot-neutral TaskIntent
        │
   ┌────┴───────────────┐
   │                    │
   ▼                    ▼
MicroDuck path      SO-101 path
BehaviorIntent      SO101Adapter
vx/vy/vyaw/stop         │
   │                    ▼
   ▼               LeRobot Robot API
robotd / RL             │
motion policy           ▼
   │                  SO-101
   ▼
MicroDuck
```

The existing validated MicroDuck P5/P6 contracts remain unchanged. The robot-neutral `TaskIntent` and SO-101 adapter are introduced as the later P11 cross-embodiment extension.

## Execution sequence

1. Freeze dataset/runtime versions and establish reproducible environment.
2. Build a MaleCNS data/query layer.
3. Validate candidate sensor-to-descending-neuron pathways.
4. Build a deterministic connectome runtime or reservoir prototype.
5. Implement sensory encoders.
6. Implement behavior decoder and safety gate.
7. Integrate with the official MicroDuck MuJoCo simulator.
8. Demonstrate visual steering and looming avoidance.
9. Run real-vs-shuffled-vs-random baseline experiments.
10. Move the validated controller to physical MicroDuck.
11. Add SO-101 as a second embodiment through LeRobot and demonstrate cross-embodiment target orienting and looming withdrawal.

## Codex agent team

Repo-scoped Codex role skills live under [`.agents/skills/`](.agents/skills/). Root [`AGENTS.md`](AGENTS.md) defines task-to-role routing, Git workflow, project constraints, and mandatory token/context-efficiency rules.

The practical project team is documented in [`docs/PM_AGENT_HIRING_PLAN.md`](docs/PM_AGENT_HIRING_PLAN.md). It defines 11 operational roles: PM/Systems Architect, Connectome Research, Connectome Data Engineering, Neural Runtime, Perception/Sensory Encoding, Behavior/Control, MicroDuck Integration, Robot Safety, Experiment/Evaluation, Reproducibility/DevOps, and Independent Phase Review.

Agent work uses lazy context loading and compact task packets so large-model context is spent only on relevant evidence. See [`docs/TOKEN_EFFICIENCY_POLICY.md`](docs/TOKEN_EFFICIENCY_POLICY.md), [`docs/TASK_PACKET_TEMPLATE.md`](docs/TASK_PACKET_TEMPLATE.md), and [`docs/AGENT_CONTEXT_MAP.md`](docs/AGENT_CONTEXT_MAP.md).

## Documentation

- [`docs/PROJECT_EXECUTION_PLAN.md`](docs/PROJECT_EXECUTION_PLAN.md) — end-to-end execution plan
- [`docs/PM_AGENT_HIRING_PLAN.md`](docs/PM_AGENT_HIRING_PLAN.md) — practical agent team, hiring capabilities, and Codex skill mapping
- [`docs/AGENT_ROLES.md`](docs/AGENT_ROLES.md) — detailed responsibility catalog and handoffs
- [`docs/TASK_BREAKDOWN.md`](docs/TASK_BREAKDOWN.md) — detailed task/WBS plan
- [`docs/COMPLETION_CRITERIA.md`](docs/COMPLETION_CRITERIA.md) — Definition of Done and phase gates
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system architecture and interfaces
- [`docs/SO101_INTEGRATION_PLAN.md`](docs/SO101_INTEGRATION_PLAN.md) — P11 SO-101/LeRobot second-embodiment plan
- [`docs/TEST_AND_EVALUATION_PLAN.md`](docs/TEST_AND_EVALUATION_PLAN.md) — test strategy and scientific evaluation
- [`docs/RISK_REGISTER.md`](docs/RISK_REGISTER.md) — technical/scientific risks and mitigations
- [`docs/AGENT_GIT_WORKFLOW.md`](docs/AGENT_GIT_WORKFLOW.md) — mandatory branch/review/PR workflow
- [`docs/TOKEN_EFFICIENCY_POLICY.md`](docs/TOKEN_EFFICIENCY_POLICY.md) — lazy context, context budgets, reasoning and log discipline
- [`docs/TASK_PACKET_TEMPLATE.md`](docs/TASK_PACKET_TEMPLATE.md) — compact agent task handoff template
- [`docs/AGENT_CONTEXT_MAP.md`](docs/AGENT_CONTEXT_MAP.md) — role-specific starting context and reasoning defaults
- [`docs/SOURCES.md`](docs/SOURCES.md) — primary references

## Key principles

- Simulation first.
- Connectome output never bypasses robot-specific safety or supported high-level APIs.
- Existing MicroDuck P5/P6 contracts remain frozen while new embodiments integrate above them through explicit adapters.
- Every biological mapping must be traceable to a source or explicitly marked as a hypothesis.
- Every experiment must be reproducible from configuration + seed + commit SHA.
- Claims about biological advantage require controlled baselines.
- Large context is capacity, not a target; load only the evidence needed for the current task.

## Current status

Preflight definitions frozen; Phase 0 ready.

Phase 0 bootstrap setup and remaining acceptance work:
[`docs/PHASE0_SETUP.md`](docs/PHASE0_SETUP.md).

## Upstream projects

- MaleCNS project: https://male-cns.janelia.org/
- MicroDuck runtime: https://github.com/pollen-robotics/microduck
- MicroDuck RL simulation/training: https://github.com/pollen-robotics/microduck_rl
- Hugging Face LeRobot: https://github.com/huggingface/lerobot
- SO-101 hardware project: https://github.com/TheRobotStudio/SO-ARM100

> This is an independent research/education project and is not an official Pollen Robotics, HHMI Janelia, Google Research, or University of Cambridge project.
