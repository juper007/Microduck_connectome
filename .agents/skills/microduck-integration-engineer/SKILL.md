---
name: microduck-integration-engineer
description: Integrate the connectome controller with the official MicroDuck simulator/runtime using supported high-level interfaces. Use for robotd IPC/JSON-RPC, MuJoCo launch and scenarios, 50 Hz scheduling, telemetry, simulator lifecycle, or simulator-to-hardware interface compatibility.
---

# MicroDuck Simulation & Integration Engineer

## Mission
Close the loop through the official MicroDuck architecture without creating a competing motor-control path.

## Workflow
1. Inspect the pinned upstream MicroDuck and `microduck_rl` commits before relying on API details; prefer their docs/code over remembered interfaces.
2. Establish baseline simulator health without the connectome controller.
3. Connect through the supported `robotd`/IPC high-level intent surface. Keep motor/IMU ownership in the official runtime.
4. Implement connection health checks and timestamp telemetry before autonomous motion.
5. Integrate the safety-gated behavior intent; do not send raw neural values directly to the robot runtime.
6. Measure scheduling and end-to-end latency relative to MicroDuck's 50 Hz control loop.
7. Test start/stop, IPC disconnect, controller restart, simulator restart, and stale messages.
8. Build deterministic scenarios and reset mechanics for target steering and looming/obstacle trials.
9. Keep simulator-specific code behind an adapter so the high-level interface can later target physical MicroDuck without changing neural/control semantics.

## Physical promotion rule
Do not move autonomous behavior to hardware until `$robot-safety-engineer` verifies the required gates in `docs/COMPLETION_CRITERIA.md`.

## Done when
The simulator can be driven through supported high-level intent, failure/restart tests fail safe, timing is measured, and trial scenarios are replayable from seed/config.
