# Escape Decoder

Task: **P5-03**

Normalized bilateral DNp01/GF escape activity is treated as an evidence-gated engineering input, not as biological equivalence to robot stopping.

```text
effective_escape = clamp(escape * gain, 0, 1)
stop = effective_escape >= threshold
```

The default versioned settings are gain 1.0 and threshold 0.5. A runtime-unhealthy readout also asserts the internal safe stop.

Whenever stop is asserted, `vx=vy=vyaw=0`. The decoder may preserve a same-sample steering intent when below threshold, but never clears an already asserted stop.

This task creates only the frozen internal `stop=true` behavior intent. It does **not** choose or call `robot.stop`, zero-twist transport, robotd IPC, simulator commands, servos, or hardware.
