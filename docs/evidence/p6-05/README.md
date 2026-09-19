# P6-05 end-to-end telemetry evidence

## Result

Source `5c2d6edff74dfef1ad9106025793d64761364ed8` ran the full controller chain
on Thor against the pinned official `robotd` and headless MuJoCo simulator.
The canonical JSONL trace contains 322 post-command records: neutral, left,
right, and center each have 60 records; stop has 82. It contains 321 actual
`robot.move` transports and one acknowledged `robot.stop` transport.

Every record links camera/ToF identity and the frozen `PerceptionFrame` to
named sensory channels, MaleCNS runtime state, DN activity, decoder intent,
SafetyClamp result, watchdog output, the actual robot-facing request, a
post-command official `robot.state`, and a MuJoCo trunk heading. All 322 state
samples occurred after their command and all requested velocities matched the
robot-facing command. Timestamps and sequences are strictly increasing with
zero gaps, NaN/Inf values, or scheduler exceptions.

The observer waited for state on a separate official robotd connection and did
not replace or block robotd's own loop. The measured controller/publish rate was
50.1357 Hz and perception was 25.1460 Hz.

## Identities and serialization

`telemetry-summary-v1.json` records the Microduck_connectome, MicroDuck,
microduck_rl, MaleCNS dataset, graph, P6 integration, scheduler, sensory,
readout, decoder, safety, watchdog, and motion-adapter identities. The frozen
P6-03 values remain `steering_yaw_sign=-1` and
`stop_transport=robot_stop`.

The trace uses sorted-key compact JSON with `allow_nan=false`. The logger
rejects secret-like keys and machine-specific absolute paths, validates
strict monotonic metadata, and deep-detaches every record before retention.

## Retained artifacts

The large trace remains on Thor under the immutable task artifact directory
`/home/juper007/projects/microduck-connectome-thor/evidence/p6-05/20260919T-p605-v2`.

| Artifact | SHA256 |
|---|---|
| `telemetry.jsonl` | `e9cae6a59a14e8fed7382e436e5299254e16d1227ee1ca8a70e2ec8b7b093a55` |
| `telemetry-summary.json` | `8f64abf7819ed7a165ebe32fc51cd2be437d91bae461fbf8b490e3fb204c09d4` |
| `python312-tests.log` | `05a911ccc35063dee5dc368521f3fd90fc0b067ee12e44f5922901e26e05d4ae` |
| `final-health.log` | `c3ef443afdc8a4c56af203559bcf2ebe0ee939651b41fb55367d3bd8559bec67` |
| `shutdown.log` | `d3f4afe57114c117d294acd158e7e26c1e0555df5b2145a4933c323f20891b7c` |

Python 3.12 ran the relevant P4, P5, P6 scheduler, IPC, adapter, schema, and
telemetry regressions: **217 passed in 2.67 seconds**. The official simulator
was then stopped through `duck-sim down`; its task socket was absent afterward.

## Scope and limitation

This proves reconstructible telemetry, not Phase-7 steering success rates.
The pinned 570-node graph contains only two of the four configured DN IDs, as
already recorded by P6-04. The deterministic scenario labels therefore prove
input/trace coverage; they do not add missing biological edges or claim that
all five inputs generate distinct learned behavior. The explicit stop record
is the scheduler's fail-safe decoder-shutdown stop, so the trace identifies
that watchdog cause instead of falsely attributing it to the looming input.
