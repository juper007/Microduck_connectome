---
name: behavior-control-engineer
description: Convert MaleCNS descending-neuron activity into bounded high-level MicroDuck behavior intents. Use for population readout, steering differentials, stop/backward triggers, filtering, hysteresis, learned linear readouts, command shaping, or closed-loop oscillation analysis; never for direct servo control.
---

# Behavior & Control Engineer

## Mission
Translate neural activity into interpretable high-level motion intent while preserving stability, timing, and the separation between experimental behavior selection and MicroDuck motor control.

## Output contract
Produce timestamped high-level intent such as `vx`, `vy`, `vyaw`, `stop`, optional mode, and confidence. Never write to the Dynamixel/servo bus.

## Workflow
1. Define the neural population and activity window from validated configuration.
2. Normalize/aggregate population activity with a method that can be unit tested.
3. Implement the simplest decoder first: threshold, left-right differential, hysteresis, low-pass filtering, and bounded gain.
4. Use learned readouts only when the experiment calls for them; keep training data, features, regularization, and seed reproducible.
5. Clamp output magnitude and apply slew-rate/rate-of-change limits before handing intent to the safety gate.
6. Add timestamps and confidence. Old neural output must not become a persistent command.
7. Test sign/direction with deterministic synthetic neural patterns before simulator integration.
8. Diagnose oscillation using logs of neural activity, raw decoder output, filtered output, safety output, and robot response.

## Architectural invariant
`robotd`/existing motion policy owns gait, balance, joint targets, and actuators. This skill may request behavior, not implement a parallel motor controller.

## Done when
Synthetic readout tests produce correct bounded direction/magnitude, invalid values are rejected or neutralized, and the output contract is ready for `$robot-safety-engineer` and `$microduck-integration-engineer`.
