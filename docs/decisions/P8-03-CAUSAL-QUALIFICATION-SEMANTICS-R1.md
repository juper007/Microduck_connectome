# P8-03 causal qualification semantics R1

Task: `P8-03-CAUSAL-PRECONDITION-R1-QUALIFICATION-SEMANTICS`. Input source
`fbe77021c982318c6bc2d26fc795043f384b5146`; fetched `origin/main`
`57161251c63be912a002d236d18e7c13cd48b1cc`. PR #94 head `66754b4`,
PR #95 head `8683a8d`. Upstream pinned source `344925c`, candidate
`c47085a`. This decision is prospective. `CPDEV-001` remains immutable
FAIL evidence and is never replayed as a new probe or reclassified.

## Required decision

| Field | Verdict |
| --- | --- |
| `FIRST_CAUSAL_LOW_VX_CAUSE` | robotd command EMA, alpha 0.2, starting at zero; requested 0.07 gives applied 0.014 on first tick. |
| `APPLIED_VX_GATE_ORIGINAL_MEANING` | Option 3: fresh applied vx at least 0.04 immediately before ARM, with 1.5 s of 20 ms commands and independent body movement. No first-tick or full-duration-above-0.04 rule was frozen. |
| `CAUSAL_MONITORING_WINDOW_REQUIRED` | YES, from first consumed accepted positive generation; every tick through stop/eligibility is retained and safety checked. |
| `QUALIFYING_MOVING_WINDOW_REQUIRED` | YES, prospectively as an eligibility phase; starts only at a fresh, attributed walk state with applied vx at least 0.04 and fresh pose-derived speed at least 0.015. It cannot erase prior causal contamination. |
| `DURATION_START` | FIRST_CAUSAL_TICK. Frozen 1.5 s of 20 ms commands is measured from causal start, per PR #94. The qualifying phase does not restart or shorten that clock. |
| `THRESHOLD_CHANGED` | NO; applied 0.04 m/s, pose speed 0.015 m/s for 200 ms, displacement 0.01 m unchanged. |
| `NO_DEADMAN_RULE_CHANGED` | NO; any causal deadman, fault, safety limiter, malformed state, or tick gap fails. |
| `LIMITED_BY_SCHEMA_FIX` | YES; omitted means empty Vec, `[]` means empty, `null` and wrong types fail, any nonempty limiter fails closed. |
| `REMEDIATION_ELIGIBLE` | YES for prospective v2 implementation and exact-head independent review; no fresh label until review PASS. |

