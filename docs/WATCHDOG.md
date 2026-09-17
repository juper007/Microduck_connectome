# Controller Watchdog

Task: **P5-05**

The watchdog stores the latest validated neural readout and post-safety behavior intent, then emits a current internal intent on every watchdog tick.

Frozen freshness limits:

- neural readout TTL: 100 ms;
- behavior intent TTL: 100 ms.

Exactly 100 ms is fresh. At 100 ms + 1 ns, the corresponding source is stale.

Any missing, invalid, future-dated, stale, nonmonotonic, runtime-unhealthy, or decoder-dead state produces a new current `stop=true` intent with zero motion and a machine-readable reason. Repeated watchdog ticks do not update source timestamps, so stale controller data cannot remain alive indefinitely.

## Process-crash boundary evidence

P5-05 models the process-supervisor boundary with `mark_decoder_crashed(nonzero_returncode)`. The deterministic test injects a nonzero process-exit code and proves that the next watchdog tick is `decoder_crash -> stop=true -> zero motion`. This validates the required process-crash failure semantics without depending on simulator or OS-specific process orchestration. Recovery explicitly clears cached samples and requires new healthy neural and behavior data.

No robot-facing stop transport is selected in this task.
