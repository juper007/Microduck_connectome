# Detailed Task Breakdown / WBS

Task IDs are stable references for issues, commits, and experiment logs.

| ID | Phase | Task | Primary role | Key output | Completion criterion |
|---|---|---|---|---|---|
| P0-01 | 0 | Pin MaleCNS release | Connectomics | dataset manifest | `male-cns:v1.0` recorded |
| P0-02 | 0 | Pin MicroDuck commits | DevOps | version manifest | runtime + RL SHAs recorded |
| P0-03 | 0 | Create environment | DevOps | lock/config | clean install succeeds |
| P0-04 | 0 | Smoke test | QA | smoke test | dataset query + imports pass |
| P1-01 | 1 | neuPrint client | Data Eng | client module | known query passes |
| P1-02 | 1 | Annotation schema | Data Eng | normalized metadata | schema validation passes |
| P1-03 | 1 | Connectivity extraction | Connectomics | edge table | reproducible counts |
| P1-04 | 1 | Cache/provenance | Data Eng | cache manifest | source/version embedded |
| P1-05 | 1 | Graph API | Data Eng | graph module | unit tests pass |
| P2-01 | 2 | Validate LC4/LPLC2 | Neurobiology | pathway card | evidence reviewed |
| P2-02 | 2 | Validate DNa02 | Neurobiology | pathway card | left/right IDs confirmed |
| P2-03 | 2 | Validate DNp01/GF | Neurobiology | pathway card | interpretation scoped |
| P2-04 | 2 | Validate MDN | Neurobiology | pathway card | IDs/evidence confirmed |
| P2-05 | 2 | Select tracking inputs | Connectomics | decision record | candidates compared |
| P3-01 | 3 | Define neuron model | Comp Neuro | design note | parameters explicit |
| P3-02 | 3 | Sparse graph runtime | SWE | runtime | tests pass |
| P3-03 | 3 | Stimulus injection | Comp Neuro | API | bounded injection tests |
| P3-04 | 3 | Population readout | SWE | API | body/type readout tested |
| P3-05 | 3 | Determinism test | QA | test report | fixed replay identical |
| P3-06 | 3 | Performance profile | GPU/Perf | benchmark | p95 documented |
| P3-07 | 3 | 10-min soak | QA | report | no NaN/Inf/explosion |
| P4-01 | 4 | Camera target detector | Vision | feature stream | fixture tests pass |
| P4-02 | 4 | Looming estimator | Vision | feature stream | monotonic approach test |
| P4-03 | 4 | ToF proximity encoder | Sensor | feature stream | loss-safe behavior |
| P4-04 | 4 | Neural sensory mapping | Encoding | stimulus adapter | side tests pass |
| P4-05 | 4 | Stimulus visualizer | QA | plot/log | traces inspectable |
| P5-01 | 5 | DN activity aggregator | Control | readout | unit tests |
| P5-02 | 5 | Steering decoder | Control | `vyaw` | direction tests |
| P5-03 | 5 | Escape decoder | Control | stop/backward | threshold tests |
| P5-04 | 5 | Safety clamp | Safety | gate | malformed input rejected |
| P5-05 | 5 | Watchdog | Safety | timeout | crash/stale tests pass |
| P5-06 | 5 | Command logger | DevOps | structured logs | timestamps complete |
| P6-01 | 6 | Launch official sim | Simulation | repeatable command | sim healthy |
| P6-02 | 6 | robotd IPC client | Integration | client | health query passes |
| P6-03 | 6 | Bounded motion command | Integration | turn/forward | heading changes |
| P6-04 | 6 | Scheduler | Integration | loop | cadence measured |
| P6-05 | 6 | End-to-end telemetry | DevOps | trace | sensor→command correlated |
| P6-06 | 6 | Restart/fault tests | Safety | report | safe failover |
| P6-07 | 6 | 10-min closed loop soak | QA | report | no runaway command |
| P7-01 | 7 | Target scenario | Simulation | scenario | deterministic |
| P7-02 | 7 | Closed-loop target steering | Behavior | demo | correct turn ≥ target |
| P7-03 | 7 | Distractor tests | Experiment | results | false steer measured |
| P7-04 | 7 | Noise tests | Experiment | results | robustness curve |
| P8-01 | 8 | Looming scenario | Simulation | scenario | deterministic |
| P8-02 | 8 | Closed-loop avoidance | Behavior | demo | trigger before boundary |
| P8-03 | 8 | False-positive suite | Experiment | results | threshold met |
| P8-04 | 8 | Sensor-loss suite | Safety | results | safe state |
| P9-01 | 9 | Real topology fixture | Connectomics | graph | frozen |
| P9-02 | 9 | Shuffled topology | ML/Stats | graph generator | structural stats checked |
| P9-03 | 9 | Random reservoir | ML | baseline | scale matched |
| P9-04 | 9 | Conventional baseline | Control/ML | baseline | interface matched |
| P9-05 | 9 | Shared trial generator | Experiment | suite | same seeds |
| P9-06 | 9 | Batch evaluation | Experiment | raw results | all controllers run |
| P9-07 | 9 | Statistical report | Statistics | report | CI/uncertainty present |
| P9-08 | 9 | Independent reproduction | Reviewer | sign-off | rerun matches |
| P10-01 | 10 | Hardware safety checklist | Safety | checklist | all gates green |
| P10-02 | 10 | Low-speed interface test | HW | log | directions verified |
| P10-03 | 10 | E-stop validation | Safety | log | immediate safe behavior |
| P10-04 | 10 | Restrained robot test | HW | log | no unexpected actuation |
| P10-05 | 10 | Physical steering demo | HW | trial set | repeated success |
| P10-06 | 10 | Physical looming demo | HW | trial set | safe response |
| P10-07 | 10 | Release report | Lead | final package | project DoD satisfied |

## Task-state rules

Allowed states:

`BACKLOG → READY → IN_PROGRESS → REVIEW → DONE`

Additional terminal states:

- `BLOCKED`
- `REJECTED`
- `NOT_PLANNED`

A task may enter `DONE` only when its explicit completion criterion has evidence linked from the issue or report.

## Dependency highlights

- P2 depends on P1.
- P3 can start after P1 graph format is frozen.
- P4 can run in parallel with P3.
- P5 requires P3 readout API.
- P6 requires P5 safety gate.
- P7/P8 require P6.
- P9 requires at least P7 and P8.
- P10 requires all P6 safety criteria plus relevant P7/P8 simulation gates.
