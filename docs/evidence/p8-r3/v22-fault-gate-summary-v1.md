# P8-R3 V2.2 local fault gate — PASS

Frozen source commit: `65122a8977c64f1f24ca92eeae18f9717100cd87`.

`python -m unittest tests.test_neural_stop_persistence tests.test_p8_r3_official_harness tests.test_fault_stop -v` passed 25 tests with zero failures or errors on that commit. The [raw gate](v22-fault-gate-raw-v1.json) records all 25 observed test identities and outcomes. The six new focused cases cover transient stale neural output followed by fresh movement intent, later external fault, neural-then-fault priority, stale watchdog stop after a healthy neural latch, fault during an in-flight move ACK, and fault during an in-flight stop ACK.

The authentic watchdog and motion adapter continue `robot.stop` publication at deterministic 20 ms control tick spacing after the first safe stop. No test publishes a positive move after the stop latch; the in-flight move ACK precedes the first stop ACK. The fault latch and motion arbiter preserve later external fault provenance. The watchdog retains its first-fault reason, so its stale reason may still describe the earlier transient fault.

This is a local component gate using a fake robotd ACK, not an official simulator, pose-stop, measured wall-clock cadence, or hardware result. See the raw gate for each command/ACK ordering assertion and the [manifest](v22-fault-gate-manifest-v1.json) for SHA256 and byte counts.
