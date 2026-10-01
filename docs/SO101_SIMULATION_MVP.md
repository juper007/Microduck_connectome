# SO-101 simulation MVP

Simulation-only engineering demonstration, not biological arm-control validation,
P8 scientific evidence, physical LeRobot integration, or gate G11 completion.
The existing MicroDuck robotd/RL/motion path and frozen contracts are unchanged.

The existing `MvpChain` supplies synthetic perception, real MaleCNS graph-v2,
`SparseNeuralRuntime`, DNa02 differential/temporal steering, DNp01 escape
threshold 0.5 and existing safety clamp. The existing 100 ms watchdog gates a
minimal P11 `TaskIntent` orient/hold subset. The dedicated `SO101SimAdapter`
alone owns arm targets; no physical Robot, bus, serial or network service exists.

The engineering mapping normalizes bounded steering yaw by 0.3 to a horizontal
bias and integrates shoulder-pan at at most 0.2 rad/s, 0.004 rad/control tick,
within +/-0.4 rad. Positive bias means positive shoulder-pan, not a universal
camera/world left convention. Other targets stay at the simulation-only pose
`[0, -0.5, 0.5, 0, 0, 0.5]` radians in order shoulder_pan, shoulder_lift,
elbow_flex, wrist_flex, wrist_roll, gripper. Tracking error is measured rather
than assuming fixed targets imply fixed positions. Stop freezes observed pan
once; position actuators settle with no qpos/qvel overwrites during control.

Malformed/stale (>100 ms), replayed/future input and control gaps latch hold.
Connection/observation/physics faults attempt hold and disconnect if unsuccessful;
a new adapter is required after faults. When this in-process controller stops,
physics also stops stepping. This is not a hardware crash-stop guarantee.

## Official model/environment

- Source: https://github.com/google-deepmind/mujoco_menagerie
- Commit: `4d038b3feae26ec82b46a4d586379114012a8ac7`
- Model: unmodified `robotstudio_so101/scene.xml` + `so101.xml` and assets
- License: upstream `robotstudio_so101/LICENSE`, Apache-2.0; model not vendored
- MuJoCo requirement >=3.1.3; tested/pinned `mujoco==3.3.7`
- Renderer image dependency: `pillow==11.3.0`
- Backend checks clean source pin, six hinge joints, one-to-one named joint
  transmission, unit gear and position actuator gain/bias semantics, pose ranges.

## Run on Thor

```bash
export PATH=/home/juper007/projects/.microduck-tools:$PATH
uv run --with-requirements config/so101_sim_requirements.txt python -m microduck_connectome.so101_demo --backend mock
MUJOCO_GL=egl uv run --with-requirements config/so101_sim_requirements.txt python -m microduck_connectome.so101_demo \
  --backend mujoco \
  --model-dir /home/juper007/projects/so101-menagerie/robotstudio_so101 \
  --output results/so101-mujoco
SO101_MODEL_DIR=/home/juper007/projects/so101-menagerie/robotstudio_so101 \
  uv run --with-requirements config/so101_sim_requirements.txt python -m unittest tests.test_so101_sim tests.test_so101_mujoco
```

For a fresh model checkout, clone upstream with `--filter=blob:none --no-checkout`,
set sparse checkout to `robotstudio_so101`, then checkout the exact commit above.
Simulation dependencies are isolated in a `uv run --with-requirements` environment;
the frozen project `uv.lock` is unchanged. The graph-v2 artifact must exist at the existing manifest's Thor path.

The demo covers neutral, 3 s left, 3 s right, center, 3 s looming plus shutdown.
`summary.json` reports actual joint displacement and signed velocity, neural
escape/healthy-watchdog hold, final 0.5 s drift/velocity and non-pan tracking.
PASS requires opposite displacement >0.01 rad and signed speed >0.01 rad/s,
DNp01 threshold/stop/hold, unchanged final hold target, final drift <0.002 rad,
speed <0.01 rad/s, non-pan error <0.04 rad, and no faults. These are new demo
checks, not changes to frozen P8 criteria. `telemetry.json` and PNGs stay in
ignored `results/`. PNGs render recorded actual phase-end states after control;
they are visual pose confirmation, not a live viewer/video proof of motion.
