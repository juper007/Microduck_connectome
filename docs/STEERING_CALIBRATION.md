# P5 steering decoder and P6 yaw calibration preparation

Base: 6056aa892abc4bcc8879d2f1e76bcdee077ef495.
Branch: feature/p5-safe-steering. No main integration or phase approval implied.

## Pure decoder

`scripts/safe_steering.py` receives explicit L/R activity normalized to [0,1].
For the frozen five-step readout, divide the mean spike count by five before
calling the gate. It emits vx=vy=0 and yaw = sign * 0.5 * (left-right), clamped
to 0.5 rad/s and 1.5 rad/s² slew. Sign must be supplied from a valid simulator
calibration; neither numeric ID nor soma side establishes robot direction.

Stale (age >=100 ms), future, malformed, nonfinite, out-of-range, unhealthy,
regressing sequence, changed-payload sequence reuse and emergency inputs
immediately emit zero with stop=true. Repeated identical samples may be consumed
until their original timestamp expires. Delayed ticks cannot spend accumulated
time as a larger slew increment. Confidence is input-validity bookkeeping (1 or
0), not a calibrated estimate of visual target confidence.

Run: `python -m unittest discover -s tests -p test_safe_steering.py -v`.

This is a pure function-like gate, **not an independent watchdog service**.
The caller must tick at 50 Hz separately from the neural producer. The adapter
must also recheck outgoing intent age. Killing this entire consumer still leaves
the upstream 500 ms deadman: it does not satisfy the project's 100 ms behavior
freshness requirement. No neural producer is connected to robotd in this change.

## Dedicated simulator measurements

`scripts/calibrate_sim_yaw.py` is a bounded research harness. It is deliberately
restricted to Thor's dedicated `cal-state/duck-a.sock` and localhost port 18801.
Reset that dedicated official simulator between each sign. It sends only
robot.move and subscribes to robot.state. MuJoCo TCP is used only for read/hello.
The user's existing sim-state/17801 simulator is not controlled by this harness.

Commands are vx=vy=0, vyaw ramped toward ±0.2 rad/s at at most 1.5 rad/s².
Trials are bounded to 3 or 8 seconds. State age, fallen and limp checks abort
motion; a finally block sends a zero twist. This finally block cannot protect
against SIGKILL/process death; no crash-stop guarantee is claimed.

## Findings and promotion block

Initial 3-second trials observed heading deltas +0.00448 and -0.07004 rad.
The positive response is very small and the negative response largely reverses
after stop. An 8-second positive diagnostic observed only +0.00685 rad even
though the walk policy was selected for 394/400 frames and applied yaw reached
+0.2 rad/s. These observations are insufficient to freeze a useful steering
mapping. **steering_yaw_sign remains unset; closed-loop promotion is blocked.**
The matched 8-second negative diagnostic changed heading -0.07329 rad and then
reversed +0.07403 rad after zero twist; it also fails to show a sustained turn.

Stop was measured separately: requested twist became zero in approximately
20–40 ms, while applied twist decayed through robotd's command EMA. The original
strict diagnostic (applied magnitude <1e-9 within 1 second) FAILED and has not
been relaxed or relabeled as a pass. Applied yaw crossed 0.01 in about 0.3 s,
0.001 in about 0.5 s, and 1e-9 in about 1.7 s. Physical settling is different
from requested/applied command neutrality. `zero_twist` is the transport tested
here, not an approved looming benchmark transport or emergency stop.

Required next investigations: low-speed walk-policy yaw response, persisted
heading after settling, repeated trials and stop residual motion. Do not raise
motion limits, change policies, or invert the decoder to conceal this issue.

Upstream identities: microduck 344925c9f8fa031f85428a305b1e8ec2eaae29c1,
microduck_rl cb70b792312d559a4da09064d92009079671815f; official seeded policies
from the dedicated simulator state. The raw JSON traces and policy hashes are
retained in the Thor evidence directory, outside Git.
