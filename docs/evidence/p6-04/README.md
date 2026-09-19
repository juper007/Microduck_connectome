# P6-04 scheduler evidence

## Result

The final P6-04 source commit `61ab626c0b77b4c58151611e13eadb7c181b4ae2`
ran for 30.002 seconds on Thor (`jetsonthor01`) with the pinned official
`robotd` and headless MuJoCo body. The scheduler exercised the deterministic
PerceptionPipeline, SensoryMapper, sparse MaleCNS runtime, DN aggregator,
steering/escape decoders, SafetyClamp, ControllerWatchdog, sealed motion
adapter, and official robotd high-level IPC boundary.

The measured rates were 25.0315 Hz perception and 50.0296 Hz neural,
watchdog/control, and robot publish. Watchdog period p50/p95/p99 was
19.9996/20.0114/20.0857 ms and p95 absolute jitter was 0.0273 ms. There were
no dropped updates, stale events, missed scheduler deadlines, scheduler
exceptions, or additional robotd missed ticks. `robotd` retained its official
50 Hz loop and motor ownership.

Machine-readable evidence is `scheduler-runtime-v1.json`.

## Runtime identity

- Microduck_connectome source: `61ab626c0b77b4c58151611e13eadb7c181b4ae2`
- MicroDuck: `344925c9f8fa031f85428a305b1e8ec2eaae29c1`
- microduck_rl: `cb70b792312d559a4da09064d92009079671815f`
- graph: `340f6a3180026f6c61f19ebc016ae8610ec9f4a07af2af589e4d6d89e5b31f70`
- Python: 3.12.3
- frozen yaw sign: `-1`
- frozen stop transport: `robot_stop`

The pinned 570-node pathway artifact contains 275 of the 460 configured
sensory IDs and two of the four configured DN IDs. The runtime fixture does
not invent missing neurons or edges: absent inputs/readouts remain neutral.
This is explicit coverage metadata, not a change to biological provenance or
the frozen graph. It is a residual graph-coverage limitation for later
end-to-end behavior evidence, not a scheduler cadence exception.

## Tests

On Thor, Python 3.12 ran the scheduler tests plus the directly relevant P4,
P5, IPC, adapter, watchdog, safety, neural runtime, sensory mapping, DN, and
decoder regressions: `197 passed in 2.70s`.

## Retained raw artifacts

Artifacts remain on Thor at
`/home/juper007/projects/microduck-connectome-thor/evidence/p6-04/20260919T1333Z`.

| Artifact | Bytes | SHA256 |
|---|---:|---|
| `scheduler-runtime-raw.json` | 3126 | `2502aa4ffa459935b35d6a1ee77c30e0513146b84180bc5ca4ed9b2f2ef6f360` |
| `fixture-stdout.log` | 2968 | `32e2377244b8f8ab69d5d3794f11dd640dc6f714531837bd7d7d5ac9ea20232a` |
| `python312-tests.log` | 260 | `f3ef58e5f6aefdef89fef6455111d14da2e2b26dae8f488a51ca7ed5886a7d62` |
| official MuJoCo body log | retained in `p604-state`, size varies until shutdown | `311181a118abe631f136b349972056a2240e1ff09de0071ba03de8144260919b` at evidence capture |
| official robotd log | retained in `p604-state`, size varies until shutdown | `ea49f4cd78e637e132d77c02d313d2f00bf43b560093b6b78a5cbf7188b42b42` at evidence capture |

The raw JSON and test logs contain no credentials or tokens. Simulator logs
were hashed at evidence capture; their processes were still active, so those
two hashes are snapshots rather than immutable final hashes.
