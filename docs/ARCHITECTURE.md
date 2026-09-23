# System Architecture

## 1. Responsibility split

The central rule is:

> MaleCNS chooses **high-level behavioral/task intent**; each supported robot stack owns **motion execution and actuator safety**.

For MicroDuck, `robotd` remains the motor-control owner. For SO-101, the P11 adapter uses the supported LeRobot `Robot` interface and must not bypass LeRobot to let the connectome layer command Feetech servos directly. The project must not create a parallel low-level motor controller.

## 2. Runtime layers

```text
┌─────────────────────────────────────────────┐
│ Robot sensors                               │
│ Camera / ToF / IMU                          │
└──────────────────┬──────────────────────────┘
                   ▼
┌─────────────────────────────────────────────┐
│ Perception features                         │
│ target_x, target_size, looming, proximity   │
└──────────────────┬──────────────────────────┘
                   ▼
┌─────────────────────────────────────────────┐
│ Sensory encoder                             │
│ features → selected MaleCNS population      │
└──────────────────┬──────────────────────────┘
                   ▼
┌─────────────────────────────────────────────┐
│ MaleCNS-derived neural runtime              │
│ graph + temporal state                      │
└──────────────────┬──────────────────────────┘
                   ▼
┌─────────────────────────────────────────────┐
│ Descending-neuron readout                   │
│ steering / escape / backward populations    │
└──────────────────┬──────────────────────────┘
                   ▼
┌─────────────────────────────────────────────┐
│ Behavior decoder                            │
│ vx / vy / vyaw / stop                       │
└──────────────────┬──────────────────────────┘
                   ▼
┌─────────────────────────────────────────────┐
│ Safety gate                                 │
│ clamp / slew / watchdog / stale timeout     │
└──────────────────┬──────────────────────────┘
                   ▼
┌─────────────────────────────────────────────┐
│ Official MicroDuck high-level API           │
│ robotd / JSON-RPC IPC                       │
└──────────────────┬──────────────────────────┘
                   ▼
┌─────────────────────────────────────────────┐
│ Existing RL motion policy + actuator safety │
│ 50 Hz robot control loop                    │
└─────────────────────────────────────────────┘
```

## 3. Timing architecture

MicroDuck's official runtime uses a 50 Hz robot control loop. The connectome controller should target a 20 ms external update where feasible.

If the neural runtime cannot reliably meet this deadline:

- do not block `robotd`,
- run connectome computation asynchronously,
- timestamp outputs,
- let safety gate consume only fresh outputs,
- hold/neutralize after timeout,
- record connectome update rate separately from robot control rate.

## 4. Public module boundaries

Suggested package layout:

```text
src/
├── malecns/
│   ├── client.py
│   ├── graph.py
│   ├── cache.py
│   └── populations.py
├── neural/
│   ├── runtime.py
│   ├── models.py
│   └── readout.py
├── perception/
│   ├── target.py
│   ├── looming.py
│   └── tof.py
├── encoding/
│   └── sensory.py
├── control/
│   ├── decoder.py
│   ├── safety.py
│   └── scheduler.py
├── microduck/
│   ├── ipc.py
│   └── sim.py
├── experiments/
│   ├── scenarios.py
│   ├── baselines.py
│   └── metrics.py
└── logging/
    └── telemetry.py
```

## 5. Data contracts

### Perception frame

```json
{
  "timestamp_ns": 0,
  "target_x": 0.0,
  "target_area": 0.0,
  "looming": 0.0,
  "proximity_left": 0.0,
  "proximity_center": 0.0,
  "proximity_right": 0.0,
  "confidence": 1.0
}
```

### Neural readout

```json
{
  "timestamp_ns": 0,
  "dna02_left": 0.0,
  "dna02_right": 0.0,
  "escape": 0.0,
  "backward": 0.0
}
```

### Behavior intent

```json
{
  "timestamp_ns": 0,
  "vx": 0.0,
  "vy": 0.0,
  "vyaw": 0.0,
  "stop": false,
  "confidence": 1.0
}
```

## 6. Safety invariants

- connectome module cannot access serial servo bus;
- robot motion command has a TTL;
- missing sensor input cannot reuse an old stimulation indefinitely;
- missing neural output cannot reuse an old velocity indefinitely;
- clamp occurs after decoder, before robot API;
- emergency stop overrides all neural outputs;
- simulation limits are not automatically promoted to hardware limits.

## 7. Biological provenance

Every configured population must include:

```yaml
population:
  name: steering_left
  dataset: male-cns:v1.0
  cell_type: DNa02
  side: L
  body_ids: [...]
  evidence:
    source: ...
    confidence: high|medium|exploratory
  engineering_mapping:
    output: positive_yaw
```

This prevents an engineering choice from silently becoming a biological “fact.”


## 8. Cross-embodiment extension (P11)

P11 adds SO-101 without changing the existing MicroDuck P5/P6 control contract.

```text
                     MaleCNS-derived readout
                              │
                              ▼
                    Robot-neutral TaskIntent
                              │
                  ┌───────────┴───────────┐
                  │                       │
                  ▼                       ▼
        MicroDuck translation       SO-101 translation
        BehaviorIntent              SO101Adapter
        vx/vy/vyaw/stop                  │
                  │                       ▼
                  ▼                 LeRobot Robot API
               robotd               get_observation()
                  │                  send_action()
                  ▼                       │
             MicroDuck                    ▼
                                        SO-101
```

The MicroDuck path remains authoritative for locomotion validation. P11 is a separate cross-embodiment layer and must not retroactively relax G5/G6 invariants.

### Robot-neutral TaskIntent

Initial P11 contract:

```json
{
  "timestamp_ns": 0,
  "sequence": 0,
  "horizontal_bias": 0.0,
  "vertical_bias": 0.0,
  "approach": 0.0,
  "withdraw": 0.0,
  "grasp": 0.0,
  "release": 0.0,
  "stop": false,
  "confidence": 1.0,
  "source": "male-cns-controller"
}
```

This contract expresses task-level intent rather than joint targets. `grasp` and `release` are engineering primitives unless a separate biological evidence review explicitly supports a mapping.

### SO-101 adapter responsibilities

The SO-101 adapter:

- owns creation and lifecycle of the LeRobot SO-101 follower object;
- acquires state/camera observations through supported LeRobot interfaces;
- maps fresh validated TaskIntent to bounded arm actions;
- enforces joint, workspace, step-size, rate, gripper, and freshness limits;
- requires a safe/hold state on startup and after reconnect;
- records intent, action, and observation timestamps;
- fails to hold/neutral on stale input, disconnect, exception, or controller crash.

No connectome, perception, neural-runtime, or experiment component may write directly to the SO-101 motor bus.

### Cross-embodiment mapping rule

A neural behavior concept may map differently by embodiment while retaining the same high-level interpretation:

| High-level intent | MicroDuck | SO-101 |
|---|---|---|
| horizontal orient | yaw/steering | arm/end-effector horizontal orienting |
| approach | bounded forward velocity | bounded end-effector approach |
| withdraw/escape | stop/backward primitive | bounded arm retract/hold |
| stop | robot stop/zero twist | hold/neutral action |
| grasp/release | not used in initial locomotion demo | manipulation primitive/policy handoff |

The adapter mapping is an engineering choice and must not be described as a direct biological motor homology.

See `docs/SO101_INTEGRATION_PLAN.md` for the P11 task sequence and safety gate.
