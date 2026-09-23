# Project Execution Plan

Status: Initial baseline  
Date: 2026-09-15

## 1. Mission

Build and experimentally validate a **MaleCNS-driven high-level behavior controller** for MicroDuck.

The system will translate robot sensor observations into biologically inspired sensory stimulation, propagate activity through a MaleCNS-derived network, read activity from selected descending neurons, and convert that activity into safe high-level motion intents accepted by MicroDuck.

The initial target behaviors are intentionally small:

1. steer toward or away from a visual target,
2. stop/escape when a looming obstacle is detected,
3. trigger backward motion when an avoidance pathway is activated.

The project is complete only after the real-connectome controller is compared against controlled baselines.

---

## 2. Success definition

The first complete release is successful when:

- the pipeline runs end-to-end in MicroDuck MuJoCo,
- it operates at a stable control cadence compatible with MicroDuck's 50 Hz runtime,
- no connectome component directly commands a motor,
- the safety gate prevents stale, out-of-range, or unstable commands,
- at least two sensor-driven behaviors work without keyboard/scripted command injection,
- results are reproducible from a clean environment,
- the real connectome is compared against shuffled and random-network baselines,
- a written result states whether the biological topology helps, hurts, or is indistinguishable under the chosen tasks.

---

## 3. Workstreams

### WS-A — Connectomics

Owns MaleCNS data ingestion, biological annotation, pathway hypotheses, and graph construction.

### WS-B — Neural Runtime

Owns network simulation/reservoir implementation, numerical stability, runtime performance, and reproducibility.

### WS-C — Robot Perception

Owns camera/ToF/IMU features and mapping from machine observations to synthetic fly sensory stimuli.

### WS-D — Robot Integration

Owns MicroDuck simulator/runtime connection, behavior commands, timing, and motion-interface compatibility.

### WS-E — Safety & Reliability

Owns clamping, watchdog, stale-command handling, fail-safe transitions, command arbitration, and hardware promotion gates.

### WS-F — Experimentation

Owns baseline controllers, evaluation metrics, trial generation, statistics, result interpretation, and experiment reports.

### WS-G — DevOps / Reproducibility

Owns environment, configuration, CI, deterministic seeds, artifact logging, and documented setup.

---

# 4. Phase plan

## Phase 0 — Scope, repository, and reproducible environment

### Goal

Create a development environment in which the exact MaleCNS dataset, MicroDuck commit, dependencies, and experimental configurations can be reproduced.

### Required agent roles

- **Technical Lead Agent** — makes architecture and scope decisions.
- **Connectomics Research Agent** — validates MaleCNS sources and dataset identifiers.
- **DevOps/Reproducibility Agent** — freezes environment and creates automated checks.
- **QA Agent** — independently verifies setup instructions.

### Detailed activities

1. Pin MaleCNS dataset to `male-cns:v1.0`.
2. Record official Janelia download/query methods.
3. Pin an upstream `pollen-robotics/microduck` commit.
4. Pin an upstream `pollen-robotics/microduck_rl` commit.
5. Define supported host environment:
   - primary: Linux x86_64 + NVIDIA CUDA where available,
   - secondary: CPU-only development mode.
6. Create Python environment metadata.
7. Define configuration schema for:
   - dataset,
   - neuron sets,
   - simulation timestep,
   - random seed,
   - encoder,
   - decoder,
   - safety limits,
   - robot socket.
8. Add smoke-test script.
9. Add CI checks for syntax, unit tests, and config validation.

### Deliverables

- environment definition,
- version manifest,
- source registry,
- smoke-test command,
- initial CI workflow.

### Exit criteria

- clean checkout can recreate environment,
- MaleCNS API query returns a known neuron record,
- MicroDuck simulator checkout/build procedure is documented,
- all pinned versions appear in one manifest,
- smoke test succeeds twice from fresh environments.

---

## Phase 1 — MaleCNS data and graph layer

### Goal

