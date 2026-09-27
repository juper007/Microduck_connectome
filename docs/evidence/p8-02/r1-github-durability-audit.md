# P8-02 R1 GitHub durability audit

Status: **BLOCKED_ON_THOR** for a GitHub-only P8-02 R1 gate decision. This audit does not rescore or rerun any D/B trial. Primary role: `$microduck-pm-architect` for gate sequencing, with `$experiment-evaluation-scientist` for the fixed evidence contract. An independent `$independent-phase-reviewer` examined the GitHub state separately.

## Input state and finding

- Fetched `origin/main`: `c31da4d75574be6942956315a997057a019860d7`.
- Merged PR #76 head: `082de9bc142f7d11de95bf5a32ba71fdd0068046`; execution source named in its message: `4fc5a818249ee1fae4a603fa770beffd825fe967`.
- The evidence commit has the same file tree as that execution source. Its 3/3 D, 19/20 B, and zero-safety statements are in the commit message and PR description, without the D/B raw ledgers, journals, manifests, scorer outputs, or final down/port probes in GitHub.
- PR #76 says exact-head independent review is pending. GitHub has no review or comment recording one. Its PR description cites Thor-local evidence paths only.
- No P8-03 or later final-stage evidence is committed at this base.

The reported results are **unverified, not recoded as FAIL**. The R1 remediation protocol requires raw-derived recomputation, manifest agreement, and independent exact-head review before P8-03. A merged PR alone does not establish this gate. P8-03 final seeds, P8-04, final regression, and G8 remain blocked in this GitHub-only audit. Do not repeat B trials or select replacement seeds to resolve an evidence-access gap.

## Thor evidence transfer and gate recovery

Preserve the existing Thor roots unchanged:

```text
/home/juper007/projects/microduck-connectome-thor/evidence/p8-v2-final/p8-02-r1-no-seed-gate-v1/
/home/juper007/projects/microduck-connectome-thor/evidence/p8-v2-final/p8-02-r1-development-v1/
/home/juper007/projects/microduck-connectome-thor/evidence/p8-v2-final/p8-02-r1-approach-v1/
```

On Thor, first inventory and package **all three existing directories** without modifying their contents. Run from the frozen parent directory:

```bash
cd /home/juper007/projects/microduck-connectome-thor/evidence/p8-v2-final
tar -czf /tmp/p8-02-r1-evidence-v1.tar.gz p8-02-r1-no-seed-gate-v1 p8-02-r1-development-v1 p8-02-r1-approach-v1
sha256sum /tmp/p8-02-r1-evidence-v1.tar.gz
```

Publish the archive in a durable GitHub location accessible to an independent reviewer, record its SHA256, byte size, exact URL, all three source-directory names, and the execution source/config/upstream hashes in a new evidence PR. If GitHub rejects the archive size, use a GitHub release asset or another repository-approved immutable GitHub artifact with the same recorded checksum. Do not replace or edit the Thor raw directories. The reviewer must download the bytes, verify the archive checksum and each raw-manifest entry, independently run the R1 scorer against both D and B ledgers, inspect the no-seed gate and final simulator down/port probes, reconcile every D/B ID and failure, and review the final evidence PR head. Record the verdict and reviewed head SHA durably. Only a verified PASS and merged evidence PR unlock P8-03.

## Handoff

- Task: P8-02 R1 GitHub durability audit; input/base `c31da4d75574be6942956315a997057a019860d7`.
- Context: AGENTS.md, P8-V2 final protocol, P8-02 R1 remediation protocol, completion criteria, Git workflow, PR #76 and its Git tree/reviews only. No Thor-local or uncommitted evidence used.
- Seeds/config: no new trials; frozen D00-D02 and B00-B19 remain as registered.
- Safety/science: no runtime or threshold change; no claim of biological superiority.
- Next owner: Thor evidence custodian, then a separate `$independent-phase-reviewer` at the evidence PR's exact final head.
- Gate: BLOCKED_ON_THOR pending accessible raw evidence and independent review; P8-03 is not authorized as a final-stage execution yet.
