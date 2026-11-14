# WO-6 implementation plan

## Summary

Persist validated lab and project payloads as immutable SQLite revisions. Each new project revision pins the lab revision used to validate its instrument.

## Code reuse and package structure

Use the existing Draft 2020-12 validator dependency, registry layout and JSON reader/digest helpers in factory/context.py. Preserve the static EPR resolver and legacy B12 profile. Add the shared profile schema and public profile under registry/, a context input schema there, a SQLite repository module under factory/, and public fixture payloads under fixtures/context/. Put repository contract tests in tests/test_context_repository.py.

## Components and flow

ContextRepository defines save_lab, save_project and get. SQLiteContextRepository runs versioned migrations, validates the public payload and resolves ownership during an immediate write transaction. Expected revision zero creates an entity. A mismatch raises RevisionConflict before an append. Each ContextRevision carries an immutable ID, scope, revision, payload and canonical SHA-256. Project revisions record their exact lab revision and digest. The instrument instance is contained in its owning lab's versioned inventory and refers to the shared public profile by ID and digest.

## Steps

1. Publish the instrument profile, schemas and public lab/project fixtures.
2. Implement transaction-scoped ownership validation, revision checks, append-only storage and historical lookup.
3. Exercise contracts through the public repository API, including concurrent writers and database reopen.
4. Hand the fixture and repository API to the integration reviewer. Record verification and the PR in the work order.

## Testing

Run the new unittest contract suite with temporary SQLite databases and the existing B12 regression. Independently exercise project revision 1 at 650 nm after saving revision 2 at 450 nm. The parent acceptance pass combines this repository and the WO-7 loopback adapter in an isolated checkout. Production approval and recipe compilation belong to WO-8.
