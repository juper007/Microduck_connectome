# P8-03-R1 terminal FAIL evidence

**Gate: FAIL.** The frozen R1 static run stopped at RS04 before arm because
the official fresh-reset heading differed from the RS00 reference by
0.09849262507 rad, above the preregistered 0.08 rad tolerance. Simulator
`up` exited 0. The R1 protocol permits one attempt per ID, so RS04 was not
retried. RS00–RS03 were armed and complete; RS05–RS19 remain pending. No
receding trial ran. The 40/40 accounting and clean-trial requirements are not
met. P8-04, final regression, and G8 cannot begin from this result.

## Identity and provenance

- Task: P8-03-R1; original task branch base `origin/main`
  `57161251c63be912a002d236d18e7c13cd48b1cc`.
- Exact independently reviewed and executed source HEAD:
  `f71be96913adb1daec0952afbda7f0cf61dfa712`.
- Thor source checkout:
  `/home/juper007/projects/microduck-connectome-thor/p8-03-r1-source`, clean
  at the executed HEAD. Pinned upstream, graph, policy, Python 3.12,
  official simulator, and isolated state/port passed preflight.
- Frozen config and 40 final IDs/seeds are in the archive. The original
  P8-V2 master protocol is bound by SHA256; only R1 IDs/seeds changed.
- Historical S00 negative evidence remains in Release
  [`p8-03-s00-interruption-v1`](https://github.com/juper007/Microduck_connectome/releases/tag/p8-03-s00-interruption-v1),
  asset SHA256 `a05c8031d5e15b6f8d07c3ab8fad3b2e02243dbca729ddc42e58dbf3ed5c840b`.

## Development gate

The first development run (`p8-03-r1-development-gate-v1`) failed independent
evidence review because five nested manifests were omitted from its top-level
inventory, and an overwritten zero-byte checkpoint was not retained. Its
result and manifest SHA256 values are
`f1d5300c99963f4617cd79661e5d9e3744b4afef68136479976fdb9420d8cbac`
and `83de41fc1cf7572b29150732af20eb16e6adfa7e0ea65785f5a4ad1eb349d4fc`.
It remains in the release as failed review evidence.

The corrected, versioned v2 development run reused only the reserved
development seeds (887100–887105); no final seed was used. Independent review
verified all 43 retained files, A/B source journal snapshots, both E
checkpoint states, and the official simulator stop/down/probe in C. Cases A–F
and independent review passed. The v2 result and manifest SHA256 values are
`ffa604ed3ef451e72575285f3946d2433f3970380e7f0966ecf7e3ade1ebdf47`
and `03219079ae9879da872a8b7a21c9fcd24a62235461c6bcbb5efa5e6e1bbd41f6`.
The independent gate artifact SHA256 is
`86dc017d02fea33017ff2f5370120621ac6721393f62aa7731af34011bbfea4c`.

## Final static result

Independent review checked all 83/83 static raw manifest entries, all four
arm markers, the RS04 absent marker, and every journal state. Its retained
raw manifest, journal, and score SHA256 values are respectively
`08cf9b1b233792d7d2596e83ab3c06ed0aab08695e8bc201ed7c6eeca9572fd4`,
`e7b236574f4b17b3f0c703e7767e615cfbd91118e0807e2ecdefa917d0437f7a`,
and `59055c4c2df5bf476a3bcb3f09311198b949b2fed816551f2b5418e4fe5585f8`.
Deterministic raw rescoring matched the stored score: FAIL, 0 observed false
neural stops, 16 contaminated or incomplete IDs, and 0 observed safety-limit
violations in completed data. The missing trials do not have known safety
outcomes. The supervisor exited 1 with journal FAIL. The acknowledged
`robot.stop`, final `duck-sim down` exit 0, and isolated-state probe PASS are
retained. `up.log` contains shell errors; their cause and relationship to the
reset heading deviation are unproven.

## Immutable release and re-verification

Release: [`p8-03-r1-evidence-v1`](https://github.com/juper007/Microduck_connectome/releases/tag/p8-03-r1-evidence-v1).
The asset `p8-03-r1-evidence-v1.tar.gz` is 123861 bytes, SHA256
`9a0a7f8bd59e56d21ebb3429a1fb4a60acadcd1e9c7ae524d4efadc44974a961`.
Its full manifest SHA256 is
`c38997f1cf45aef64ae1a7e7ab80c139fd19a6d237fa36dea09cfad956ff9391`.
Independent prepublication review verified all 178/178 listed files, and a
fresh GitHub download matched the asset SHA256 and size. Local re-verification
of the published bytes checked all 178 file hashes, sizes, and record counts,
the 83-entry static manifest, the raw rescore, 4 completed plus 1 pre-arm
failed plus 15 pending static IDs, and no receding data. The release is
evidence of a terminal FAIL, not an experimental PASS.
An independent reviewer also freshly downloaded the published asset and
verified its 178/178 full-manifest files, 83/83 static raw entries, source
identity, trial states, scorer, and final cleanup. Publication integrity
passed; the scientific final gate failed.

The R1 evidence PR remains draft and must not merge as a PASS. A new
versioned protocol, fresh eligible final seed matrix, independent review,
and separate evidence run would be needed before another final attempt.
