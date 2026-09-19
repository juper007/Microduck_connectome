# Steering Decoder

Task: **P5-02**

The decoder computes the explicit neural differential:

```text
abstract_demand = steering_right - steering_left
vyaw = steering_yaw_sign * gain_vyaw_radps * abstract_demand
```

The output is clamped to the frozen `abs(vyaw) <= 0.50 rad/s` envelope and always uses `vy=0`.

## Frozen yaw calibration

The committed `config/steering_decoder_v1.json` stores:

```json
"steering_yaw_sign": -1
```

P6-03 measured positive `vyaw` as positive wrapped MuJoCo trunk-heading change
and negative `vyaw` as negative change from matched reset poses. Since a left
image target raises `steering_left`, `right - left` is negative; multiplying by
`-1` therefore requests the simulator-proven positive, left-turn direction.
The calibration and its observed asymmetry are recorded in
`docs/evidence/p6-03/README.md`.

The decoder produces an internal behavior intent only. It never calls robotd, `robot.move`, servo APIs, or hardware.