Create a trustworthy graph/data API rather than coupling the project directly to raw neuPrint queries.

### Required agent roles

- **Connectomics Research Agent**
- **Data Engineering Agent**
- **Scientific QA Agent**

### Detailed activities

1. Use `neuprint-python` against `male-cns:v1.0`.
2. Fetch:
   - neuron metadata,
   - side,
   - cell type,
   - class,
   - connectivity,
   - synapse/weight summaries,
   - neurotransmitter predictions where useful.
3. Define canonical internal identifiers using MaleCNS body IDs.
4. Create a local cache format.
5. Create graph extraction APIs:
   - fetch neuron set by type,
   - outgoing neighbors,
   - incoming neighbors,
   - weighted subgraph,
   - shortest/restricted path search,
   - brain ↔ VNC/descending-neuron queries.
6. Add provenance fields to every derived graph.
7. Add sanity checks:
   - no duplicate body ID,
   - valid edge endpoints,
   - positive connection weights,
   - side/type metadata preserved.
8. Generate a graph report for candidate pathways.

### Deliverables

- `malecns` data client,
- cached metadata,
- graph builder,
- pathway report.

### Exit criteria

- same query produces reproducible body IDs,
- graph counts are stable for the pinned release,
- selected pathways can be reconstructed from source data,
- all derived files record dataset version and extraction code version.

---

## Phase 2 — Biological pathway validation

### Goal

Choose only pathways that have enough biological and connectomic evidence to justify use.

### Required agent roles

- **Neurobiology Literature Agent**
- **Connectomics Research Agent**
- **Scientific Reviewer Agent**

### Candidate pathways

- looming: LC4 / LPLC2 family,
- urgent escape: giant-fiber/DNp01-related descending pathway,
- steering: DNa02 left/right,
- backward locomotion: MDN-related pathway,
- target tracking: candidate visual projection pathway selected after MaleCNS validation.

### Detailed activities

For each pathway:

1. verify cell-type names against MaleCNS v1.0,
2. verify left/right body IDs,
3. verify connectivity to relevant downstream structures,
4. collect primary literature,
5. distinguish:
   - experimentally established relation,
   - connectomic inference,
   - project-specific engineering mapping,
6. create a pathway card:
   - biological function,
   - selected input neurons,
   - selected readout neurons,
   - evidence,
   - uncertainty,
   - proposed robot mapping,
7. reject pathways that are annotation-mismatched or insufficiently supported.

### Deliverables

- pathway catalog,
- evidence matrix,
- accepted/rejected candidate list.

### Exit criteria

Every selected neural population has:
- valid MaleCNS IDs,
- source reference,
- known side/type metadata,
- explicit confidence rating,
- explicit statement separating biology from engineering interpretation.

---

## Phase 3 — Neural runtime / reservoir MVP

### Goal

Produce deterministic time-varying activity from a MaleCNS-derived graph.

### Required agent roles

- **Computational Neuroscience Agent**
- **GPU/Performance Agent**
- **Software Engineer Agent**
- **QA Agent**

### Implementation strategy

Start with the simplest controllable model.

**MVP**:
- weighted graph,
- leaky accumulator or LIF-like state,
- signed/typed edge handling only where evidence supports it,
- configurable threshold/decay,
- 20 ms external control tick,
- deterministic seed.

Do not attempt full biophysical realism in MVP.

### Detailed activities

1. define neuron state representation,
2. define edge representation,
3. choose sparse execution format,
4. implement sensory current injection,
5. implement synchronous timestep,
6. expose population activity counters,
7. profile CPU,
8. add optional GPU path only if needed,
9. test identical replay from fixed seed/input,
10. test zero-input stability,
11. test bounded-state behavior,
12. log runtime latency.

### Exit criteria

- deterministic replay passes,
- zero stimulus does not create uncontrolled numerical explosion,
- output activity can be queried by population,
- p95 step latency supports required closed-loop cadence or an explicitly documented multi-rate design,
- no NaN/Inf states during a 10-minute soak test.

