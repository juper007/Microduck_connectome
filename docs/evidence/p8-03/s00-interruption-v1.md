# P8-03 S00 acquisition interruption — negative evidence v1

**Gate: BLOCKED.** This is an interrupted acquisition, not a scored static
trial or a P8-03 behavioral result. Preserve the existing Thor output. Do not
resume S00, substitute a seed, or start R/P8-04 from this run.

## Identity and frozen inputs

- Source: PR [#79](https://github.com/juper007/Microduck_connectome/pull/79),
  `experiment/p8-03-static-receding`, execution HEAD
  `91a932cb9c36db943939df24646ab3a6c72b9d0e`; base
  `57161251c63be912a002d236d18e7c13cd48b1cc`.
- Execution config: `config/p8_03_execution_v1.json`, SHA256
  `32e25712bef2c81a51ec150a46e794eb56101bcc884d30618ba32b3c9c26468c`.
  Thor's committed master protocol config SHA256 was
  `d281d239b9d080027d4c2662f889f76e68e04ef06599d78bb0cd644dcf515e42`.
- Thor host: `jetsonthor01`; official MicroDuck
  `344925c9f8fa031f85428a305b1e8ec2eaae29c1`, microduck_rl
  `cb70b792312d559a4da09064d92009079671815f`, graph SHA256
  `c4160c42941163079b6b569d117bf67afcf8b45eaa128c444f7c96c2567593cc`,
  walking policy SHA256
  `98c3ea73fa6bb196bcf16586cf38b9fffb782787447d638fa1c1028df9082c1a`.
- Reviewed Thor focused command:
  `PYTHONPATH=. python3.12 -B -m unittest tests.test_p8_03_controls -q`;
  12 tests passed on Python 3.12.3. The earlier remote implementation-readiness
  review passed at the execution HEAD; it is not a final experiment review.

## Preserved observation

At `2026-09-28T11:26:49Z`, the S preflight recorded PASS with zero IDs assigned,
then a journal checkpoint recorded `S00/attempt-01` as `ACQUIRING` with
`armed=false`. The process ended without a completed attempt or final simulator
down record. The preserved `down.log` is zero bytes and was not included in the
last checkpointed manifest. There is no active P8-03/duck-sim/robotd process.

The reviewed `--recover-only` path was run without changing the journal or
trial bytes. It reported `in_flight_unknown_arm=["S00/attempt-01"]`, source
journal SHA256 `56feaba7e6bd593af2d438f4e2dfdf348391bd2c4b6fd97355a21fb7572f531d`,
and full manifest **FAIL** (`missing_or_extra:S00/attempt-01/down.log`). The
isolated-state probe at `2026-09-28T15:53:48Z` returned PASS: body port 7894
and `/tmp/p8-03-state/duck-a.sock` were not connectable. This post-interruption
probe is not a substitute for the missing final down record.

The available checkpoint does not prove the trial remained unarmed after its
last write. No S trial was scored, no R trial started, and no safety-violation
count can be concluded from this incomplete run.

## Durable archive and independent download

- [Release](https://github.com/juper007/Microduck_connectome/releases/tag/p8-03-s00-interruption-v1)
  and [asset](https://github.com/juper007/Microduck_connectome/releases/download/p8-03-s00-interruption-v1/p8-03-s00-interruption-v1.tar.gz)
- Asset bytes: `1907`; SHA256:
  `a05c8031d5e15b6f8d07c3ab8fad3b2e02243dbca729ddc42e58dbf3ed5c840b`.
- Archive contains the preflight/recovery audit, static batch journal, raw
  manifest, and S00/attempt-01/down.log. It was downloaded fresh from GitHub
  into a separate directory; byte count, SHA256, and tar listing matched.
- Deterministic remote recheck of the downloaded bytes returned manifest FAIL
  with the same unaccounted file, batch score FAIL, and S00
  `missing_or_incomplete_id`. The planned denominator remains 20 static IDs.

## Required next step

Classify and investigate the interruption without modifying this archive or
the original output. The unknown-arm state and incomplete manifest block this
frozen final batch. Follow the protocol's separately versioned remediation
workflow, including new development/final seeds where required and fresh
independent review, before another official P8-03 execution. P8-04 and later
Phase 8 gates remain blocked.
