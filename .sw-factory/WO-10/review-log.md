# WO-10 review log

Base: main. Review scope: scheduler/store and standalone tests; approved acquisition and software adapters, scheduled time-course and composition tests; WO-7 HTTP response classification and regression; operator documentation and execution records.

## Round 1 — CHANGES_REQUESTED

Independent review found that cancelled runs could retain their FIFO position after a busy response, and that a dead worker could leave a cancelled attempt marked running. The measurement gate needed to reject mixed job IDs and the analysis writer needed to reject non-JSON values before attempting persistence. Two concurrent runs sharing a preparation task could misinterpret a claim in progress as a failed build. A fresh concentration fit using a prior blank needed a new calibration ID. Finally, a malformed HTTP success could be misclassified as an authoritative rejection after the instrument had already started acquiring.

## Round 2 — fixes and verification

- Scheduler/store: retire cancelled queue heads and abandoned worker attempts under process locks. Validate measurement identity/count and finite result JSON. Persist first-dispatch intent before external I/O, so restarts cannot treat preflight failures as proof of no remote job.
- Preparation/release: follow contested planner claims and recover an interrupted attempt with a new receipt; require a verifier before handing off candidates. Recheck calibration identity/digest and release compatibility at analysis time. A repeated fit retains the approved blank but has its own ID and digest.
- Time-course/HTTP: persist each point before dispatch, resume by original key or known identity and use actual point starts. Treat unreadable successes as uncertain. A live malformed 202 followed by a retry recovered the same remote job.
- Independent delegates reviewed the scheduler/store, production adapters and time-course/HTTP boundaries; blockers were reproduced and retested. No simulator storage writes, executable candidate imports, frontend or hosted deployment changes. Sandbox execution and project-scoped immutable release loading remain owned by WO-9.
- Manual status probe with a controlled clock: completion at t=4, inspection at t=11 with build still running returned acquisition=completed, analysis=pending, software_wait_s=7, software_wait_pending=true and “Waiting for a compatible verified release”.
- Scope: RUN-001.1–7 and RUN-002.1–3. Strict FIFO and per-instrument lease, concurrent software preparation, automatic analysis, independent acquisition during analysis, missing dependencies, cancellation and process death are covered by standalone behavioral tests. Frontend staleness and evidence export are outside this work order.

## Acceptance evidence

Development base: 505c66b. Integration inputs: WO-8 at 5c7592bd2dd1929d38f21122c548c3c4b7f1d6e5 and WO-9 at 7763601ab7228401d74086351486015839cfff90. The dependency changes were applied to a disposable checkout; they are not vendored in this PR.

- Branch regression: `python -m unittest discover -s tests -v`: 94 discovered; 93 passed. The single composition case requires both open dependency PRs and was executed separately with them present. The branch suite includes 16 scheduler tests, 4 series tests, legacy B12/EPR, UV–Vis HTTP, replay and sandbox coverage.
- In the composed checkout, the concentration release analyzed 12 fresh readings; its frozen calibration was then used by the time-course release for 6 readings over two real HTTP jobs. A repeat concentration run reused the verified source and original blank but obtained a new calibration ID. The final reproducible test is tests/test_experiment_composition.py. See composition-receipts.json for run, release and remote identities and the actual UTC timestamps from one observed execution. These are test receipts from temporary local stores, not an exported replay bundle or a live model-generation claim.
- In that execution the measured software waits were 1.883457 s, 0.718928 s and 0 s, respectively. The late-build regression independently checks elapsed wait before as well as after readiness.
- An initial attempt to run two full suites concurrently collided on WO-7's host-wide test instrument lock. Regressions were rerun sequentially without weakening instrument exclusivity.
- The full combined suite and focused composition checks use loopback HTTP and macOS Seatbelt. No frontend code or build configuration changed.

- Final combined regression on the implementation commit: **122 passed, zero skipped** (72.420 s). The same 16 scheduler cases also passed directly on the branch.

Independent review verdict: **APPROVED**.