---

## Phase 4 — Sensory encoder

### Goal

Convert MicroDuck observations into stable, testable stimulus channels.

### Required agent roles

- **Computer Vision Agent**
- **Sensor Fusion Agent**
- **Connectomics Agent**
- **QA Agent**

### MVP channels

#### A. Target horizontal position

Input:
- camera frame,
- target detector or simple color blob.

Output:
- normalized `target_x ∈ [-1, 1]`,
- confidence,
- size/area.

#### B. Looming

Estimate approach from apparent-size growth or ToF decrease.

Output:
- `looming_strength ∈ [0,1]`,
- side,
- confidence.

#### C. Optional obstacle range

Input:
- ToF.

Output:
- left/center/right proximity channels.

### Detailed activities

1. create prerecorded synthetic/test scenes,
2. implement detector,
3. normalize coordinate convention,
4. low-pass noisy features,
5. convert feature into neural injection pattern,
6. enforce maximum stimulation,
7. unit-test left/right mapping,
8. unit-test stationary target,
9. unit-test approaching target,
10. visualize stimulus traces.

### Exit criteria

- known left stimulus never maps to right by coordinate error,
- fixed scene produces stable output,
- looming score increases monotonically in controlled approach sequence,
- dropped camera/ToF input causes zero/neutral stimulus rather than stale stimulation.

---

## Phase 5 — Descending-neuron decoder and safety gate

### Goal

Translate neural activity to high-level MicroDuck intents without allowing unsafe direct control.

### Required agent roles

- **Control Systems Agent**
- **MicroDuck Runtime Agent**
- **Safety Agent**
- **QA Agent**

### Decoder outputs

Initial interface:

```text
vx       forward/backward velocity intent
vy       optional lateral intent
vyaw     yaw-rate intent
stop     immediate high-level stop request
mode     optional behavior state
confidence
timestamp
```

### Detailed activities

1. select activity window,
2. normalize population activity,
3. derive left/right steering differential,
4. implement threshold/hysteresis,
5. low-pass velocity intents,
6. clamp velocity and yaw,
7. add slew-rate limiting,
8. add command timestamp,
9. watchdog stale controller output,
10. define neutral behavior,
11. add emergency stop override,
12. ensure direct servo API is unavailable to connectome module.

### Exit criteria

- every output is bounded,
- stale output becomes neutral/stop within configured timeout,
- 100% of intentionally malformed outputs are rejected in tests,
- left/right steering tests pass,
- connectome process crash cannot leave a persistent motion command.

---

## Phase 6 — MicroDuck MuJoCo integration

### Goal

Close the control loop against the official simulated MicroDuck.

### Required agent roles

- **MicroDuck Runtime Agent**
- **Simulation Agent**
- **Integration Agent**
- **Safety Agent**
- **QA Agent**

### Detailed activities

1. install/run official MicroDuck simulator,
2. verify `robotd --sim` path,
3. connect through official Unix-socket JSON-RPC client/interface,
4. query health before motion,
5. send bounded velocity intent,
6. establish tick scheduling,
7. record command/robot-state timestamps,
8. measure end-to-end latency,
9. run start/stop/restart tests,
10. verify controller survives simulator restart,
11. add emergency-stop test,
12. create replayable integration scenario.

### Exit criteria

- simulator stands normally without connectome controller,
- connectome client connects without modifying motor-control internals,
- commanded turn changes simulated heading,
- stop returns robot to neutral behavior,
- process restart and dropped messages fail safe,
- 10-minute autonomous soak test completes with no uncontrolled command.

---

## Phase 7 — Behavior Demo A: visual steering

### Goal

Demonstrate sensor → MaleCNS → descending readout → MicroDuck turn.

### Required agent roles

- **Computer Vision Agent**
- **Connectomics Agent**
- **Behavior Agent**
- **Experiment Agent**

### Scenario

A visible target moves left and right across the camera.

