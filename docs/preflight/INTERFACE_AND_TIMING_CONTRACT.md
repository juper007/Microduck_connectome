# Interface and Timing Contract

Status: **FROZEN for Phase 0/MVP**  
Version: P-1.0  
Date: 2026-09-15

## 1. Purpose

This document prevents different agents from inventing incompatible coordinate systems, timestamps, stale-data behavior, and message semantics.

## 2. Authority boundary

The only robot-facing output of this project is a high-level MicroDuck intent accepted by the official `robotd` API.

Allowed MVP robot calls:

```text
robot.move(vx, vy, vyaw)
robot.stop
robot.health / robot.state reads as supported by upstream
```

Disallowed:

- direct servo writes,
- opening the Dynamixel bus,
- modifying joint targets behind `robotd`,
- blocking or replacing the official 50 Hz `robotd` control loop.

Upstream MicroDuck uses a right-handed trunk-frame protocol and a 50 Hz control loop. All velocity values remain in the upstream units/protocol; this project does not redefine them.

## 3. Clock contract

All internal messages carry a monotonic timestamp in nanoseconds:

```text
timestamp_ns = monotonic clock, not wall-clock time
```

Wall-clock UTC may be recorded separately for experiment metadata but is never used for control freshness calculations.

Freshness is evaluated from the consumer's monotonic clock against the message timestamp.

## 4. Perception coordinate convention

Normalized image coordinate:

```text
x = -1.0   far left of image
x =  0.0   image center
x = +1.0   far right of image
```

`target_x` must be clamped to `[-1, +1]`.

Image Y coordinates, when added later:

```text
y = -1.0   top
y =  0.0   center
y = +1.0   bottom
```

The MVP steering behavior uses only `target_x`.

## 5. Lateral neural convention

Neural populations must be configured with explicit anatomical side metadata:

```yaml
side: L | R | M
```

Array index, body-ID numeric magnitude, or query return order must never be used to infer side.

The sensory encoder must have fixtures proving that a left-image target activates only the configured left/right stimulus channel intended by that encoder design.

## 6. Robot yaw convention

The project inherits MicroDuck's right-handed trunk-frame protocol.

No agent may guess the behavioral meaning of positive `vyaw` from naming alone. Before closed-loop steering is accepted, the integration test must issue a small positive and negative `vyaw`, measure simulated heading change, and record the observed convention in a machine-readable integration fixture.

The decoder then defines one configuration scalar:

```yaml
steering_yaw_sign: +1 | -1
```

This sign is calibrated once from the official simulator fixture and must not be silently changed to make an experiment pass.

## 7. Perception frame contract

```json
{
  "timestamp_ns": 0,
  "frame_id": 0,
  "target_x": 0.0,
  "target_area": 0.0,
  "looming": 0.0,
  "proximity_left": 0.0,
  "proximity_center": 0.0,
  "proximity_right": 0.0,
  "confidence": 1.0,
  "valid": true
}
```

Ranges:

```text
target_x: [-1, +1]
target_area: [0, 1]
looming: [0, 1]
proximity_*: [0, 1]
confidence: [0, 1]
```

Invalid or stale input must result in neutral sensory injection, not replay of the last valid stimulus indefinitely.

## 8. Neural readout contract

```json
{
  "timestamp_ns": 0,
  "sequence": 0,
  "steering_left": 0.0,
  "steering_right": 0.0,
  "escape": 0.0,
  "runtime_healthy": true
}
```

Readout values are non-negative normalized activity summaries. Difference/sign logic belongs in the behavior decoder.

## 9. Behavior intent contract

```json
{
  "timestamp_ns": 0,
  "sequence": 0,
  "vx": 0.0,
  "vy": 0.0,
  "vyaw": 0.0,
  "stop": false,
  "confidence": 1.0,
  "source": "male-cns-controller"
}
```

The safety gate produces the final robot-facing intent after clamping and freshness checks.

## 10. Control rates

### Upstream robot loop

```text
robotd: 50 Hz / 20 ms period
```

This is authoritative and is not modified by this project.

### Perception

Target:

```text
camera feature update: >= 25 Hz
```

A lower sensor rate may be accepted for recorded fixtures, but autonomous MVP trials must record actual feature rate.

### Neural runtime

Preferred:

```text
50 Hz
```

Allowed asynchronous fallback:

```text
>= 20 Hz
```

### Behavior decoder / safety gate

Runs independently at 50 Hz or whenever a new neural sample arrives plus a 50 Hz watchdog tick. It must never block `robotd`.

## 11. Freshness and timeout constants

Initial frozen defaults:

```yaml
perception_ttl_ms: 100
neural_readout_ttl_ms: 100
behavior_intent_ttl_ms: 100
```

Rules:

- stale perception -> zero/neutral neural injection,
- stale neural output -> zero twist / stop-safe behavior,
- stale behavior output -> no continuing autonomous motion,
- `runtime_healthy=false` -> immediate neutral/stop path.

These TTLs may be made stricter after profiling; they may not be relaxed after observing evaluation failures without ADR + independent review.

## 12. MVP motion envelope

Simulation starts with intentionally conservative autonomous limits:

```yaml
max_abs_vx_mps: 0.08
max_abs_vy_mps: 0.00
max_abs_vyaw_radps: 0.50
max_delta_vx_per_s: 0.20
max_delta_vyaw_per_s2: 1.50
```

`vy` is disabled for the MVP.

These are project-side intent limits in addition to upstream `robotd` safety. They are not hardware limits and do not automatically transfer to physical MicroDuck testing.

## 13. Steering decoder sign test

Required fixture before Behavior Demo A:

1. start official MicroDuck simulator,
2. record initial heading,
3. command `vyaw=+0.2` for a short bounded interval,
4. record heading delta,
5. reset,
6. command `vyaw=-0.2`,
7. record heading delta,
8. prove deltas have opposite sign,
9. freeze `steering_yaw_sign` in versioned config.

## 14. Stop semantics

For an urgent looming response, the preferred interface is the upstream discrete `robot.stop` request when its current semantics are appropriate. Otherwise the controller must continuously publish zero twist until the behavior state returns to normal.

The integration agent must verify actual upstream behavior in the pinned MicroDuck commit; documentation wording alone is not enough for a safety claim.

## 15. Preflight exit criteria

- [x] time source is defined,
- [x] perception coordinates are defined,
- [x] neural side is explicit,
- [x] robot yaw sign is empirically calibrated rather than guessed,
- [x] message schemas are defined,
- [x] rates and TTLs are defined,
- [x] MVP motion envelope is defined,
- [x] stale/invalid behavior is fail-safe,
- [x] `robotd` remains authoritative.

## References

- MicroDuck architecture: https://github.com/pollen-robotics/microduck/blob/main/docs/design/architecture.md
- MicroDuck robotd design: https://github.com/pollen-robotics/microduck/blob/main/docs/design/robotd-design.md
- MicroDuck simulation: https://github.com/pollen-robotics/microduck/blob/main/docs/robot/simulation.md
