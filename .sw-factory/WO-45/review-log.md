# WO-45 review

## Round 1 · 313b7d1 · CHANGES_REQUESTED

Two independent delegates reviewed the branch from its merge base d59d8e6. The acquisition review found that malformed terminal times could release a lease and overlapping observations could overwrite newer progress. The repository review found that ReleasePlanner requires scoped historical release enumeration to avoid its local SQLite fallback. No additional blockers were reported in the domain ports, migrations or disposable test harness.

The fixes validate remote UTC timestamps, serialize observation and persistence per run, and index immutable releases by scope and insertion order. Regression tests exercise each case through the hosted repository or real planner.
