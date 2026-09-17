# Neural Runtime Performance and Memory Profile

Task: **P3-06 / G3 remediation**

The Phase 3 performance harness measures `SparseNeuralRuntime.step()` wall-clock latency with `time.perf_counter_ns()` after a warmup period. It reports nearest-rank p50, p95 and p99 latency plus min/max.

## Workload

The benchmark workload is deterministic and **synthetic matched-scale**, not an actual MaleCNS topology:

- 570 neurons;
- 21,142 unique directed non-self edges;
- normalized edge weight 0.01;
- graph generation rule `round_robin_offset_unique_directed_nonself-v1`;
- 100 warmup steps;
- 500 measured steps;
- every tenth warmup step injects 0.5 into body 1;
- every tenth measured step injects 0.5 into body 1 and 0.25 into body 200.

The executable workload definition is produced by
`microduck_connectome.workload_identity.performance_workload_definition()`.
Its SHA-256 is computed from canonical JSON at runtime; it is not a manually copied constant.

Current v2 workload SHA256:

`9c60aacf6c2f024fca2ea3de1961010c9e1dad4990aae8b421c4c3d9da69fd19`

Generated graph content SHA256 is `b91d9ddff6c68bf507b98b87abdf3e122b379cbb86c21e27aaa13d5fdae520f7` and is embedded in the workload definition. Changing graph content or another workload parameter changes the workload hash and is covered by regression tests.

The scale matches the selected G1 graph evidence (570 nodes / 21,142 edges) only for runtime-cost characterization. It does not preserve G1 degree distribution or topology and must not be presented as biological or actual MaleCNS-topology performance.

## Latency gate

The frozen P-1.1 preferred target is p95 neural step latency <=18 ms. The benchmark reports the target and whether the supported-environment run meets it. The threshold is not adjusted after seeing results.

## Memory measurement

G3 also requires a memory benchmark. On the supported Linux/Python 3.12 CI environment the harness reads `/proc/self/status`:

- `VmRSS` before graph/runtime construction -> `baseline_rss_bytes`;
- `VmRSS` after graph + runtime construction -> `runtime_constructed_rss_bytes`;
- `VmRSS` after the measured profile -> `post_profile_rss_bytes`;
- `VmHWM` -> `peak_rss_bytes`;
- constructed minus baseline RSS -> `runtime_rss_delta_bytes`.

Measurement method identity is `linux-proc-status-vmrss-vmhwm`.

RSS is environment-dependent evidence. There is deliberately no newly invented memory pass threshold; G3 requires a reproducible latency/memory benchmark to exist.

## Evidence

Historical `performance-v1.json` and `performance-v2.json` are retained. G3 remediation's current graph-bound result is `performance-v3.json`, with latency, memory, executable workload definition/hash, generated-graph content hash, config hash, code/source SHA, runner and workflow identity.

Only supported Python 3.12 CI measurements are acceptance evidence.
