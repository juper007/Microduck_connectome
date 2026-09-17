# ToF Proximity Encoder

Task: **P4-03**

The MVP ToF encoder maps explicit left/center/right millimeter distances into the frozen perception frame's three proximity channels.

For valid readings between configured `near_mm` and `far_mm`:

```text
proximity = (far_mm - distance_mm) / (far_mm - near_mm)
```

Distances at or inside `near_mm` clamp to 1.0; distances at or beyond `far_mm` clamp to 0.0.

## Sensor-loss rule

The encoder is stateless. If the source is invalid or **any one** of the three sensor readings is missing, all three proximity outputs are zero and the emitted frame has `valid=false`. No last-known distance or proximity value is replayed.

This is intentionally conservative for the MVP. It is a sensor feature contract only; neural stimulation, behavior intent and robot commands are outside P4-03.
