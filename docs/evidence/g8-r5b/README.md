# G8-R5b official Thor run — FAIL, batch stopped after trial 1

The new moving-body protocol was frozen at commit `4a94809053a42e18a9220cf741240a12b30fb436`, SHA-256 `6a97821b2e7fd388a6c1d14800b1807d2ef3a14b9b956ec8e40ca1364f27c3a8`. The fixture and tests were committed at `96a517cda1bd7e4f2c7e0d7fd80a3b4a68c4e171` before the first final Thor run. Historical G8-R5 FAIL PR #60 and its artifacts were not changed or merged.

The authoritative batch directory is `/home/juper007/projects/microduck-connectome-thor/evidence/g8-r5b/20260925T1414Z-v1`. It used official MicroDuck `344925c9f8fa031f85428a305b1e8ec2eaae29c1`, microduck_rl `cb70b792312d559a4da09064d92009079671815f`, robotd/MuJoCo, graph-v2 `c4160c42941163079b6b569d117bf67afcf8b45eaa128c444f7c96c2567593cc`, and the hash-checked frozen P7 walking policy. The precondition was an engineering high-level `robot.move(vx=0.07, vy=0, vyaw=0)` fixture, never a MaleCNS command. All other controller, safety, watchdog and stop transport settings stayed frozen.

Trial `g8-r5b-01-80101` established 0.0410 m precondition trunk displacement, 0.0774 m/s pose-derived handoff speed and 0.0408 m/s immediately before healthy neural stop. Visual looming and LPLC2 reached 1.0; graph-v2 DNp01 escape reached 1.0. The first relevant stop was the healthy decoder → SafetyClamp → Watchdog → official `robot.stop` path. The RPC ACK returned before observed motion satisfied the frozen ≤0.008 m/s confirmation rule (confirmed speed 0.00253 m/s, ACK-to-confirmation 322 ms). No command bound violation or earlier manual/watchdog stop was observed. Official robot.state in this setup had no measured odometry velocity, so MuJoCo trunk x/y displacement over the frozen 100 ms window was the primary motion measure. Exact socket-write timestamps were unavailable; publisher call start and RPC ACK return bound that interval.

**The trial nonetheless FAILS.** During the same fixed 1.2 s neural observation window, the unchanged P8-01 virtual sphere reached the virtual camera position. `render_pixels` raised `virtual camera entered sphere`, causing `SchedulerWorkerError: perception worker failed`. The protocol requires zero scheduler exceptions. The trial summary records `scheduler_exceptions: null` because `scheduler.run` raised before returning its metrics; the events JSONL records the actual exception. The first trial was retained, the batch stopped immediately, and planned trials 2 and 3 were **not started**. The final official simulator shutdown succeeded.

| Immutable Thor artifact | SHA-256 | Bytes | Records |
| --- | --- | ---: | ---: |
| `batch-summary.json` | `a727de369cae8daaaf8e61023c8fa45417647f36f0b50bd30c217549cbbcff2d` | 8,813 | 1 attempted trial |
| `trial-01-80101/summary.json` | `57202212d72471e8a56cb7967a05bdd0fbfce990077f5008e4536ee722fb2264` | 6,253 | 1 summary |
| `trial-01-80101/trace.jsonl` | `2524790bb400481f295b616bca953b90757368e5580ad6cdedd96ff1a3989ed5` | 160,596 | 52 |
| `trial-01-80101/events.jsonl` | `a725eed8df9b7f7fd230b7f82d830c954d84a0fbaec09f4b1f588dbe1c0f306e` | 69,267 | 136 |
| `trial-01-80101/trial.log` | `c6448411128015907b3bb3547c1dc0aa95bfb6f02eb95bd9bd0985fb1aae79cd` | 523 | 1 log |

Trace monotonic timestamps: `1787192841271252`–`1787193860360021` ns; events: `1787191299518107`–`1787193860529604` ns. Both intervals and counts are also in the committed compact summary.

The [machine-readable compact summary](moving-neural-stop-summary-v1.json) preserves the observed timeline and the FAIL classification. Thor Python 3.12 focused suites passed **142 tests**, and the frozen graph-v2 escape regression reproduced the existing 47/97 healthy stop counts for nominal/bounded looming. This does not cancel the official runtime exception.

**Decision: FAIL; do not merge this branch as a recertification PASS.** A new versioned protocol would have to constrain the visual observation window before virtual sphere penetration, then rerun the full affected three-reset batch and obtain a new exact-head review. The current thresholds, graph/controller, raw run, and historical PR #60 must remain intact. G8-R6 and P8-v2 remain unstarted.