The preregistered [local-reference protocol](../tasks/P8-03-LOCAL-REFERENCE-PROTOCOL-V1.md)
and `config/p8_03_local_reference_v1.json` introduced the 0.04 endpoint check.
The historical `scripts/p8_03_trial.py` and `scripts/p8_03_score.py` use 75
commands and the last fresh applied state. [PR #94's causal decision](P8-03-PRECONDITION-CAUSAL-STATE-DECISION.md)
requires the 1.5 seconds from first causal consumption. Requiring a further
1.5 seconds after 0.04 would change that duration meaning, so R1 does not do it.
The prospective v2 evaluator does require the applied threshold and walk policy
to remain valid after the first qualifying state through eligibility. This
strengthens continuity without changing the numerical threshold or behavioral
acceptance.

## CPDEV-001 source diagnosis

Immutable archive: `p8-03-causal-precondition-fail-v1.tar.gz`, SHA-256
`161f8fdb3427fabfb1b7c468199d9b38298d2d7e1e1d9d0e0f501c8ebe97f0a6`.
Its `diagnostic.jsonl` SHA-256 is
`595e8dd7b85afc87a669cb5a710d40f0fd780cb326da5d3dd0d0abed1fb2f1fd`.
The first 15 causal states are retained below. Accepted and consumed generation
are identical in each row. Requested vx is 0.07 m/s, `limited_by` is omitted
(empty), safety fallen/limp are false, and no deadman/fault occurs in every row.
Pose speed is from the adjacent independent body samples, not a robotd field.
Times are monotonic nanoseconds.

| Tick/gen | Command sent ns | State source ns | Applied vx | Policy | Body pose speed m/s |
| --- | ---: | ---: | ---: | --- | ---: |
| 394/1 | 325066750083537 | 325066764154666 | 0.014000000 | stand | 0.000404 |
| 395/2 | 325066770134036 | 325066784386379 | 0.025200000 | stand | 0.000566 |
| 396/3 | 325066790120026 | 325066804542877 | 0.034160000 | stand | 0.000551 |
| 397/4 | 325066810118099 | 325066824682950 | 0.041328000 | stand | 0.000519 |
| 398/5 | 325066830070061 | 325066844844439 | 0.047062400 | stand | 0.000110 |
| 399/6 | 325066850118708 | 325066864165689 | 0.051649920 | walk | 0.000137 |
| 400/7 | 325066870076698 | 325066884480614 | 0.055319936 | walk | 0.004924 |
| 401/8 | 325066890113688 | 325066904651650 | 0.058255949 | walk | 0.011246 |
| 402/9 | 325066910113529 | 325066924826871 | 0.060604759 | walk | 0.022156 |
| 403/10 | 325066930112102 | 325066944947935 | 0.062483807 | walk | 0.036594 |
| 404/11 | 325066950103796 | 325066965083786 | 0.063987046 | walk | 0.096625 |
| 405/12 | 325066970120572 | 325066984316506 | 0.065189637 | walk | 0.000000 |
| 406/13 | 325066990112442 | 325067004494728 | 0.066151709 | walk | 0.040414 |
| 407/14 | 325067010120062 | 325067024324199 | 0.066921367 | walk | 0.067627 |
| 408/15 | 325067030116745 | 325067044513310 | 0.067537094 | walk | 0.098608 |

Every applied value follows `v[n] = v[n-1] + 0.2 * (0.07 - v[n-1])` exactly
from zero. Pinned MicroDuck `robotd-params/src/lib.rs` sets the default
`cmd_alpha=0.2`; `robotd/src/main.rs` smooths the gated twist before publishing
`move.applied`. The stand policy persists until the smoothed command passes
the policy's 0.05 walk threshold (`duck-control/src/policy.rs`). Thus command
smoothing causes the 0.014; stand is a consequence, not the vx reduction.
The project SafetyClamp and robotd joint safety limiter did not cause it.

`CPDEV-001` still has local reference PASS, 91 paired move ACKs, contiguous
ticks, no causal deadman/fault, and 0.051377938 m body displacement. Its
recorded evaluator result is FAIL because v1 rejected omitted empty
`limited_by`; the first-tick applied check would independently reject 0.014.
Neither recorded result nor archive is edited.

## Prospective non-weakening proof

- Tick 394 at 0.014 cannot qualify; safety monitoring starts there.
- A deadman, fault, safety limiter, unknown limiter, malformed state, or tick
  gap at any causal ramp tick is terminal. Later clean movement cannot reset it.
- Physical drift before the qualifying state never substitutes for applied
  threshold, walk policy, sustained pose speed, displacement, or freshness.
- The first qualifying state must actually show applied vx >=0.04, walk policy,
  and a fresh independent pose speed >=0.015. Full 1.5 s command/cadence and
  duration evidence still begins at the first causal tick.
- No scored ARM is present in the development probe; eligibility is reported
  only after all frozen gates pass.

## Limiter protocol

Pinned `duck-ipc-proto` uses
`#[serde(default, skip_serializing_if = "Vec::is_empty")]` for
`MoveState.limited_by` and tests omission of an unlimited command. Thus
omitted and `[]` mean empty. JSON `null` is not a valid Vec; wrong element
types fail. The protocol presently emits `deadman`, `joint_range`, and
`not_finite`; `safety` or any future/unknown token is retained as evidence
and fails closed, never treated as clean.
