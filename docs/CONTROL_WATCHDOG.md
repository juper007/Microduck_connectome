# Phase-5 Control Watchdog

Task: **P5-05**

The watchdog is an internal safety boundary before future robot integration. It does not call robot APIs or select a stop transport.

Frozen freshness limits are 100 ms for both neural readout and behavior intent. Exactly 100 ms remains fresh; 100 ms + 1 ns is stale.

Missing, malformed, stale, future/regressing, unhealthy, or unavailable decoder inputs produce an internal safe intent with stop=true, zero motion, and confidence=0. Repeated identical samples are allowed while still fresh, and a new advancing healthy sample can recover normal pass-through behavior.
