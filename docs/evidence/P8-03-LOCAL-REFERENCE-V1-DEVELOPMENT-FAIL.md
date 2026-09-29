# P8-03 local reference V1 development failure

Task: `P8-03-LOCAL-REFERENCE-DEVELOPMENT-EXECUTION`. Source: PR #88 reviewed head `821360b5a0f88ede760a0961a2f7f1bada53dbc4`, based on `57161251c63be912a002d236d18e7c13cd48b1cc`.

On Thor, the 51 focused tests and the zero-ID preflight passed. The first development reset, `D889100` attempt 1, completed official startup, pinned walk-policy readback, and persisted a valid settled local reference. `scripts/p8_03_trial.py:189` then raised `NameError: reference_hash is not defined` before movement or arm. The child remained alive during thread shutdown. The operator sent SIGINT to the batch once to trigger its conservative stop and official down path. The batch marked `D889100` `INTERRUPTED_UNKNOWN_ARM`; no armed marker exists. It did not retry the ID. `D889101`–`D889109` remain pending. No final ID ran and no behavioral result was obtained.

The raw package is retained unchanged on Thor at `/home/juper007/projects/microduck-connectome-thor/evidence/p8-v2-final/p8-03-local-v1`. Its `development-manifest.json` SHA256 is `63ea9f26cf24c5033dbd4d057bd45fec23f02ed5407a9d0cfc45bf1f32d57ec3`. The 14-entry manifest verified after the failure. The scorer returned FAIL; official final down and the port/socket probe passed. Zero reported safety violations cannot establish closed-loop safety because no trial armed. The independent development evidence review returned FAIL.

This failed V1 reset and package are historical evidence. R1 uses a different development matrix and output root. Neither the V1 journal nor its manifest may be rewritten, and `D889100` cannot be retried or counted in R1.