### Detailed activities

1. define target stimulus,
2. collect target position ground truth,
3. inject appropriate sensory population,
4. record selected DN activity,
5. decode steering,
6. command `vyaw`,
7. measure angular error,
8. repeat across seeds/speeds/lighting conditions.

### Exit criteria

- robot turns in correct direction in ≥ 90% of valid target trials,
- no-target false steering rate stays below agreed threshold,
- steering remains inside safety envelope,
- all trial data are logged.

---

## Phase 8 — Behavior Demo B: looming avoidance

### Goal

Demonstrate autonomous reaction to a rapidly approaching obstacle.

### Required agent roles

- **Perception Agent**
- **Connectomics Agent**
- **Safety Agent**
- **Experiment Agent**

### Detailed activities

1. build controlled approaching-object simulation,
2. calculate looming signal,
3. inject looming population,
4. measure escape/urgent DN response,
5. map response to stop or backward primitive,
6. measure trigger latency,
7. test non-approaching distractors,
8. test noisy and intermittent sensor data.

### Exit criteria

- trigger occurs before configured safety boundary in ≥ 95% of valid looming trials,
- stationary/distant distractor false-positive rate is below threshold,
- sensor loss yields safe neutral/stop,
- latency distribution is recorded.

---

## Phase 9 — Scientific baseline experiment

### Goal

Determine whether real MaleCNS topology adds measurable value.

### Required agent roles

- **Experiment Design Agent**
- **Statistics Agent**
- **Connectomics Agent**
- **ML Agent**
- **Independent Reviewer Agent**

### Compared controllers

A. real MaleCNS-derived topology  
B. degree-preserving shuffled topology where practical  
C. random sparse reservoir matched for scale/edge density  
D. small conventional MLP/state-machine baseline

### Metrics

- task success rate,
- heading/target error,
- obstacle collision rate,
- response latency,
- false-positive rate,
- sample efficiency for learned readout,
- robustness to sensor noise,
- robustness to neuron/edge dropout,
- runtime latency,
- compute/memory cost.

### Exit criteria

- all models receive equivalent observations,
- all use the same robot safety limits,
- seeds and trial sets are shared,
- baseline generation is reproducible,
- results include confidence intervals or equivalent uncertainty,
- negative/no-difference results are retained,
- experiment report is generated from stored result data.

---

## Phase 10 — Physical MicroDuck promotion

### Goal

Move only the simulation-proven high-level controller to hardware.

### Required agent roles

- **Hardware Integration Agent**
- **MicroDuck Runtime Agent**
- **Safety Agent**
- **Test Engineer Agent**
- **Release Manager Agent**

### Promotion gates

Physical testing is forbidden until:
- simulation phase gates pass,
- watchdog is validated,
- command clamp is validated,
- explicit human E-stop exists,
- robot can be supported/secured during first tests.

### Detailed activities

1. connect controller through supported robot API,
2. begin with robot physically restrained/supported,
3. verify zero-motion neutral state,
4. verify command direction at low limits,
5. verify E-stop,
6. run low-speed steering,
7. run short autonomous trials,
8. inspect falls/thermal/current issues,
9. gradually raise limits only by recorded configuration change.

### Exit criteria

- E-stop passes before autonomous motion,
- no direct actuator bypass exists,
- all commands remain within hardware profile,
- repeated low-speed trials match simulator directionality,
- every hardware trial has logs and config snapshot.

---

## Phase 11 — SO-101 cross-embodiment integration

### Goal

Add the Hugging Face LeRobot SO-101 follower as a second embodiment while preserving the validated MicroDuck P5/P6 path. Demonstrate that the same MaleCNS-derived high-level controller can drive locomotion and manipulation embodiments through separate robot-specific adapters.

### Required agent roles

- **PM/Systems Architect Agent**
- **Behavior/Control Agent**
- **Robot Integration Agent**
- **Robot Safety Agent**
- **Reproducibility/DevOps Agent**
- **Independent Reviewer Agent**

