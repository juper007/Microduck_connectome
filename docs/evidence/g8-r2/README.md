# G8-R2 actual graph-v2 neural runtime recertification

The immutable graph-v2 artifact `c4160c42941163079b6b569d117bf67afcf8b45eaa128c444f7c96c2567593cc`
was loaded through `ConnectomeGraph.from_cache` and run with the unchanged
`config/neural_model_v1.json` on Thor, Linux Python 3.12.3 CPU. Workload code
commit: `6e05edd3c04109b976012921a532343b6eb35a66`.

This is the actual 1,098-node / 72,782-edge MaleCNS-derived graph, not the
historical 570-node matched-scale synthetic fixture. The graph bytes were
checked against `data/manifests/controller-graph-v2.json` before execution.

| Check | Result |
| --- | ---: |
| Fixed 200-step replay | exact equality |
| Zero-input soak | 30,000 steps, 600 s neural time, healthy, no nonfinite state |
| Bounded-input soak | 30,000 steps, 600 s neural time, healthy, no nonfinite state |
| Maximum bounded state magnitude | 0.75 |
| Measured steps after warmup | 500 after 100 |
| Step latency p50 / p95 / p99 | 2.672353 / 2.995910 / 4.015942 ms |
| Frozen preferred p95 target | ≤18 ms, met |
| RSS baseline / after graph construction | 21,762,048 / 101,236,736 bytes |
| RSS graph delta / process peak | 79,474,688 / 166,977,536 bytes |

The full result is `runtime-v2.json`, SHA256
`12a88310754e95f30c36e92e8e4134bba915d6aed6f034aca2793f7dc09b328a`.
The deterministic bounded schedule injects into one pinned LC10a-left ID and
one pinned LPLC2-left ID every tenth 20 ms step; the zero run injects nothing.
The report records exact body IDs, model/sensory config hashes, graph identity,
environment, memory method, and all counts.

Reproduce on Thor with the pinned artifact named by the graph-v2 manifest:

```sh
python scripts/recertify_graph_v2_runtime.py --output results/g8-r2-repeat.json
```

This recertifies P3 numerical execution and timing for graph v2. It does not
demonstrate DNp01 behavioral sufficiency, closed-loop robot stop, P6 safety,
or P7 graph-v2 steering. The historical graph-v1 G3/G7 evidence remains intact.
