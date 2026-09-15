# Test and Evaluation Plan

## 1. Test pyramid

### Unit tests
- graph parsing,
- population selection,
- timestep dynamics,
- feature normalization,
- left/right mapping,
- decoder math,
- safety clamp,
- stale timeout.

### Component tests
- neuPrint → local graph,
- video → looming,
- neural injection → readout,
- readout → safe intent,
- intent → simulated robot IPC.

### Integration tests
- camera/synthetic scene → MicroDuck simulator,
- process restart,
- dropped frame,
- dropped neural update,
- simulator restart.

### Soak tests
- neural runtime: 10 min minimum,
- closed-loop simulator: 10 min minimum,
- later release target: 1 h.

## 2. Required fault injections

- camera disconnect,
- ToF disconnect,
- malformed feature value,
- NaN neural activity,
- connectome process crash,
- connectome process freeze,
- delayed command,
- robotd restart,
- IPC disconnect,
- extreme target position,
- continuous maximal looming stimulus.

Expected result: safe neutral or stop; never unbounded persistent motion.

## 3. Behavior metrics

### Steering
- correct turn direction,
- heading error,
- target centering error,
- time to center,
- oscillation rate,
- false turn with no target.

### Looming
- detection-to-command latency,
- response boundary distance/time,
- false positives,
- missed responses,
- collision rate.

## 4. Connectome-value experiment

Controllers:
1. real MaleCNS topology,
2. shuffled topology,
3. random sparse reservoir,
4. conventional controller.

Control variables:
- same perception features,
- same safety gate,
- same trial seeds,
- same robot state initialization,
- same output bounds,
- equivalent readout training budget where learning is used.

Report:
- mean/median,
- dispersion,
- confidence interval,
- per-seed results,
- failure cases,
- runtime cost.

## 5. Ablations

At minimum:
- remove DNa02 readout,
- swap L/R readout,
- remove looming input,
- randomize sensory population,
- edge dropout at several rates,
- neuron dropout at several rates.

Ablations test causality and robustness, not only task score.

## 6. Reproducibility record per trial

Each trial log must include:
- git commit,
- MaleCNS dataset ID,
- upstream MicroDuck commit,
- config hash,
- random seed,
- scenario ID,
- start/end timestamp,
- software versions,
- controller type,
- safety profile,
- raw observations,
- neural summary,
- behavior intents,
- robot telemetry,
- final metrics.
