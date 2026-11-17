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
"${PYTHON:-python3}" -m unittest discover -s tests -p 'test_postgres*.py' -v
