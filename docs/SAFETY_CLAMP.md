# Safety Clamp

Task: **P5-04**

The Phase-5 safety clamp enforces the frozen internal motion envelope independently of neural/decoder logic: `abs(vx)<=0.08`, `vy=0`, `abs(vyaw)<=0.50`, with slew limits `0.20/s` for vx and `1.50/s` for vyaw. Slew timing uses monotonic intent timestamps and the last emitted safe intent.

Malformed, non-finite, wrong-source, future, or nonmonotonic intents are converted to `stop=true` with zero motion and an explicit reason. An input stop also forces zero motion immediately. Reset clears the previous slew state.

The module emits only internal safe-intent data plus intervention reasons; transport/integration is outside P5-04.
