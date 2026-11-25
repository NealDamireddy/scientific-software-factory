# WO-45 implementation plan

Persist the existing Python context, run and release contracts in PostgreSQL, and implement the reviewed-domain storage protocols defined by WO-28, WO-31 and WO-37. Local stores remain the contract oracles.

## Code reuse and placement

Place the adapters and versioned SQL under factory/postgres. Reuse context validators, canonical encoders, digest functions, release manifests and owner-defined record types. Use psycopg as an optional hosted dependency. Keep the disposable cluster runner and storage contract tests under tests.

## Components and flow

1. Apply transactional migrations before opening repositories. Serialize expected-revision writes, validate instrument ownership and retain immutable project-to-lab pins. Store verified release bytes and promote the active pointer in one transaction.
2. Persist the RunStore journal and idempotent submissions. Lock a per-instrument queue row to serialize submission order, then claim only a ready head under SKIP LOCKED. Commit dispatch identity and instrument ownership together. Recover by looking up the existing key or polling its recorded job. Only a matching terminal outcome releases ownership.
3. Read the three owner branches as contracts become available. Persist their exact values and exercise their shared contract suites against hosted adapters in temporary composition.
4. Provide opt-in PostgreSQL tests with a private temporary cluster. Run local/hosted parity, competing submissions, stale writes, contention across instruments, cancellation, ambiguous dispatch, reopen, release rollback and historical reads. Run the relevant existing suites and review the branch diff.

## Verification commands

Run tests/fixtures/postgres/run.sh with the hosted dependencies and PostgreSQL binaries on PATH. Use Python unittest discovery for base regressions and invoke the same runner in a temporary tree containing the domain contracts.

## Reproduce the composed PostgreSQL check

From the repository root, create a temporary source copy from the verified WO-45 head. Overlay only the paths added under factory and tests by each owner. These commands use local Git objects and leave the checked-out branch alone.

```bash
set -euo pipefail
scratch=$(mktemp -d)
git archive HEAD | tar -x -C "$scratch"
for owner in 30167ad32e1c6b9a7b6abf6a4c27b4960ce95d2e 9cd1ff67431f940223d26ec0301629479efe7d5f 3fb322876737c27f55d80d574bfc149761a28e54; do
    git diff --name-only --diff-filter=AM d59d8e6 "$owner" -- factory tests |
        while IFS= read -r path; do
            mkdir -p "$scratch/$(dirname "$path")"
            git show "$owner:$path" > "$scratch/$path"
        done
done
cd "$scratch"
uv sync --locked --extra postgres --python 3.13
PYTHON="$scratch/.venv/bin/python" bash tests/fixtures/postgres/run.sh
```

PostgreSQL's initdb and pg_ctl must be on PATH. The runner creates and removes a socket-only cluster in a private temporary directory. In the isolated WO-45 checkout, four tests require the sibling domains. Composed runs execute every owner contract.
