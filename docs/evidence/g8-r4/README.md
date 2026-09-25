# G8-R4 graph-v2 DN/escape recertification

The fixture and case order were committed at
`4e6f966d8693ecdd0912618a9c70a9e698708223` before this result was
observed. The graph-v2 SHA256 is
`c4160c42941163079b6b569d117bf67afcf8b45eaa128c444f7c96c2567593cc`.
The P3/P4/P5 model, sensory mapping, DN readout, EscapeDecoder threshold
**0.5**, SafetyClamp limits, and Watchdog TTL were unchanged.

The frozen `config/g8_r4_recert_v1.json` applies a 10-step neutral warmup,
then 100 steps at 20 ms for each of three fresh perception-frame cases.
`target_area=0.4` and `confidence=0.9` are shared; only looming differs.
Every step traverses SensoryMapper → actual graph-v2 SparseNeuralRuntime →
DNActivityAggregator → EscapeDecoder → SafetyClamp → ControllerWatchdog.

| Case | LPLC2 spikes | DNp01 spikes | Max escape readout | Healthy neural stop steps | First stop step | Post-safety/watchdog stop steps |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| target only, looming 0 | 0 | 0 | 0 | 0 | — | 0 |
| nominal looming 0.8 | 9,250 | 98 | 0.6 | 47 | 16 | 47 |
| bounded looming 1.0 | 18,500 | 198 | 1.0 | 97 | 13 | 97 |

Both looming cases crossed the **unchanged** 0.5 neural escape threshold
while the runtime was healthy, and their decoder stop survived SafetyClamp and
a healthy Watchdog. The target-only control did not assert neural stop. All
watchdog fault counts were zero. The report retains every step and the exact
DN, sensory, decoder, safety, and watchdog config hashes.

`neural-escape-v1.json` SHA256:
`8b8c369b7d4ebdb3e2db04fed023e13f05ba15cb2fbc465c69280ac32e5b2199`.
The 62 directly affected P3/P4/P5 tests passed on Thor Python 3.12.

**Limit:** Nominal stop was intermittent (47/100 active steps). This fixture
shows internal neural-path feasibility, not official simulator stopping before
a safety boundary, a success rate, or sensor-loss behavior. G8-R5/P7
recertification and a new preregistered P8 batch remain mandatory. No threshold
or controller parameter was tuned after these results.
