# Agent Roles and Responsibilities

This document defines the specialized agents required to execute the project. A role can be performed by a human, an autonomous coding/research agent, or a hybrid reviewer.

## 1. Technical Lead / Architect Agent

**Purpose:** Own the system boundary and prevent local optimizations from breaking the project.

**Responsibilities**
- approve architecture,
- decide module boundaries,
- maintain phase dependencies,
- resolve cross-workstream conflicts,
- approve changes to public interfaces,
- ensure research claims match implemented system.

**Inputs:** all design docs, phase results, risks.  
**Outputs:** architecture decisions, accepted interfaces, go/no-go decisions.  
**Done when:** no unresolved P0 architectural blocker exists for the next phase.

---

## 2. Connectomics Research Agent

**Purpose:** Make MaleCNS use scientifically traceable.

**Responsibilities**
- query `male-cns:v1.0`,
- resolve body IDs/types/sides,
- extract weighted subgraphs,
- validate graph provenance,
- maintain neuron-set configuration,
- distinguish dataset facts from engineering assumptions.

**Outputs**
- neuron catalogs,
- graph extracts,
- pathway connectivity reports,
- provenance metadata.

**Done when:** every neuron population used by code maps to pinned MaleCNS records and source evidence.

---

## 3. Neurobiology Literature Agent

**Purpose:** Validate behavioral interpretation of selected neurons.

**Responsibilities**
- find primary publications,
- summarize experimental evidence,
- assign evidence strength,
- flag contradictory findings,
- prevent labels such as “escape neuron” from being treated as stronger claims than evidence allows.

**Done when:** each biological mapping has an evidence note and confidence rating.

---

## 4. Data Engineering Agent

**Purpose:** Make connectome data reproducible and efficient.

**Responsibilities**
- build neuPrint client,
- schema validation,
- cache/version extraction,
- graph serialization,
- metadata normalization,
- extraction tests.

**Done when:** source-to-cache transformation is deterministic and auditable.

---

## 5. Computational Neuroscience Agent

**Purpose:** Design the dynamical interpretation of a static connectome.

**Responsibilities**
- choose MVP neuron model,
- define decay/threshold/integration,
- model excitatory/inhibitory information only where justified,
- design stimulation/readout windows,
- test dynamical stability.

**Done when:** runtime dynamics are explicit, configurable, and stable.

---

## 6. GPU / Performance Agent

**Purpose:** Ensure network execution can support embodied control.

**Responsibilities**
- sparse graph profiling,
- CPU/GPU comparison,
- latency/memory measurement,
- batching only if it preserves online semantics,
- optimize bottlenecks after profiling.

**Done when:** p50/p95/p99 step latency and memory are measured and acceptable for the chosen scheduling model.

---

## 7. Computer Vision / Perception Agent

**Purpose:** Convert camera/ToF observations into robust physical features.

**Responsibilities**
- target detection,
- looming calculation,
- confidence estimation,
- feature filtering,
- camera test fixtures,
- sensor-failure behavior.

**Done when:** perception feature tests pass independently of the connectome.

---

## 8. Sensory Encoding Agent

**Purpose:** Map machine features to synthetic fly neural stimulation.

**Responsibilities**
- select input neural populations,
- define stimulus amplitude/rate,
- lateralize left/right input,
- prevent saturation,
- document where mappings are biological vs engineered.

**Done when:** controlled features create predictable stimulation traces and stay within configured bounds.

---

## 9. Behavior Decoder / Control Agent

**Purpose:** Convert descending-neuron activity into robot-level intent.

**Responsibilities**
- population activity aggregation,
- differential steering,
- hysteresis/filtering,
- learned linear readout experiments,
- output confidence,
- command normalization.

**Done when:** neural-output unit tests generate correct, bounded high-level commands.

---

## 10. MicroDuck Runtime Integration Agent

**Purpose:** Integrate without violating official control/safety architecture.

**Responsibilities**
- use official simulator/runtime interfaces,
- understand `robotd` intents,
- connect via supported IPC,
- manage health checks,
- synchronize control cadence,
- keep motor ownership in `robotd`.

**Done when:** connectome controller can drive the simulator using supported high-level API only.

---

## 11. Safety Agent

**Purpose:** Remain authoritative over all experimental controllers.

**Responsibilities**
- watchdog,
- stale-command timeout,
- velocity/yaw clamps,
- slew-rate limits,
- stop logic,
- process-crash behavior,
- hardware E-stop gate,
- safety test matrix.

**Done when:** all defined fault injection scenarios resolve to a safe state.

---

## 12. Simulation Agent

**Purpose:** Create controlled repeatable robot scenarios.

**Responsibilities**
- launch MuJoCo stack,
- generate target/obstacle trajectories,
- reset environment,
- provide trial ground truth,
- automate repeated trials.

**Done when:** scenarios are deterministic from seed and can run unattended.

---

## 13. Experiment Design Agent

**Purpose:** Turn demos into falsifiable experiments.

**Responsibilities**
- define hypotheses,
- metrics,
- baselines,
- shared trial sets,
- randomized seeds,
- ablations,
- acceptance thresholds before results are viewed.

**Done when:** experiment plan can distinguish “works” from “connectome adds value.”

---

## 14. Statistics / Evaluation Agent

**Purpose:** Analyze performance without cherry-picking.

**Responsibilities**
- aggregate trials,
- confidence intervals,
- effect sizes where appropriate,
- failure distribution,
- latency distributions,
- robustness curves.

**Done when:** results are generated by script from raw logs and include uncertainty.

---

## 15. QA / Independent Reviewer Agent

**Purpose:** Challenge assumptions and independently reproduce claims.

**Responsibilities**
- run setup from clean checkout,
- review test coverage,
- validate completion criteria,
- reproduce key demo,
- reject phase completion when evidence is insufficient.

**Done when:** release checklist is independently signed off.

---

## 16. DevOps / Reproducibility Agent

**Purpose:** Make every result reconstructible.

**Responsibilities**
- environment lock,
- CI,
- version manifest,
- config schema,
- artifact naming,
- seed management,
- structured logs.

**Done when:** tagged release can reproduce key results on a clean machine.

---

# Handoff protocol

Every agent handoff must include:

1. input version/commit,
2. configuration used,
3. produced files,
4. tests executed,
5. known limitations,
6. unresolved risks,
7. explicit completion-criteria status.

No phase may rely only on an informal chat summary.
