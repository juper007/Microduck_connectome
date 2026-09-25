# P8-R3 V2.1 official Thor development — FAIL

Frozen source `31ff99f03ed7f89e1d70f30e3889cd31e710c56c` and
`config/p8_r3_v21_official_v1.json` were run on Thor Python 3.12 with the
pinned duck-sim, robotd, MuJoCo, walking policy, graph-v2, and fresh
development seeds 885421–885423. This batch is not P8-02 final evidence.
All three planned resets were armed and completed with a trial summary;
the frozen composite is **0/3 FAIL**. Simulator final `duck-sim down` exited 0.

| Seed | Moving precondition | Max RGB frame gap | First positive looming | First stop source | Healthy neural stop | Safety violations | Outcome |
| --- | --- | ---: | --- | --- | --- | ---: | --- |
| 885421 | confirmed | 109.88 ms | none | `safe_stop`, `stale_neural` | none | 0 | FAIL |
| 885422 | confirmed | 110.03 ms | none | `safe_stop`, `stale_neural` | none | 0 | FAIL |
| 885423 | confirmed | 110.61 ms | none | `safe_stop`, `stale_neural` | none | 0 | FAIL |

The selected 10 Hz visual period is exactly the frozen 100 ms perception TTL.
Measured official frame gaps exceeded 100 ms. Each trial produced only two
visual frames, no positive looming or LPLC2, and DNp01 peak 0. The watchdog
issued a stale-neural fault stop before any healthy neural escape. The motion
arbiter then rejected a later non-stop watchdog output, raising
`SchedulerWorkerError: watchdog worker failed: non-stop watchdog output after
stop latch`. There was no neural `robot.stop` ACK and no pose-derived stopped
confirmation. Safe fault-stop ACKs cannot be counted as neural success. The
official result does not establish V2.1 moving-body looming or stop
persistence. Zero safety-limit violations were recorded, but scheduler
exceptions are **not** zero.

The complete [batch summary](official-v21-v1-batch-summary.json) has SHA256
`b0a2b72e4b798cfea8719f863d8eefae84b834851dab3622ec5d590d72df82db`.
The [raw manifest](official-v21-v1-raw-manifest.json) has SHA256
`7ad1497762a6f081a32fdb37bc9d7a11797eee17e32ad92f57b31cc4ac7d89dd`.
All 29 indexed raw files were independently rehashed on Thor against their
recorded byte lengths, line counts, and SHA256 values. The immutable remote
raw root is:

`/home/juper007/projects/microduck-connectome-thor/evidence/p8-r3-v21/official-v1-885421-423/`

The V2.1 internal and sampling PASS results remain development-only and are
preserved. A separately frozen remediation must use new development seeds,
address visual cadence versus freshness and persistent fault-stop arbitration,
then repeat the full official three-reset matrix. Do not reuse these seeds,
relax the 0.5 decoder threshold, 0.25 m boundary, graph weights, or safety TTL.