No new repo-scoped agent skill is required by this planning change. SO-101 implementation work should be routed through the existing PM/architecture, behavior/control, safety, reproducibility, and review roles, with integration-specific task packets.

### Design constraints

1. Do not modify or weaken the frozen MicroDuck P5/P6 `BehaviorIntent` and `robotd` safety boundaries.
2. Introduce a robot-neutral `TaskIntent` above robot-specific execution.
3. The SO-101 path must use the supported LeRobot `Robot` interface.
4. The connectome/runtime/decoder layers must not write directly to the Feetech motor bus.
5. Manipulation primitives such as grasp/release are engineering abstractions unless separately supported by reviewed biological evidence.
6. Physical SO-101 testing requires conservative workspace/rate limits, a human-accessible stop, calibrated hardware identity, and fault-safe stale/disconnect behavior.
7. Simulation, mock, dry-run, or action-logging validation precedes powered autonomous motion where practical.

### Detailed activities

1. Pin a LeRobot commit/tag/version and record the SO-101 follower configuration and Feetech dependency.
2. Define and test the robot-neutral `TaskIntent` contract.
3. Define a generic RobotAdapter boundary without changing the MicroDuck P5/P6 interfaces.
4. Implement an SO-101 adapter using LeRobot `connect`, `get_observation`, `send_action`, and `disconnect`.
5. Add joint/workspace/step/rate/gripper/freshness safety limits.
6. Integrate camera observations into the existing perception pipeline.
7. Demonstrate target orienting from MaleCNS-derived steering activity.
8. Demonstrate looming-triggered withdrawal/hold behavior.
9. Run stale-input, malformed-action, disconnect/reconnect, and process-failure tests.
10. Complete a 10-minute autonomous closed-loop soak.
11. Run a cross-embodiment experiment in which the same high-level MaleCNS experiment definition drives MicroDuck and SO-101 through separate adapters.
12. Record full telemetry from perception → neural runtime → TaskIntent → robot-specific action → robot observation.

### Exit criteria

- SO-101 uses supported LeRobot observation/action interfaces;
- no connectome component directly commands an SO-101 servo;
- startup/reconnect defaults are safe;
- stale, malformed, disconnect, and controller-crash cases fail to hold/neutral;
- target orienting and looming withdrawal are reproducible and remain within the configured safety envelope;
- a 10-minute autonomous soak completes with no runaway or stale command;
- telemetry is sufficient to reconstruct the control chain;
- MicroDuck regression evidence remains valid;
- biological mappings and embodiment-specific engineering mappings are explicitly separated.

Detailed plan: `docs/SO101_INTEGRATION_PLAN.md`.

---

# 5. Recommended milestone releases

| Milestone | Meaning |
|---|---|
| M0 | Repository + reproducible environment |
| M1 | MaleCNS query/graph layer |
| M2 | Candidate neural pathways validated |
| M3 | Deterministic neural runtime |
| M4 | Sensor encoder + DN decoder |
| M5 | Closed-loop MicroDuck simulation |
| M6 | Visual steering demo |
| M7 | Looming avoidance demo |
| M8 | Baseline comparison report |
| M9 | Physical MicroDuck low-speed demo |
| M10 | Reproducible research release |
| M11 | SO-101 cross-embodiment demonstration |

---

> P11/M11 is an extension milestone and does not retroactively change the MicroDuck-focused v1 completion definition below. A later multi-embodiment release may promote G11 into the release Definition of Done.

# 6. Definition of project completion

The project is not considered complete merely because the robot moves.

Completion requires:

1. source sensor data controls the robot without scripted motion commands,
2. MaleCNS-derived activity participates causally in action selection,
3. disabling/bypassing the connectome changes the resulting behavior as expected,
4. safety behavior remains independent and authoritative,
5. experiments are reproducible,
6. real-connectome performance is compared with non-biological baselines,
7. conclusions are limited to what the measured data supports.
