# SO-101 Embodiment Integration Plan

Status: Planned extension  
Phase: P11  
Target release: M11 — Cross-embodiment demonstration

## 1. Purpose

Add the Hugging Face LeRobot SO-101 follower arm as a second physical embodiment for the MaleCNS-derived controller without weakening or rewriting the existing MicroDuck control path.

The goal is not to make MaleCNS directly command SO-101 servo joints. The connectome remains a high-level behavior-selection component. A robot-specific adapter translates bounded, fresh high-level task intent into an SO-101 action using the supported LeRobot `Robot` interface.

This phase demonstrates that the project is an embodied-connectome control platform rather than a MicroDuck-only controller.

## 2. Non-goals

P11 does not:

- replace or modify the frozen MicroDuck `BehaviorIntent` contract used by P5/P6;
- allow the connectome runtime to write directly to the SO-101 motor bus;
- claim that grasping or Cartesian manipulation is a biologically established Drosophila behavior mapping;
- require an SO-101 leader arm for autonomous control;
- promote unvalidated simulation limits directly to physical hardware.

## 3. Architecture

```text
Camera / optional external sensors
              │
              ▼
      PerceptionFrame
              │
              ▼
       Sensory Mapping
              │
              ▼
         MaleCNS Runtime
              │
              ▼
     Descending-Neuron Readout
              │
              ▼
       Robot-neutral TaskIntent
              │
       ┌──────┴─────────┐
       │                │
       ▼                ▼
MicroDuck path      SO-101 path
BehaviorIntent      SO101Adapter
vx/vy/vyaw/stop         │
       │                ▼
       ▼          LeRobot Robot API
 robotd / RL       get_observation()
 motion policy     send_action()
       │                │
       ▼                ▼
  MicroDuck            SO-101
```

The existing MicroDuck P5/P6 path remains unchanged. `TaskIntent` is a new P11 boundary above robot-specific execution.

## 4. Robot-neutral TaskIntent

Initial P11 schema:

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

Rules:

- continuous values are finite and normalized to `[0,1]` or `[-1,1]` as appropriate;
- `stop` overrides every other field;
- stale or malformed intents are rejected before robot-specific translation;
- `grasp` and `release` are engineering task primitives unless supported by a separately reviewed biological mapping;
- every robot adapter defines its own bounded execution envelope.

## 5. SO-101 adapter boundary

The SO-101 adapter owns all LeRobot interaction and is the only project component permitted to call the SO-101 `Robot` action surface.

Expected responsibilities:

1. create/configure an `SO101Follower`;
2. connect and verify calibration/health before motion;
3. acquire observations through `get_observation()`;
4. convert a validated `TaskIntent` to bounded arm targets;
5. send actions only through `send_action()`;
6. enforce joint, step-size, workspace, gripper, freshness, and rate limits;
7. hold/neutralize safely on stale input, disconnect, exception, or controller crash;
8. expose telemetry sufficient to reconstruct intent → action → observed state.

Direct Feetech bus writes from the connectome, decoder, or experiment layers are prohibited.

## 6. Initial behaviors

### P11 behavior A — Visual target orienting

Camera target position produces a horizontal/vertical orienting intent. The SO-101 end effector or selected arm orientation tracks the target while remaining within a conservative workspace.

### P11 behavior B — Looming withdrawal

An increasing looming signal produces a withdrawal/stop response. This is the manipulation embodiment of the same high-level escape concept tested on MicroDuck.

### P11 behavior C — Optional reach/grasp handoff

MaleCNS-derived activity may select a high-level approach/engage state, while a conventional IK or LeRobot manipulation policy performs the detailed reach/grasp trajectory.

The connectome must not be presented as directly solving inverse kinematics or joint-space manipulation.

## 7. Safety invariants

- simulation or dry-run validation precedes powered autonomous SO-101 motion;
- first physical tests use conservative speed/step limits and a clear workspace;
- a human-accessible stop mechanism is required;
- adapter startup defaults to no motion;
- reconnect requires a fresh safe state before non-zero/non-hold actions;
- stale perception, neural output, or task intent must not continue motion;
- no direct motor-bus access exists outside the adapter/LeRobot layer;
- calibration identity and LeRobot version are recorded with every physical trial;
- gripper force/position and workspace bounds are separately limited;
- telemetry records command and observation timestamps.

## 8. P11 task sequence

| ID | Task | Output | Completion criterion |
|---|---|---|---|
| P11-01 | Pin LeRobot + SO-101 environment | version manifest | LeRobot commit/version, Feetech dependency, port/calibration procedure recorded |
| P11-02 | Define TaskIntent | schema + tests | malformed/stale/out-of-range intent rejected |
| P11-03 | Define generic RobotAdapter boundary | interface/ADR | MicroDuck and SO-101 mappings documented without changing P5/P6 contract |
| P11-04 | Implement SO101Adapter | adapter + tests | connect/observe/action/stop lifecycle tested |
| P11-05 | Add SO-101 safety envelope | config + tests | joint/workspace/step/rate limits enforced |
| P11-06 | Camera → target orienting | demo + telemetry | repeated correct-direction response within limits |
| P11-07 | Looming → withdrawal | demo + telemetry | withdrawal/stop occurs before configured boundary |
| P11-08 | Fault/reconnect tests | report | disconnect, stale input, malformed action, restart fail safe |
| P11-09 | 10-minute closed-loop soak | report | no runaway/stale command and no safety-limit violation |
| P11-10 | Cross-embodiment experiment | report/video | same MaleCNS experiment definition drives MicroDuck and SO-101 through separate adapters |

## 9. Gate G11 — SO-101 embodiment validated

Pass only if:

- supported LeRobot APIs are used for observation/action;
- no MaleCNS component directly controls an SO-101 servo;
- P11 safety envelope, stale timeout, stop, disconnect and reconnect tests pass;
- target-orienting and looming-withdrawal demonstrations are reproducible;
- a 10-minute autonomous soak completes without runaway or stale command;
- telemetry reconstructs perception → MaleCNS → TaskIntent → SO-101 action → observation;
- MicroDuck P5/P6 regression tests remain valid;
- cross-embodiment results clearly separate biological mappings from engineering mappings.

## 10. Promotion strategy

Recommended order:

1. SO-101 software adapter with mocked LeRobot Robot;
2. LeRobot simulation/dry-run or action logging fixture where practical;
3. powered follower-arm connectivity and observation test;
4. low-step manually supervised action test;
5. target orienting;
6. looming withdrawal;
7. fault/restart suite;
8. 10-minute closed-loop soak;
9. optional reach/grasp policy handoff;
10. MicroDuck vs SO-101 cross-embodiment demonstration.

## 11. Reproducibility record

Every P11 experiment must record:

- Microduck_connectome commit SHA;
- LeRobot commit/tag/version;
- SO-101 follower configuration and unique calibration identity;
- controller board/serial port identity where practical;
- camera configuration;
- TaskIntent and adapter configuration hashes;
- neural/runtime configuration and dataset version;
- random seed when applicable;
- test scenario and thresholds;
- raw telemetry and summary metrics.

## 12. Upstream references

- LeRobot repository: https://github.com/huggingface/lerobot
- LeRobot SO-101 guide: https://github.com/huggingface/lerobot/blob/main/docs/source/so101.mdx
- LeRobot Robot API: https://github.com/huggingface/lerobot/blob/main/docs/source/api/robots.mdx
- SO-ARM100/SO-101 hardware project: https://github.com/TheRobotStudio/SO-ARM100
