# P6-01 runtime evidence — BLOCKED

Pinned upstream source was inspected at the exact commits in `config/versions.json`.

The pinned official `microduck/scripts/duck-sim` documents the supported local path:

```sh
scripts/duck-sim
scripts/duck-sim ctl health
scripts/duck-sim down
```

The same pinned script states that the simulator runs the real `robotd` binary with the same policies, 50 Hz loop and IPC, substituting simulated I/O at the body seam.

## Execution result

This task is **BLOCKED**, not PASS.

The current execution environment lacks:

- the pinned `microduck` checkout;
- the pinned `microduck_rl` checkout and its `.venv`;
- Rust `cargo` / `rustc`;
- Python `mujoco`;
- Python `onnxruntime`.

A direct Git fetch probe also failed because this container cannot resolve `github.com`.

Therefore the official simulator was not launched and `scripts/duck-sim ctl health` was not run. No simulator or robotd health result is inferred from unit tests or source inspection.

`scripts/p6_sim_preflight.py` is provided to make the missing prerequisites explicit on a Linux host that has the pinned repositories available.

P6-01 acceptance requires an actual simulator launch and real robotd health response, so P6-02 and later tasks must not proceed under the requested sequential workflow until this block is resolved.
