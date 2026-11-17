# WO-45 review

## Round 1 · 313b7d1 · CHANGES_REQUESTED

Two independent delegates reviewed the branch from its merge base d59d8e6. The acquisition review found that malformed terminal times could release a lease and overlapping observations could overwrite newer progress. The repository review found that ReleasePlanner requires scoped historical release enumeration to avoid its local SQLite fallback. No additional blockers were reported in the domain ports, migrations or disposable test harness.

The fixes validate remote UTC timestamps, serialize observation and persistence per run, and index immutable releases by scope and insertion order. Regression tests exercise each case through the hosted repository or real planner.

## Round 2 · a48f5da · CHANGES_REQUESTED

The acquisition reviewer confirmed both prior fixes and identified a completed series lacking a start timestamp. The terminal check now requires both timestamps on completed series and retains the valid never-started cancellation path. The coordinator also requested the original seven context contract cases and runtime digest verification on read. Both are covered in the disposable suite.

## Round 3 · 7fecd98 · APPROVED

The acquisition reviewer approved the completed-series fix and the full acquisition bucket. The repository reviewer approved the repository bucket at a48f5da. Its files are identical at 7fecd98.

* AC-WEB-001.3 — historical context pins and immutable release bytes restore on reopen. The real planner discovers verified releases in project scope. The seven unchanged context contract tests pass against PostgreSQL.
* AC-RUN-001.1 and AC-RUN-001.2 — concurrent claimers preserve FIFO per instrument, skip locked heads across instruments, and require an exact approved spec, verified recipe and calibration. A forced run-write failure rolls back lease creation.
* AC-RUN-001.7 — a worker process exits abruptly after the fake instrument accepts its original key. The restarted worker retrieves the job and confirms its outcome before releasing the instrument. Concurrent observations, cancellation and malformed terminal data have regression coverage.
* WO-28, WO-31 and WO-37 — the 36-case composed PostgreSQL run passed with zero skips, including the actual owner suites. Owner revisions and reproduction commands are in the plan. Immutable runtime records verify their canonical SHA-256 on read.
* Independent SQL inspection after claim, cancellation and repository reopen showed the first run dispatching with its lease and the second queued without a lease.
* uv lock --check --offline and git diff --check passed. The coordinator published the verified branch after the user approved publication.
* Full isolated-branch regression with disposable PostgreSQL 16.2 and the loopback scientific simulator: python -m unittest discover -s tests -v ran 291 tests in 88.725s. 287 passed and four sibling-domain tests skipped. The composed run above exercised those domains.
