# Experiment Protocol

Status: **FROZEN before benchmark implementation**  
Version: P-1.0  
Date: 2026-09-15

## 1. Research question

Primary question:

> Does the real MaleCNS-derived topology provide measurable value for MicroDuck sensor-to-behavior control compared with matched non-biological baselines?

A successful demo is not sufficient evidence. The project must compare the real topology to controlled alternatives.

## 2. Primary MVP hypotheses

### H1 — steering

A MaleCNS-derived controller can convert lateralized visual input into correct-direction MicroDuck steering in simulation.

### H2 — looming

A MaleCNS-derived controller can convert looming input into a stop response before a predefined safety boundary.

### H3 — topology value

Under matched inputs, safety limits, trial sets, and readout budget, real MaleCNS topology differs measurably from shuffled/random alternatives on at least one pre-registered metric.

H3 may be rejected. A null or negative result is valid and must be retained.

## 3. Controllers to compare

Every final comparative run includes these controller classes:

### A. Real MaleCNS topology

- graph extracted from pinned `male-cns:v1.0`,
- same neural dynamics described in `NEURAL_MODEL_SPEC.md`,
- same sensory and readout interfaces as other reservoir baselines.

### B. Degree-preserving shuffled topology

Goal: destroy biological wiring specificity while preserving as much local graph statistics as practical.

Minimum requirements:

- same neuron count,
- same edge count,
- preserve in/out degree distribution as closely as the chosen shuffle algorithm permits,
- preserve the same weight multiset or weight distribution,
- deterministic from explicit seed,
- generation method recorded and tested.

### C. Matched random sparse reservoir

Minimum requirements:

- same neuron count as evaluated real graph,
- same total edge count,
- weights sampled/reassigned to match the real graph's normalized weight distribution,
- same neural dynamics and external interface,
- explicit seed.

### D. Conventional non-connectome baseline

MVP baseline:

- simple rule/state-machine or small MLP operating on the exact same perception features,
- same final behavior-intent schema,
- same safety gate and robot limits.

If an MLP is used, training examples/epochs/parameter count and tuning budget must be reported.

## 4. Fair-comparison rules

All controllers in a comparison must share:

- identical perception input traces,
- identical simulator initial states,
- identical scenario seeds,
- identical high-level output limits,
- identical downstream safety gate,
- identical success/failure definitions,
- equivalent readout fitting budget where learning is used.

A controller may not receive privileged ground truth unavailable to another controller in the same comparison.

## 5. Behavior A — visual steering protocol

### Scenario

A target appears/moves at known horizontal positions within the camera field.

Trial dimensions should include at minimum:

- target side: left/right,
- target eccentricity: near-center / medium / far,
- target motion: static / slow crossing,
- visual noise level: clean / moderate,
- no-target control trials.

### Primary steering metric

```text
correct_direction_rate
```

A trial is correct when the first sustained turn response after the valid stimulus is in the direction defined by the pre-validated yaw-sign fixture.

### Frozen steering acceptance thresholds

MVP behavior gate:

```text
correct_direction_rate >= 0.90
safety_limit_violations == 0
```

No-target false-turn gate:

```text
false_turn_rate <= 0.05
```

A false turn is a sustained `abs(vyaw) >= 0.10 rad/s` for at least 200 ms during a no-target trial after warm-up.

Secondary metrics:

- absolute target-centering error,
- response latency,
- yaw oscillation count,
- time to enter center tolerance,
- runtime p50/p95/p99 latency.

## 6. Behavior B — looming-stop protocol

### Scenario

An obstacle approaches along controlled trajectories while distractor trials include static or receding objects.

The scenario generator must expose a ground-truth time-to-boundary or distance-to-boundary independent of perception estimates.

### Frozen looming acceptance thresholds

```text
valid_looming_trigger_rate >= 0.95
false_positive_rate <= 0.05
safety_limit_violations == 0
```

Every successful response must be initiated before the predefined simulator safety boundary.

The exact physical/simulation boundary distance is frozen when the scenario geometry is implemented and **before** controller comparison results are examined.

Secondary metrics:

- detection-to-stop latency,
- margin before safety boundary,
- missed response rate,
- distractor false positives,
- sensor-loss behavior.

## 7. Trial counts

Development smoke tests may be small.

For an MVP gate, use at least:

```text
steering: 100 valid target trials + 40 no-target trials per controller
looming: 100 valid approach trials + 40 distractor trials per controller
```

For final topology comparison, run at least 5 independent controller/network seeds where the controller class includes randomness.

If computational cost forces a reduction, the change must be recorded before final results are interpreted.

## 8. Seeds and randomization

- Trial seeds are generated once and stored.
- The same trial seeds are used across controller classes.
- Network/shuffle seeds are separate from simulator scenario seeds.
- Trial execution order should be randomized to avoid systematic warm-up/order effects.
- No failed seed may be silently discarded.

## 9. Statistics

Reports must include raw per-trial values plus summary uncertainty.

Minimum reporting:

- success proportion with 95% confidence interval,
- median and p95 latency,
- mean/median error as appropriate,
- per-seed values,
- failure counts and categories.

For real-vs-baseline comparisons, prefer paired analysis because identical trial seeds are shared.

Do not claim superiority from a single best seed or only from average score without variability.

## 10. Required ablations

At minimum:

1. bypass connectome and feed neutral readout,
2. swap left/right steering readout,
3. remove sensory injection,
4. randomize sensory population assignment,
5. edge dropout at multiple fixed rates,
6. neuron dropout at multiple fixed rates.

The first three are causal sanity checks and must behave in the predicted direction before a topology-value claim is accepted.

## 11. Pre-registration rule

Before a benchmark batch begins, freeze:

- controller versions,
- graph hashes,
- neural parameters,
- scenario generator version,
- metrics,
- thresholds,
- trial seeds,
- safety config,
- readout training/tuning budget.

Any change after results are seen creates a new experiment version and requires rerunning all affected controller classes.

## 12. Raw-data retention

Every run must retain enough information to reconstruct the result:

- perception features,
- neural readout summary,
- behavior intents before and after safety gate,
- robot state/heading,
- timestamps,
- scenario ground truth,
- controller/network identifiers,
- outcome and metric values.

## 13. Reporting rule

The final report must explicitly choose one of these conclusions for each hypothesis:

```text
supported by this experiment
not supported by this experiment
inconclusive under this experiment
```

Do not convert “robot moved” into “fly connectome improves robotics.”

## 14. Preflight exit criteria

- [x] hypotheses are explicit,
- [x] four controller classes are defined,
- [x] comparison fairness rules are frozen,
- [x] steering and looming acceptance thresholds are defined,
- [x] trial-count floor is defined,
- [x] seed/randomization policy is defined,
- [x] required ablations are defined,
- [x] null/negative results are retained,
- [x] changing metrics after results requires a new experiment version.
