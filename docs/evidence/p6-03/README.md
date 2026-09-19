# P6-03 bounded motion calibration evidence

The pinned official `robotd` (`344925c9f8fa031f85428a305b1e8ec2eaae29c1`)
and `microduck_rl` MuJoCo simulator
(`cb70b792312d559a4da09064d92009079671815f`) were run on Thor. Every yaw trial
used a fresh simulator process at the `SIT` keyframe followed by the official
enable/stand sequence. The two zero-twist initial trunk headings differed by
2.26e-9 rad, establishing a matched reset pose.

At `vx=0`, six seconds of `vyaw=+0.2` changed wrapped trunk heading by
+0.005692066 rad. A fresh reset followed by `vyaw=-0.2` changed it by
-0.072844682 rad. Both requested and applied state reached the commanded sign,
and the measured heading deltas have opposite signs. This freezes the protocol
direction as positive yaw = simulated left. The gait response is strongly
asymmetric and partly unwinds after stopping; the evidence establishes sign,
not yaw-rate accuracy.

The existing abstract demand is `steering_right - steering_left`. A left-image
target therefore gives negative demand, so `steering_yaw_sign=-1` maps it to the
measured positive left turn.

Both candidate stop transports were tested after actual bounded motion. One
`robot.stop` request returned `accepted=true`, held requested zero for one second
without republishing, resumed on a later move, and was accepted again after the
controller socket was closed and reopened. One zero-twist notification also
held through the upstream deadman and resumed on a later move. `robot_stop` is
selected because its discrete acknowledgement makes acceptance observable while
retaining the verified one-shot, persistence, resume, and reconnect behavior.
The production adapter refreshes this acknowledged request on every watchdog
stop tick so a silent peer loss cannot hide behind a local latch.

The safety-review rerun distinguished three restart cases. A controller socket
reconnect advanced the client generation from 1 to 2; movement was rejected
until a newly minted watchdog safe-stop crossed successfully. The fixture then
terminated the verified robotd PID 2351958 while MuJoCo remained running. The
next stop refresh detected `Broken pipe`. After robotd PID 2352950 started and
the client reached generation 3, movement was again rejected until a fresh
safe-stop. Subsequent bounded motion reached requested `[0.04, 0, 0.2]` and
applied `[0.0397639, 0, 0.1988194]`, followed by an acknowledged final stop.
Full simulator restarts are separate: those are the fresh-process resets used
for the matched yaw trials.

Raw traces and launch/shutdown logs are read-only at
`/home/juper007/projects/microduck-connectome-thor/evidence/p6-03/20260919T1206Z`
on Thor. The run interval was 2026-09-19T12:06:56Z through
2026-09-19T12:08:33Z. SHA-256 values for the decision-bearing raw JSON are in
`motion-calibration-v1.json`; launch log hashes are available beside the raw
artifacts. No credentials are present.

Final boundary-remediation evidence was rerun from source head
`b6d9a811f31dd6d881aa549bba1757fc7059bd42` and is read-only at
`/home/juper007/projects/microduck-connectome-thor/evidence/p6-03/20260919T125838Z-final-boundary`.
Its decision-bearing JSON SHA-256 is
`0f472f80c69a16a8cdb1338a473815c8e1c38b82ceaff582ee7dc477c2aabbfc`.
The JSON embeds the executed fixture SHA-256
`09b0160406e2d780512247b2afb5960b2460594e77acf895090c5a8cb18efc3c`;
`executed-sources.sha256` records the exact runtime, config, test, and fixture
files used. The final fixture also records rejection of the same pre-safe-stop
output after both controller reconnect and actual robotd restart.

This is simulator-only evidence. It does not authorize physical motion, claim a
calibrated yaw-rate response, or bypass robotd's policy and safety ownership.

Focused Thor regression command:

```text
python3 -m pytest -q tests/test_motion_adapter.py tests/test_robotd_client.py
tests/test_steering_decoder.py tests/test_watchdog.py tests/test_safety_clamp.py
tests/test_p5_pipeline.py tests/test_p4_sensor_pipeline.py
tests/test_p6_runtime_evidence.py
```

Initial result: 138 passed in 0.12 seconds on Python 3.12. After the final
watchdog-content identity and bypass coverage changes, the exact focused command
passed 149 tests in 0.12 seconds on Python 3.12. Its log SHA-256 is
`9c065fe71cbcace8aa23ccdd9ebecf80606f3f78783c681c21c23d3826ecfdbb`.
