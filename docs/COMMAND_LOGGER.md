# Phase-5 Command Logger

Task: **P5-06**

`CommandTrace` stores a detached, JSON-safe record for every final Phase-5 watchdog output. Each record preserves:

- top-level monotonic timestamp and sequence;
- neural readout summary when available;
- pre-safety behavior intent;
- post-safety behavior intent;
- final watchdog intent;
- final stop state and runtime health;
- watchdog state and decoder liveness;
- clamp-applied flag and clamp reasons;
- stale/fault reason;
- controller source;
- version/config identity supplied by the caller.

The logger permits null neural/pre/post fields for failure cases such as decoder process exit where those artifacts do not exist. The required watchdog result remains fully validated, and a `safe_stop` record must contain a reason plus zero-motion stop intent.

`to_jsonl()` uses deterministic canonical JSON serialization with NaN/Inf disabled. Stored data and `records()` results are detached copies. Trace timestamps and sequences must increase strictly.

Config identity rejects obvious credential field names and local filesystem paths so evidence metadata does not casually leak secrets or developer-specific paths.

The final integration fixture exercises P5-01 through P5-06 for nominal steering, escape stop, invalid neural output, stale-source shutdown, and decoder process-exit boundary behavior. The steering integration fixture uses a **test-only +1 yaw sign**; the committed production steering config remains uncalibrated (`null`) until the official simulator sign fixture in Phase 6.

This module records internal intent evidence only and performs no robot-facing transport.
