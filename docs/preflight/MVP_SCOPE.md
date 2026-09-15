# MVP Scope and Definition Freeze

Status: **FROZEN for Phase 0**  
Version: P-1.1  
Date: 2026-09-15

## 1. Purpose

The first MVP exists to answer one narrow engineering question:

> Can a MaleCNS-derived network participate causally in a safe closed-loop MicroDuck behavior in the official MuJoCo simulator?

The MVP is **not** intended to reproduce a living fly brain, solve general autonomy, or directly control MicroDuck joints.

## 2. MVP success target

The MVP is complete when both behaviors below run end-to-end from sensor observation through MaleCNS-derived activity to a safe `robotd` intent:

1. **Visual target-following steering** — a target presented left/right causes the simulated MicroDuck to turn **toward the target**.
2. **Looming stop** — an approaching obstacle causes a safe stop before a predefined safety boundary.

The first vertical slice is visual target-following steering. Looming is added only after the steering slice passes its integration gate.

## 3. In scope

### Environment

- Official MicroDuck MuJoCo simulator only for MVP acceptance.
- Linux x86_64 primary development environment.
- NVIDIA GPU is optional; CPU execution must remain available for tests and small fixtures.

### Connectome

- MaleCNS dataset: `male-cns:v1.0`.
- Connectivity is obtained from official MaleCNS/neuPrint sources or a reproducibly generated local cache.
- The MVP uses a deterministic MaleCNS-derived recurrent graph model.

### Behavior A — visual target-following steering

Frozen behavior contract:

```text
camera/synthetic target
    -> target_x [-1,+1]
    -> lateralized visual sensory injection
    -> MaleCNS-derived network
    -> left/right steering descending-neuron readout
    -> behavior decoder
    -> safety gate
    -> robot.move(vx, vy, vyaw)
    -> heading moves toward target bearing
```

The **steering descending readout is DNa02 left/right** for the first candidate implementation. MaleCNS Cell Type Explorer currently exposes one DNa02 neuron per side. The exact v1.0 body IDs must be queried and pinned before code references them.

`LC10a` is the initial target-tracking sensory candidate because it is present as a visual-projection population in MaleCNS. However, **LC10a is not accepted merely by name**: the Connectome Researcher must demonstrate a plausible MaleCNS v1.0 path from the chosen sensory population toward the DNa02 readout before that input population is frozen in configuration. If LC10a fails that evidence gate, another lateralized visual-projection population may replace it through an architecture decision record without changing the steering interface contract.

The image-side-to-yaw relationship is not guessed. `INTERFACE_AND_TIMING_CONTRACT.md` requires an official-simulator fixture that establishes the `vyaw` sign, after which a left target must command the calibrated left-turn sign and a right target the opposite sign.

### Behavior B — looming stop

Frozen behavior contract:

```text
camera/ToF approach evidence
    -> looming_strength [0,1]
    -> validated looming-sensitive sensory population
    -> MaleCNS-derived network/readout
    -> stop intent
    -> safety gate
    -> frozen stop transport semantics
```

`LPLC2` is the initial looming sensory candidate and must be validated against MaleCNS v1.0 before body IDs are frozen. The final descending readout for looming remains a **pre-implementation evidence gate**; the project must not hard-code a literature label that does not map cleanly to MaleCNS v1.0.

Before looming benchmark trials, the integration agent must freeze one verified robot-facing stop mechanism for that experiment version rather than mixing `robot.stop` and zero-twist semantics across trials.

## 4. Explicit non-goals for the MVP

The following are out of scope until the MVP gates pass:

- physical MicroDuck autonomous testing,
- direct Dynamixel/servo commands from the connectome controller,
- replacement or retraining of MicroDuck gait policies,
- audio, speech, microphone, or LLM behavior,
- general object recognition,
- navigation or mapping,
- backward-walking behavior as an MVP acceptance requirement,
- online synaptic plasticity,
- biologically faithful membrane/channel simulation,
- claims that the runtime reproduces actual fly neural activity,
- optimization for embedded deployment,
- full whole-CNS real-time performance as a prerequisite for the first vertical slice; validated subgraphs are allowed during bring-up.

## 5. Fixed architectural boundary

MaleCNS-derived logic produces **behavior intent only**. `robotd` remains authoritative for gait, balance, safety, actuator limits, and the motor bus.

No module under this project may open the MicroDuck Dynamixel serial device or bypass `robotd` safety.

## 6. MVP order of execution

1. Synthetic feature -> sensory injection -> DNa02 readout, no robot.
2. Readout -> decoder -> bounded `vyaw`, no robot.
3. Decoder -> official MicroDuck simulator through `robotd` IPC.
4. Real/simulated camera target -> target-following steering end to end.
5. Looming feature -> validated neural path -> one frozen stop mechanism end to end.
6. Baseline/ablation comparison.

## 7. Change control

Items marked **Frozen** may change only when:

1. a blocking technical/scientific finding is documented,
2. `$microduck-pm-architect` records the proposed change and impact,
3. `$independent-phase-reviewer` reviews it,
4. the change goes through the normal branch/review/PR workflow.

A failed experiment is not by itself justification to relax an acceptance threshold.

## 8. Preflight exit checklist

This document passes preflight when:

- [x] simulator-only MVP is explicit,
- [x] first behavior is visual **target-following** steering,
- [x] second behavior is looming stop,
- [x] DNa02 left/right is the steering readout candidate,
- [x] candidate sensory populations are identified but require MaleCNS v1.0 evidence before body-ID freeze,
- [x] yaw direction must be simulator-calibrated,
- [x] looming trials must use one frozen verified stop mechanism,
- [x] direct motor control is prohibited,
- [x] non-goals are explicit,
- [x] scope-change procedure is defined.

## References

- MaleCNS project: https://male-cns.janelia.org/
- MaleCNS downloads: https://male-cns.janelia.org/download/
- Male CNS Cell Type Explorer DNa02: https://reiserlab.github.io/celltype-explorer-drosophila-male-cns/types/DNa02.html
- Male CNS Cell Type Explorer LC10a: https://reiserlab.github.io/celltype-explorer-drosophila-male-cns/types/LC10a_R.html
- Male CNS Cell Type Explorer LPLC2: https://reiserlab.github.io/celltype-explorer-drosophila-male-cns/types/LPLC2_L.html
- MicroDuck robotd design: https://github.com/pollen-robotics/microduck/blob/main/docs/design/robotd-design.md
