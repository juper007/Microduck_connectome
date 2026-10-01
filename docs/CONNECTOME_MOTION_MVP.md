# Connectome Motion MVP

Status: **interactive demo / iteration path**

This track exists to answer one question quickly:

> Can the real MaleCNS-derived controller make MicroDuck visibly react in MuJoCo?

It does **not** replace P8 scientific validation. P8 keeps its frozen timing, causality, evidence, baseline, and reproducibility gates unchanged. The MVP is a separate fast path for development and visual confirmation.

## Minimal path

```text
synthetic camera target / looming
        ↓
existing PerceptionPipeline
        ↓
existing SensoryMapper
        ↓
real MaleCNS controller graph v2
        ↓
existing SparseNeuralRuntime
        ↓
DNa02 / DNp01 readout
        ↓
SteeringDecoder / EscapeDecoder
        ↓
SafetyClamp + ControllerWatchdog
        ↓
RobotMotionAdapter
        ↓
official robotd
        ↓
MicroDuck RL policy + MuJoCo
```

The connectome layer never writes servo/joint commands. `robotd` remains the motor-control owner.

## MVP success criteria

One short run should visibly demonstrate:

1. left-target and right-target stimuli create non-zero **opposite yaw commands** through DNa02 steering,
2. the looming stimulus activates the DNp01 escape readout and produces a connectome-derived `stop`,
3. all robot-facing commands still pass through the existing safety/watchdog/robotd path.

This is intentionally a demo gate. It does not require shuffled/random baselines, 20-trial statistics, Wilson intervals, evidence manifests, nanosecond causality attribution, or P8 completion claims.

## Run on Thor

Prerequisites:

- official MicroDuck MuJoCo / `duck-sim` is running,
- `robotd` is running and healthy with the walking policy available,
- the graph-v2 artifact from `data/manifests/controller-graph-v2.json` exists at its Thor path,
- run from the repository checkout that contains this MVP.

Validate the graph and configs without moving the robot:

```bash
uv run python -m microduck_connectome.mvp_demo --check-only
```

Run the visual demo:

```bash
uv run python -m microduck_connectome.mvp_demo
```

The default robotd socket is `/run/robotd.sock`. The default graph cache/key are read from `data/manifests/controller-graph-v2.json`.

If the Thor graph lives elsewhere:

```bash
uv run python -m microduck_connectome.mvp_demo \
  --graph-cache /path/to/graph-cache \
  --graph-key <64-char-graph-key>
```

## What to watch

The run lasts about 6.4 seconds and cycles through:

```text
neutral → left → right → center → stop/looming
```

The terminal emits only meaningful transitions, for example:

```json
{"event":"turn","scenario":"left","vyaw":0.12}
{"event":"turn","scenario":"right","vyaw":-0.11}
{"event":"neural_escape","escape":0.6,"robot_stop":true}
{"demo_result":"PASS","opposite_left_right_turns":true,"connectome_escape_stop_seen":true}
```

At the same time, watch the MuJoCo window for the body/head orientation response and final stop.

## Relationship to P8

P8 remains the research-validation track and is still required before making scientific claims such as “the MaleCNS topology performs better than shuffled/random controls.”

The MVP has a different purpose: make the full controller easy to run, inspect, debug, and demonstrate before spending time on research-grade evidence collection.
