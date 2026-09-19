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
- robotd socket: `/tmp/p602-runtime-final2/robotd.sock`
- Evidence window: `2026-09-19T01:17:33.757449Z` through
  `2026-09-19T01:17:33.789310Z`

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
............................                                             [100%]
28 passed in 0.03s
```

The final pushed implementation was also checked out in `/tmp/p602-full` for the P6
client/evidence tests plus P4/P5 safety regressions. The exact-head result is recorded in
the PR validation summary.

Real runtime probe:

```text
PYTHONPATH=/tmp/p602-code python3 /tmp/p602-code/probe_robotd_readonly.py \
  --socket /tmp/p602-runtime-final2/robotd.sock \
  --microduck /home/juper007/projects/microduck-connectome-thor/microduck \
  --microduck-rl /home/juper007/projects/microduck-connectome-thor/microduck_rl \
  --output /tmp/p602-runtime-final2/robotd-readonly-evidence.json
```

Observed: both health reads reported `healthy=true`; state before and after reconnect
reported `policy=held`, 15 joints, 15 targets, and zero requested/applied motion. The
reconnect advanced client generation 1 to 2. The 50 Hz robotd loop reported zero missed
ticks in both health samples.

## Raw artifact references

Large/runtime-local logs remain on Thor.

| Artifact | Bytes | SHA256 |
|---|---:|---|
| `/tmp/p602-runtime-final2/robotd-readonly-evidence.json` | 3306 | `f9a10e93392303b0bb416b4c789b72af0dbce58aa6e5039949947a59ed83d6c9` |
| `/tmp/p602-runtime-final2/robotd-validation-final.log` | 2724 | `a708204c51abea767e0f5e7df3d2301794bfb03fd9524b60bb087caeb3825d50` |
| `/tmp/p602-runtime-final2/body-validation-final.log` | 137 | `21dde2545ceb0ceb44076f8e3c26978fd8f3ff6359ffda3410d50501451d0bb9` |

The runtime log snapshots were copied only after both processes stopped and then made
read-only, so the recorded hashes identify immutable files. They cover startup through
shutdown and contain no credentials or tokens.

## Scope

This evidence covers P6-02 read-only IPC only. It does not select a stop transport,
calibrate yaw, send velocity, or provide evidence for P6-03 or later tasks.
