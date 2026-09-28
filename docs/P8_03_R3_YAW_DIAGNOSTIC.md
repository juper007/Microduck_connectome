# P8-03-R3 yaw diagnostic protocol v1

Task P8-03-R3-YAW-DIAGNOSTIC starts from freshly fetched `origin/main`
`57161251c63be912a002d236d18e7c13cd48b1cc`. PR #80 and immutable
Release `p8-03-r1-evidence-v1` remain terminal R1 FAIL. PR #81 and its R2
development roots remain terminal R2 FAIL. This protocol is a separate,
development-only investigation. It never arms a P8 static or receding trial,
executes a final seed, performs the R2 60-reset qualification, or implements a
correction. The P8 criteria, final 0.08 rad tolerance, R2 0.06 rad guard,
controller, graph, decoder, safety envelope, and final matrices stay frozen.

## Hypotheses and measurement

The unresolved R2 v4 D01 event is a positive `vyaw` correction that increased
the reference-heading error from 0.120655 to 0.155390 rad over seven requests.
P6/P7/G8 longer-duration calibration supports positive command to positive
MuJoCo yaw and negative to negative yaw, but does not identify 0.2-second
post-stop response under the current model-1250 policy. Candidate classes are
robotd command sign, MuJoCo quaternion/coordinate sign, policy response and
rebound, saturation/clamp, stale pose timing, reset asymmetry, nonlinear
contact response, or infrastructure fault. ACK, requested/applied velocities,
`limited_by`, policy state, robotd clock, official body `sim_time`, pose and
quaternion, stop ACK, and final down/probe are retained per reset. During-pulse,
after-first-stop, and after-second-stop trajectories permit these classes to
be distinguished where the data support it. Unresolved mechanism is reported
as unresolved, not inferred from sign alone.

The complete development matrix is `D00`–`D49`, seeds 887700–887749,
preregistered in `config/p8_03_r3_yaw_diagnostic_v1.json`. Ten five-reset
blocks use `+,−,sham,−,+` for even blocks and `−,+,sham,+,−` for odd blocks.
Thus there are 20 positive, 20 negative, and 10 sham fresh resets. Each reset
starts with official `duck-sim down/up` at `SIT`, exact pinned upstream and
model-1250 policy, zero-intent stop, one-second settle, then 21 fresh pose
samples at 50 ms. Each active condition sends exactly two 0.20-second,
±0.2-rad/s high-level yaw pulses at 50 Hz, with an acknowledged `robot.stop`
after **each** pulse. Sham has identical timings and two zero-yaw pulses.
One-second settle and 21 fresh 50-ms samples follow each stop. There is no
feedback or response-dependent second pulse. A single reset never switches
signs. Requested yaw integral is at most 0.08 rad/reset.

The primary response is wrapped final plateau median minus initial plateau
median. Its frozen detection floor is `max(0.005 rad, largest absolute sham
response + 0.002 rad)`. The sham distribution defines the noise floor only;
the formula is frozen before seeing any directional data. Stable bidirectional
mapping requires all 20 valid positive responses strictly above the floor and
all 20 valid negative responses strictly below its negative, plus 10 valid
shams. This is a strict diagnostic reproducibility criterion, not a final
P8 efficacy claim or an estimate of correction reliability. Any weak response
is INCONCLUSIVE. Wrong-sign response is WRONG_SIGN. Both make the mapping gate
FAIL. All safe resets are completed even if a response is weak. Any safety or
data-integrity breach stops the batch and leaves unrun IDs pending; no retry.

## Safety and integrity

Use only official high-level `robot.move` and `robot.stop`. Zero x/y command;
100-ms motion TTL; 50-Hz refresh; bounded 0.2-rad/s yaw and 0.2-s pulses.
Pre-command simulator and robotd clocks must advance, body-response age must
be at most 100 ms, health must be nondegraded, and pinned walk policy must be
loaded. The robotd lifecycle field may be `stand` while stopped and `walk`
while moving; any other lifecycle state aborts. A body read may wait at most
50 ms for a newer simulator clock tick. The first two 20-ms command ticks
permit the stand-to-walk transition; ticks 3–10 require `walk` for active
yaw. Command starts must be spaced 10–30 ms apart (50 Hz ±10 ms); missed
cadence invalidates that reset. Initial x/y/z must be inside the
unchanged R2 reference envelope;
initial heading may be up to 0.35 rad from that reference for diagnostic
inclusion, without qualifying it for P8. Roll and pitch stay within ±0.5 rad,
and command-induced planar translation within 0.01 m of each reset's start.
Every stop must ACK; post-stop applied velocity must decay to ≤0.005 and the
21-sample heading drift to ≤0.005 rad. A stale/nonfinite/nonadvancing pose,
ACK/TTL failure, wrong policy, unhealthy robotd, excess motion, or failed
down/probe aborts with a retained partial trace. `robot.stop` is attempted in
`finally`; official `down` and a socket/port probe follow every reset.

## Frozen analysis and handoff

The scorer reads every raw trace and verifies the frozen ID/order, sign,
freshness, stop and cleanup fields before computing the sham floor and
directional mapping. The result is FAIL or BLOCKED if any required trace is
missing or invalid. No parameter changes can be made after viewing outcomes;
a changed design needs a new version and a new matrix. A separate versioned
correction strategy may be **designed** only if this bidirectional gate PASSes.
It must use conservative bounded correction and stop after each command, and
must receive independent exact-head review before any reset qualification.

Thor handoff: clone the reviewed R3 head into
`/home/juper007/projects/microduck-connectome-thor/p8-03-r3-yaw-source`, verify
its clean HEAD, pinned upstream commits and material SHA256, Python 3.12, and
idle dedicated state `/tmp/p8-03-r3-yaw-state` / port 7899. Run only
`python3.12 -m scripts.p8_03_r3_yaw_diagnostic --output
/home/juper007/projects/microduck-connectome-thor/evidence/p8-v2-final/p8-03-r3-yaw-diagnostic-v1
--reviewed-head <exact-head>`. The output root is single use. Publish raw
evidence as immutable Release `p8-03-r3-yaw-diagnostic-evidence-v1`, download
and reverify asset bytes, rerun the scorer from raw traces, and have an
independent reviewer inspect the final exact head and evidence. No final seed
is eligible in this task.
