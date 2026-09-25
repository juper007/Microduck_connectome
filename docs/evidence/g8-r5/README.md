# G8-R5 official Thor integration recertification — FAIL

The acceptance rule was committed in `docs/tasks/G8-R5.md` at `597fec2bd6731621a178a5ecbb175c6162e3a374`, before either simulator result. The graph-v2 controller, P3–P6 configs, P7 steering calibration, safety limits, TTL and `stop_transport=robot_stop` were not changed. This is a short recertification smoke, not a P8 final trial.

The first run used the frozen P8-01 approaching virtual-visual scenario, seed `80101`, on Thor official MicroDuck `344925c9f8fa031f85428a305b1e8ec2eaae29c1`, microduck_rl `cb70b792312d559a4da09064d92009079671815f`, robotd and MuJoCo. It produced 13 healthy neural stops and 14 total `robot.stop` records, but no preceding robot motion. Its raw and summary are retained under `/home/juper007/projects/microduck-connectome-thor/evidence/g8-r5/official-integration-v1.*` (JSONL SHA-256 `0d40fce57b1925a354a01cb7b42aab086a5b74ed7e9f5dbb4fd2875d6cc14d66`; summary SHA-256 `23ae5f18bdb415ea355b1a75f285f368882ee9802623afe7457bc274aa52e935`). **Do not use its quaternion field**: it was an instrumentation placeholder.

Commit `d53c605a5040e2fe79c8becf0caa31eef7a48609` removed that placeholder and recorded the actual official MuJoCo trunk x/y/heading/z. The same frozen scenario and seed were replayed once in a fresh official simulator process. Corrected authoritative raw JSONL: `/home/juper007/projects/microduck-connectome-thor/evidence/g8-r5/official-integration-v2.jsonl`, SHA-256 `e53144a621d616a4492da0c04add6d8704e668fb3e7efec263e79b63898c99b8`, 200 records. Summary: `official-integration-v2.json`, SHA-256 `c55919d18a257613133f1fbb14cff75eee596633d06f335b12fe8c1e64709f30`.

| Corrected run | Observation |
| --- | ---: |
| Healthy neural stop → official `robot.stop` | 10 records; first sequence 189 |
| Total official `robot.stop` | 11, including one scheduler-shutdown stop |
| Peak visual looming / DN escape | 1.0 / 1.0 |
| Motion before first neural stop | **No**; actual robot.state velocity remained zero |
| Motion after neural stop | Zero |
| Bounded commands | Yes; no safety-limit violation |
| Scheduler exceptions / missed deadlines | 0 / 0 |
| Official robotd health before/after | Healthy / healthy |
| Telemetry observer errors | 0 |

The healthy neural causal segment is reconstructible in raw records: RGB perception → looming → LPLC2 stimulus → graph-v2 runtime → DNp01 escape readout ≥ frozen 0.5 threshold → decoder and post-safety stop → healthy watchdog → official `robot.stop` response → post-command official robot.state and MuJoCo pose. The 11th stop is scheduler shutdown and is excluded from the neural count.

**Decision: FAIL under the preregistered G8-R5 rule.** This trial never had actual pre-stop motion. A zero-velocity state after `robot.stop` cannot establish that the neural stop halted moving MuJoCo motion. The frozen steering decoder emits `vx=0` for this centered visual scenario. This is an evidence/fixture gap, not evidence that SafetyClamp or robotd failed. Any new motion-producing recertification fixture needs a separately versioned protocol and exact-head review; P8 final batches and G8 review must wait. The virtual obstacle has no collision geom, and no boundary-before-stop success is claimed.
