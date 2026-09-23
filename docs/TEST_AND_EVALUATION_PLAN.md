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
- stale timeout,
- P11 TaskIntent schema/range/freshness validation,
- SO-101 adapter action bounding and hold/stop translation.

### Component tests
- neuPrint → local graph,
- video → looming,
- neural injection → readout,
- readout → safe intent,
- intent → simulated robot IPC,
- TaskIntent → mocked LeRobot SO-101 action,
- SO-101 observation → canonical perception/telemetry fixture.

### Integration tests
- camera/synthetic scene → MicroDuck simulator,
- process restart,
- dropped frame,
- dropped neural update,
- simulator restart,
- SO-101 mocked/dry-run connect → observe → action → disconnect lifecycle,
- SO-101 stale/disconnect/reconnect safe-state transition,
- cross-embodiment experiment replay using separate MicroDuck and SO-101 adapters.

### Soak tests
- neural runtime: 10 min minimum,
- closed-loop simulator: 10 min minimum,
- SO-101 closed-loop: 10 min minimum before G11,
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
- continuous maximal looming stimulus,
- SO-101 USB/LeRobot disconnect,
- SO-101 stale TaskIntent replay,
- malformed/non-finite SO-101 action candidate,
- SO-101 reconnect before fresh hold/stop,
- SO-101 workspace/joint/gripper limit violation attempt.

Expected result: safe neutral, hold, or stop as appropriate to the embodiment; never unbounded persistent motion.

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

### SO-101 target orienting
- correct horizontal/vertical response direction,
- target-centering error,
- time to settle,
- oscillation rate,
- workspace-limit events,
- stale/hold transitions.

### SO-101 looming withdrawal
- detection-to-withdraw latency,
- withdrawal distance/step count,
- hold/stop activation,
- false withdrawals,
- missed withdrawals,
- safety-limit events.

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
- LeRobot commit/tag/version when SO-101 is involved,
- SO-101 calibration/configuration identity when SO-101 is involved,
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
- robot adapter type/version,
- TaskIntent trace for P11 trials,
- final metrics.


## 7. P11 cross-embodiment evaluation

P11 must demonstrate portability without pretending that the two robots share identical motor semantics.

For a cross-embodiment trial:

- use the same pinned MaleCNS graph/runtime configuration where the hypothesis requires it;
- use the same high-level stimulus definition and TaskIntent semantics;
- allow robot-specific adapters and safety envelopes to differ;
- record those adapter differences explicitly;
- do not compare raw joint trajectories as though they were equivalent behaviors;
- compare high-level outcomes such as correct orienting direction, response latency, successful withdrawal, stale/fault handling, and safety-limit violations.

G11 requires a reproducible report showing that the same MaleCNS-derived high-level experiment definition can drive both MicroDuck and SO-101 through independent adapters while each robot retains its own low-level execution and safety authority.
