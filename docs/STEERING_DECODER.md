# Steering Decoder

Task: **P5-02**

The decoder computes the explicit neural differential:

```text
abstract_demand = steering_right - steering_left
vyaw = steering_yaw_sign * gain_vyaw_radps * abstract_demand
```

The output is clamped to the frozen `abs(vyaw) <= 0.50 rad/s` envelope and always uses `vy=0`.

## Yaw calibration is intentionally unresolved

The committed `config/steering_decoder_v1.json` stores:

```json
"steering_yaw_sign": null
```

A healthy readout cannot be converted to `vyaw` until Phase 6 uses the official simulator heading fixture to freeze +1 or -1 through normal reviewed configuration change. Tests use explicit +1/-1 temporary configs only to prove exact direction inversion.

The decoder produces an internal behavior intent only. It never calls robotd, `robot.move`, servo APIs, or hardware.
