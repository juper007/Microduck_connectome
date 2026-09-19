# P6-02 Thor runtime evidence

## Result

The P6-02 read-only adapter connected to the real `robotd` process running against the
official MuJoCo body on Thor, completed the official `hello` handshake, read
`robot.health`, subscribed to and received a fresh `robot.state`, disconnected locally,
rejected a call while disconnected, reconnected as a new connection generation, and read
fresh health and state again. No motion request was sent. The daemon ran with
`--no-policy`; its log records `driving=false`.

Machine-readable evidence: `thor-runtime-v1.json`.

## Runtime authority

- Execution target: `Thor` (`jetsonthor01`, Linux aarch64)
- MicroDuck: `344925c9f8fa031f85428a305b1e8ec2eaae29c1`
- microduck_rl: `cb70b792312d559a4da09064d92009079671815f`
- MuJoCo body: `127.0.0.1:17802`
- robotd socket: `/tmp/p602-runtime-final/robotd.sock`
- Evidence window: `2026-09-19T01:00:24.279105Z` through
  `2026-09-19T01:00:24.306682Z`

## Authoritative upstream protocol facts

All facts below were inspected at the pinned MicroDuck commit above.

- `duck-ipc-proto/src/lib.rs`: JSON-RPC version `2.0`, API version `31`, default robot
  socket `/run/robotd.sock`, methods `hello`, `robot.health`, `robot.subscribe`, and
  server notification `robot.state`.
- `duck-ipc-proto/src/lib.rs`: requests contain `jsonrpc`, optional `id`, `method`, and
  `params`; calls have an ID, while notifications omit it. Parameterless calls send `{}`.
- `robotd/src/main.rs`: the Unix stream is newline-delimited JSON, has a 64 KiB line
  limit, and flushes each response. `robot.subscribe` acknowledges with
  `SubscribeResult`, then pushes `robot.state` notifications.
- `robotctl/src/main.rs`: the official blocking client connects with a Unix stream,
  appends a newline to each JSON request, starts request IDs at one, matches responses by
  ID, and performs `hello` as its liveness handshake.

The Python adapter mirrors those wire facts and keeps its request ID counter increasing
across reconnects. It discards responses with nonmatching IDs and clears all buffered
bytes on disconnect, so an old response cannot become the answer on a new generation.

## Commands and outcomes

Focused unit test on Thor:

```text
cd /tmp/p602-code && python3 -m pytest tests/test_robotd_client.py -q
.............                                                            [100%]
13 passed in 0.02s
```

The final pushed implementation was also checked out in `/tmp/p602-full` for the P6
client/evidence tests plus P4/P5 safety regressions. The exact-head result is recorded in
the PR validation summary.

Real runtime probe:

```text
PYTHONPATH=/tmp/p602-code python3 /tmp/p602-code/probe_robotd_readonly.py \
  --socket /tmp/p602-runtime-final/robotd.sock \
  --microduck /home/juper007/projects/microduck-connectome-thor/microduck \
  --microduck-rl /home/juper007/projects/microduck-connectome-thor/microduck_rl \
  --output /tmp/p602-runtime-final/robotd-readonly-evidence.json
```

Observed: both health reads reported `healthy=true`; state before and after reconnect
reported `policy=held`, 15 joints, 15 targets, and zero requested/applied motion. The
reconnect advanced client generation 1 to 2. The 50 Hz robotd loop reported zero missed
ticks in both health samples.

## Raw artifact references

Large/runtime-local logs remain on Thor.

| Artifact | Bytes | SHA256 |
|---|---:|---|
| `/tmp/p602-runtime-final/robotd-readonly-evidence.json` | 3306 | `d345a133c5c5878522e2d30deec7dca51b5e7618e186fdd236747435a56e9c8d` |
| `/tmp/p602-runtime-final/robotd-validation-final.log` | 2703 | `4d662d907e0a16b1f2f683bca882d133f703963a134ecc46b8e63d75d994c477` |
| `/tmp/p602-runtime-final/body-validation-final.log` | 137 | `de1e61fc6a48d016650055692c10d8ec943836a43df9c5a9b56f26e786c8c882` |

The runtime log snapshots were copied only after both processes stopped and then made
read-only, so the recorded hashes identify immutable files. They cover startup through
shutdown and contain no credentials or tokens.

## Scope

This evidence covers P6-02 read-only IPC only. It does not select a stop transport,
calibrate yaw, send velocity, or provide evidence for P6-03 or later tasks.
