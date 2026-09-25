# P8-R3 V2.2 official Thor development — 0/3 FAIL

The frozen official V2.2 batch ran on Thor from source `0d1a178767cf4eec5ba5e53b464e4658d4fbfca9`, protocol SHA256 `756ad7a6f1064c237f766af018bc95fbe344e877d4d008e03bfea8db0b1a640a`, with fresh development seeds **885521–885523**. All three resets were armed and completed. The frozen composite result is **0/3 FAIL**, even though each trial's narrower preboundary neural screen was PASS. These runs are development evidence only, not P8-02 final trials.

| Seed | Armed neural ledger rows / valid frame-aged updates | Initial `input_none/result_none` ticks | Max valid neural frame age / RGB frame gap (ms) | First neural stop / stop request margin to 0.25 m (m) | Stop ACK refreshes / maximum gap (ms) | Frozen result |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 885521 | 45 / 41 | 4 | 60.35 / 69.76 | 0.27098 / 0.26944 | 37 / 23.84 | FAIL |
| 885522 | 44 / 41 | 3 | 63.69 / 60.00 | 0.15855 / 0.15687 | 37 / 24.82 | FAIL |
| 885523 | 41 / 39 | 2 | 64.05 / 60.00 | 0.07882 / 0.07647 | 35 / 24.93 | FAIL |

The single false frozen check in **each** trial is `visual_age_within_ttl`. The reported maximum ages of 60.35/63.69/64.05 ms are maxima over **only the 41/41/39 valid neural updates**. The complete armed neural ledgers also contain **4/3/2** early scheduler ticks with `input_none=true` and `result_none=true`, no perception timestamp, and no graph update. Those ticks cannot be assigned a frame age; a maximum calculated after excluding them cannot prove continuous fresh neural input. The frozen check requires a valid ≤100 ms age for **every** ledger row, so it correctly evaluates false. The first frame was validated and passed directly to `chain.neural` for watchdog priming before scheduler threads began, but it was not placed in the scheduler perception cache. Initial scheduler neural ticks therefore received `None` until the next published RGB frame. They are armed post-priming gaps, not exogenous pre-arm invalid trials. Keep every run in the denominator and do not relabel this batch as 3/3 PASS.

The remaining evidence is positive but does not override that failure: each body was moving with fresh positive applied vx before the healthy graph-v2 DNp01 ≥0.5 and EscapeDecoder stop; the first stop and `robot.stop` request had strictly positive boundary margins. Each stop received an ACK and production refreshes through pose-derived stopped confirmation, with no fault/deadman cessation, no post-latch positive move, **zero safety-limit violations**, and **zero scheduler exceptions**. All other frozen trial checks are true. Final `duck-sim down` exited 0. Seed 885523's stopped-confirmation margin was negative (−0.05720 m), while its trigger and stop request were preboundary; this is reported separately and does not change the specific failed check.

The retained [batch summary](official-v22-v1-batch-summary.json) is **89,376 bytes**, SHA256 `12d6b52cc612285a1a5439880b46912dc7f838ff184bb92030462e92bf6e1974`. The [raw manifest](official-v22-v1-raw-manifest.json) is **6,161 bytes**, SHA256 `66500298b36c1ded6d5c341117a009f36deeb17bb8b899ba5f0f156f7f6c64ca`. An independent local audit of the exact Thor archive verified **all 32 manifest entries** against byte length, SHA256, and line/record count: **678,442 bytes** and **5,471 recorded lines** in total, with no mismatches. The immutable remote raw root is:

`/home/juper007/projects/microduck-connectome-thor/evidence/p8-r3-v22/official-v1-885521-523/`

Retain V2.2 as a failed official batch. Any startup-handoff repair needs a separately frozen protocol and unused seeds; the completed V2.2 runs cannot be selectively replaced.
