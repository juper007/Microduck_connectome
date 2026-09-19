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

Raw traces and launch/shutdown logs are read-only at
`/home/juper007/projects/microduck-connectome-thor/evidence/p6-03/20260919T1206Z`
on Thor. The run interval was 2026-09-19T12:06:56Z through
2026-09-19T12:08:33Z. SHA-256 values for the decision-bearing raw JSON are in
`motion-calibration-v1.json`; launch log hashes are available beside the raw
artifacts. No credentials are present.

This is simulator-only evidence. It does not authorize physical motion, claim a
calibrated yaw-rate response, or bypass robotd's policy and safety ownership.

Focused Thor regression command:

```text
python3 -m pytest -q tests/test_motion_adapter.py tests/test_robotd_client.py
tests/test_steering_decoder.py tests/test_watchdog.py tests/test_safety_clamp.py
tests/test_p5_pipeline.py tests/test_p4_sensor_pipeline.py
tests/test_p6_runtime_evidence.py
```

Result: 138 passed in 0.12 seconds on Python 3.12.
