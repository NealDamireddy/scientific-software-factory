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
