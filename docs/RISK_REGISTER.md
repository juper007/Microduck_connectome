# Risk Register

| ID | Risk | Probability | Impact | Mitigation | Gate |
|---|---|---:|---:|---|---|
| R1 | Static connectome does not specify dynamics | High | High | Explicit simple dynamics; treat as engineering model, compare baselines | G3 |
| R2 | Selected neuron role is oversimplified | High | Medium | Evidence cards + confidence rating + reviewer | G2 |
| R3 | MaleCNS annotation names differ from prior literature datasets | Medium | High | Resolve exact v1.0 body IDs before coding mapping | G2 |
| R4 | Full graph runtime misses real-time deadline | Medium | High | Profile sparse runtime; multi-rate async architecture | G3/G6 |
| R5 | Network becomes unstable/explosive | Medium | High | bounded state, decay, thresholds, soak tests | G3 |
| R6 | Sensory mapping is arbitrary enough to dominate result | High | High | compare multiple encoders; mark engineered mapping; ablate | G9 |
| R7 | Decoder dominates result rather than connectome | High | High | use matched/simple readouts across baselines | G9 |
| R8 | Shuffled baseline is unfair | Medium | High | degree-preserving shuffle and matched statistics where feasible | G9 |
| R9 | Robot oscillates due to noisy neural output | Medium | High | smoothing, hysteresis, slew limits | G5 |
| R10 | Stale output causes continued movement | Medium | Critical | timestamps + watchdog + TTL | G5 |
| R11 | Direct motor integration bypasses safety | Low | Critical | architectural prohibition; supported robotd API only | G5/G10 |
| R12 | Simulator success fails on hardware | High | Medium | low-speed promotion, restrained tests, separate hardware profile | G10 |
| R13 | Experiment becomes a demo without falsifiable hypothesis | Medium | High | pre-register metrics/thresholds and baselines | G9 |
| R14 | Results are not reproducible | Medium | High | pin versions, seed/config logging, CI | G0/G9 |
| R15 | Dataset/network scale creates storage burden | Medium | Medium | use neuPrint/cache/subgraphs before bulk synapse tables | G1 |
| R16 | Biological advantage is zero or negative | Medium | Low scientifically | treat as valid result; publish negative finding | G9 |

## P0 risks

These block hardware autonomous motion:

- safety watchdog not passing,
- direct servo bypass,
- unexplained left/right inversion,
- non-deterministic safety behavior,
- stale commands surviving controller failure,
- no human E-stop.
