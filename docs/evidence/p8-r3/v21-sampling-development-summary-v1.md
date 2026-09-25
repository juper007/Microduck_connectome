# P8-R3 V2.1 temporal sampling comparison — PASS, select 10 Hz

The complete 54-case raw record is [`v21-sampling-development-raw-v1.json`](v21-sampling-development-raw-v1.json), 1,391,745 bytes, SHA256 `e00b89ae128e02438b2984426a1d65b06b69521cbe9e1dbfc77d6091b160178a`. The source was frozen at `fb7c1fae0c8699e552deb09fe6e1234c3cc61e15` before running development seeds 885401–885403. The same fractional RGB renderer/detector, A log-area estimator, graph-v2, neural model, decoder threshold 0.5, 0.25 m virtual boundary, scenarios, controls, and 50 Hz neural update were used at every rate. Only scheduled RGB cadence changed; at 20 Hz a 50 ms frame is processed on the next 20 ms neural tick when needed, and the raw trace records both frame and processing timestamps.

| RGB cadence | Approaches at 65×33 | Approaches at 129×65 | Static/receding stops | Max paired first looming/DN difference | Peak LPLC2 ratio | Minimum first-stop margin | Gate |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 10 Hz | 3/3 preboundary | 3/3 preboundary | 0/12 | 0 ms | 1.0 | 0.0678 m | PASS |
| 20 Hz | 3/3 | 3/3 | 0/12 | 0 ms | 1.0 | 0.0758 m | PASS |
| 25 Hz | 3/3 | 3/3 | 0/12 | 0 ms | 1.0 | 0.0798 m | PASS |

All neural steps were runtime healthy. At 10 Hz, first positive looming for seeds 885401/402/403 occurred at 2.1/2.7/3.1 s and first DNp01 ≥0.5 at 2.16/2.76/3.16 s, identically at both resolutions. At 20 Hz those times were 2.05/2.65/3.05 s and 2.12/2.72/3.12 s. At 25 Hz they were 2.04/2.64/3.04 s and 2.10/2.70/3.10 s. All first stops matched first DN threshold time and had positive boundary margin.

The prospectively frozen rule chooses the **lowest passing cadence: 10 Hz**. The faster cadences do not change this selection. Both representations' positive looming values were clamped at 1.0 in the earlier comparison, and this cadence screen still cannot establish unsaturated amplitude invariance or official moving-body success. Official Thor development recertification remains required and must freeze its source, selected 10 Hz scheduling, and fresh seeds before execution.
