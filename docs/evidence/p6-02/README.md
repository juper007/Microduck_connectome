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
- robotd socket: `/tmp/p602-runtime/robotd.sock`
- Evidence window: `2026-09-19T00:52:44.848429Z` through
  `2026-09-19T00:52:44.871624Z`

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
.........                                                                [100%]
9 passed in 0.02s
```

The pushed implementation was then checked out in `/tmp/p602-full`. The P6
client/evidence tests plus P4/P5 safety regressions passed:

```text
54 passed in 0.08s
```

An attempted all-tests collection on that clean checkout stopped before running because
Thor's system Python does not have the unrelated `pyarrow` dependency used by four Phase-1
evidence test modules. This is an environment limitation, not a P6-02 test failure; the
targeted P4/P5/P6 set above collected and passed.

Real runtime probe:

```text
PYTHONPATH=/tmp/p602-code python3 /tmp/p602-code/probe_robotd_readonly.py \
  --socket /tmp/p602-runtime/robotd.sock \
  --microduck /home/juper007/projects/microduck-connectome-thor/microduck \
  --microduck-rl /home/juper007/projects/microduck-connectome-thor/microduck_rl \
  --output /tmp/p602-runtime/robotd-readonly-evidence.json
```

Observed: both health reads reported `healthy=true`; state before and after reconnect
reported `policy=held`, 15 joints, 15 targets, and zero requested/applied motion. The
reconnect advanced client generation 1 to 2. The 50 Hz robotd loop reported zero missed
ticks in both health samples.

## Raw artifact references

Large/runtime-local logs remain on Thor.

| Artifact | Bytes | SHA256 |
|---|---:|---|
| `/tmp/p602-runtime/robotd-readonly-evidence.json` | 3309 | `9f4724de9ffe9820136b27f0af7b5269543aec341dca10f83a01585843e95199` |
| `/tmp/p602-runtime/robotd.log` | 1824 | `e4d6a28c8210477653068840f46befb78d1faad7a4be7c641491c16434207a55` |
| `/tmp/p602-runtime/body.log` | 137 | `81be996147b661126a6fd6c252de380cfef56ea7fdcede9d0ad5340e3444fa87` |

The runtime logs cover startup at `2026-09-19T00:50:53Z` and the probe window above.
They contain no credentials or tokens.

## Scope

This evidence covers P6-02 read-only IPC only. It does not select a stop transport,
calibrate yaw, send velocity, or provide evidence for P6-03 or later tasks.
