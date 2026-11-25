# Integrating EVOLVE work orders

Each implementation checkout belongs to one agent. Use `git worktree list` and check the owner’s working tree before making a fix. Start new work with `git fetch origin` and `git worktree add -b codex/wo-N ../evolve-wo-N origin/main`. Use a separate detached worktree from the fetched main for speculative merges. Leave shared branches, live experiment stores, archives and release pointers intact.

## November 14 merge queue

The audited base is `505c66b`, which includes WO-6 and WO-7 through PR #5. Land the integration checks first. The three implementation PRs have disjoint changed paths at their initial audited heads. The CI branch and WO-10 both edit the instrument API tests. WO-13 is in a separate worktree and shares the npm manifests, Playwright config, browser test directory and ignore file with CI. Reconcile the test command, browser suites and lockfile before its build, then exercise the hosted workspace against WO-12. Their runtime dependencies cross files.

| Order | PR and audited head | Handoff to check |
| --- | --- | --- |
| 1 | WO-8, #6, `4e783ab`, plus repair #9 at `e5f5cf4` | Immutable WO-6 context and profile pins → approved specification digest → compiled WO-7 recipe and fresh blank/job. Changes the shared settings validator in `factory/instruments/uvvis_contract.py`. The live worker must receive the exact reading fields and use frozen calibration for time courses. #9 corrects the contract that caused the first live candidates to be withheld. |
| 2 | WO-9, #4, `deca34e` | Planner candidate bytes, receipt, recipe digest and context → independent concentration/time-course verifier → immutable release manifest and scoped active pointer. Check a rejected candidate preserves the previous release. |
| 3 | WO-10, #7, `87f7b30` | Scheduler consumes the WO-8 approval, planner and acquisition services and the WO-9 verifier and release repository. Check FIFO leases, retry identity, blank reuse, timepoint job IDs, calibration identity and analysis with the verified release. Changes `factory/instruments/uvvis_adapter.py` and its API tests. |

## Before each merge

1. Fetch and record the current main and PR head SHAs. Inspect ancestry, the merge-base diff, changes to the same files, schemas and interfaces, outstanding reviews, and 8090 acceptance criteria. A revision to either SHA reopens verification.
2. Update the candidate by merging the latest main into its branch, coordinating with its owner, or rehearse its merge into the freshly fetched main in a detached worktree. Resolve incompatibilities on the owning branch with ordinary commits. Keep the PR open while checks fail. Never force-push.
3. Require **Scientific integration** and **Production build and browser regressions** on GitHub’s PR merge commit. Both jobs use the default pull-request checkout. They run the full Python suite, applicable composition, B12 replay and benchmark, retained EPR digest checks, the locked frontend production build and Chromium tests against its export. Run the same checks on a refreshed candidate whenever main advances.
4. Inspect the combined-tree results and any skipped tests. A scheduler candidate must run the real-service composition case. Record the exact base, head, CI run and remaining acceptance gaps. Obtain the repository owner’s explicit approval for this PR before merging. Keep auto-merge off.
5. Merge one approved PR, fetch the resulting main, verify the resulting tree and its push checks, then reassess the next PR. If the tree differs from the one tested, repeat the full verification.

## Actual workflow and 8090 acceptance

After WO-8, WO-9 and WO-10 are present, run `uv run --frozen python -m scripts.rehearse_experiments runs/integration-01` from the repository root on the authenticated presenter host. Choose a fresh directory for every attempt. This command drives a fresh concentration acquisition and a two-point time course through the production scheduler, real Codex generation, trusted verifier and loopback instrument. Use new empty application, release and instrument stores. Retain the approved digest, model/CLI receipt, release and source revisions, job IDs, raw readings, calibration link and analysis outcomes. A withheld result or rejected build is evidence to investigate. Never substitute the recorded candidate source or bypass verification to finish a demo. Run the B12 presenter rehearsal described in [the demo runbook](DEMO-RUNBOOK.md) and replay its exported evidence.

Record final main SHA, CI link, live run identifiers and pass/fail evidence for the applicable acceptance criteria on each 8090 Work Order. Leave unresolved work open and link its remediation. Advance status only when the final integrated evidence supports that order’s criteria. WO-11 through WO-14 have their own delivery scope.
