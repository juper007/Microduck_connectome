# G8-R5d frozen final evidence — three trial transport and motion checks

The final three-trial batch on Thor reported PASS under frozen source `61ec433419dd391bcad43b46d9cf6689f89d8163` and protocol SHA256 `ec52851ace78eb1f0e3a1227033e5032cc6a35d60c2724610e30d03550da4f54`. This is implementation evidence for independent exact-head review, not the independent gate decision. The immutable raw directory is `/home/juper007/projects/microduck-connectome-thor/evidence/g8-r5d/final-61ec433-20260925-1/`. `batch-summary.json` is 92,649 bytes, SHA256 `a7615d3f59dc7b6e69ca5c9c90500d52dcaa101b10f87ffb6de51cc00188db8b`, result PASS with all three planned fresh-reset seeds started and passed. No trial was replaced. This batch follows the separate development probe in [development-probes.md](development-probes.md).

Frozen values: moving pose speed >=0.015 m/s, fresh pre-stop applied vx >=0.04 m/s, stopped pose speed <=0.008 m/s sustained for 200 ms, 50 Hz watchdog/control, official `robot.stop` transport, 500 ms robotd deadman, and maximum acknowledged stop-refresh gap 100 ms. The source and protocol were committed before this final batch. No graph, neural, sensory, decoder, SafetyClamp, Watchdog, adapter, scheduler, or robotd production code/config changed from the fetched `origin/main` base `c7f23ac21da9d089d663e2c216cc5a07cb834b6c`.

| Trial / seed | Fresh pre-stop pose speed (m/s) | Pre-stop applied vx (m/s) | First source | First stop ACK (monotonic ns) | ACK count | Max ACK gap (ms) | Stopped confirmed (monotonic ns) |
|---|---:|---:|---|---:|---:|---:|---:|
| 01 / 80101 | 0.0880322699632 | 0.0699999998938 | healthy neural escape | 1801034088328203 | 37 | 20.048103 | 1801034819992067 |
| 02 / 80111 | 0.1230368259515 | 0.0699999997406 | healthy neural escape | 1801048509457824 | 34 | 20.420140 | 1801049184294433 |
| 03 / 80121 | 0.1347056871732 | 0.0699999998340 | healthy neural escape | 1801062925974842 | 35 | 20.102759 | 1801063615991704 |

Across the batch, 106 official `robot.stop` requests were acknowledged. The largest ACK gap was 20.420140 ms, below the frozen 100 ms bound and 500 ms deadman timeout. All three trials recorded applied-vx decline, actual pose-derived sustained cessation, an actual `MOTION_STOPPED` and `COMPLETE` transition, no deadman limiter before stopped confirmation, no robot-facing `robot.move` after the first neural stop, no sphere penetration, zero scheduler exceptions, and zero safety-limit violations. Watchdog/control continued through settling while visual/neural production ended after the first ACK. Later stale-safe watchdog refreshes are expected under the frozen production Watchdog semantics; the first relevant stop was healthy graph-v2 neural escape in each trial. The bounded positive `robot.move` before neural observation was an engineering test precondition, not a MaleCNS behavior claim.

## Raw lineage audit and frozen summary limitation

The frozen trial script computes `peak_looming` and `peak_lplc2_stimulus` from the transport telemetry `records`. Exact-neutral pre-stop outputs are suppressed for fixture isolation and are therefore absent from those telemetry records. Trial 02's frozen `summary.json` consequently reports both peaks as zero because its first transported stop frame has zero current visual input. **The original frozen summary is retained unchanged.** Its zero peak fields do not describe the complete pre-stop neural stream.

An independent read of each immutable `neural-ledger.jsonl`, filtering `result_none == false`, gives `max(looming) = 1`, `max(max(stimulus_channels.lplc2_left, stimulus_channels.lplc2_right)) = 1`, and peak DNp01 escape `0.6` in every trial. First positive visual runtime steps are 3, 4, 6, respectively; DNp01 threshold steps are 14, 14, 12. The frozen `bounded_neural_lineage` check uses this ledger, requires complete consecutive healthy graph-v2 runtime steps from positive looming/LPLC2 to the first healthy stop, and passed in all three trials. This supports bounded temporal lineage, including possible LC10a co-input, without claiming LPLC2 as a unique biological cause. Review should inspect the retained raw ledgers and hashes below, rather than treating the telemetry-derived peak fields as complete.

## Artifact integrity

All files below are in the immutable Thor final directory under `trial-XX-SEED/`. Each trial's original `summary.json` also records artifact byte counts, record counts, and monotonic start/end timestamps for its event, trace, and ledger streams.

| Trial | Artifact | Bytes | Records | SHA256 |
|---|---|---:|---:|---|
| 01 | summary.json | 25,226 | 1 | `7e4488dbedbc9d0a9b97d3bc814eb662a7977335e59fd3ac49b1d4d81da858f3` |
| 01 | events.jsonl | 146,683 | 282 | `d87eafa49587f40979f639afabeb4472b318ac6ba432b7ac9730c03e00921105` |
| 01 | trace.jsonl | 3,141 | 1 | `49668bf62ef3867c2e31ef456e671eb5244ecd66005c19431df21c3695714a52` |
| 01 | neural-ledger.jsonl | 11,716 | 17 | `020481c391b6743ab372a13f16c31c0845db403fde1eb6cb0438b5cb2b81cea4` |
| 02 | summary.json | 24,395 | 1 | `edeac908cb887d3f06ceb4968f0144dc40a416312e71ee1de696c309cb8bc0cd` |
| 02 | events.jsonl | 136,207 | 265 | `6ea198479e8d4ee14cbed7f01d19a52bc3c454bfab80d5cea26bfad0085838f7` |
| 02 | trace.jsonl | 3,096 | 1 | `3bfe96146393ae65360f9d689f55c7d0986a39099248cf111075230dc7915355` |
| 02 | neural-ledger.jsonl | 9,582 | 14 | `2c12c0d42534e90c8030e8905a8ee46153bcffc8ef3becb7881eb92a533ff600` |
| 03 | summary.json | 24,480 | 1 | `d9b14a186f7f4e599e492028cb3172c7a292364ff6334f812251dcb70154ed0a` |
| 03 | events.jsonl | 139,306 | 269 | `74512ddeac7e1ad6f6ea97e70bdd1c9a4afe6a45727f2907cc9387a692ae32d0` |
| 03 | trace.jsonl | 3,141 | 1 | `5092182d03a8edf87b2b977b3043322589b141040bfb0377b0376612058427f3` |
| 03 | neural-ledger.jsonl | 10,284 | 15 | `a47f97e3e7f7e7997f68faa3c495a66c2e4e2e0e9b2471aebee50e051901de5c` |

Python 3.12 on Thor: `PYTHONPATH=. python -m pytest` for G8-R5d, Watchdog, motion adapter, robotd client, scheduler, and looming suites: **158 passed**. The exact final source head and this evidence note require independent reviewer assessment before any PASS gate or merge.
