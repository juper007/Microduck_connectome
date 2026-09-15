# System Architecture

## 1. Responsibility split

The central rule is:

> MaleCNS chooses **behavioral intent**; MicroDuck owns **motion execution and actuator safety**.

The project must not create a parallel motor controller.

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
