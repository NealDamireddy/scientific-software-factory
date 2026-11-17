#!/usr/bin/env bash
# Run from the repository root with initdb, pg_ctl and Python + the postgres extra on PATH.
set -euo pipefail
cluster=$(mktemp -d /tmp/evolve-pg.XXXXXXXX)
cleanup() {
    if [[ -f "$cluster/data/postmaster.pid" ]]; then
        pg_ctl -D "$cluster/data" -w -m immediate stop >/dev/null
    fi
    rm -rf "$cluster"
}
trap cleanup EXIT
initdb -D "$cluster/data" --username=evolve --auth=trust --encoding=UTF8 --no-locale >/dev/null
pg_ctl -D "$cluster/data" -l "$cluster/server.log" -o "-h '' -k '$cluster'" -w start >/dev/null
export EVOLVE_TEST_POSTGRES_DSN="host=$cluster dbname=postgres user=evolve"
"${PYTHON:-python3}" - <<'PYTHON'
import unittest

suite = unittest.defaultTestLoader.discover("tests", pattern="test_postgres*.py")
result = unittest.TextTestRunner(verbosity=2).run(suite)
if not result.wasSuccessful() or result.skipped or result.testsRun < 37:
    raise SystemExit(
        f"PostgreSQL contracts require at least 37 tests and zero skips. "
        f"Ran {result.testsRun}, skipped {len(result.skipped)}."
    )
PYTHON
