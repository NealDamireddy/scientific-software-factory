# WO-31 implementation plan

## Summary

Persist immutable scientific evidence, intent, design, specification revisions and human decision receipts. Preserve the exact scoped predecessor and references on each revision.

## Code reuse and placement

Use factory.context_repository.canonical_json and RevisionConflict and factory.context.digest. Follow the connection-per-operation SQLite pattern. Put the public protocol and record shapes in factory/scientific_artifact.py, with the adapter and migration under the same scientific_artifact prefix. Keep reusable behavioral assertions in tests/fixtures/scientific_artifact_contract.py and run them through tests/test_scientific_artifact_repository.py.

## Components and flow

Trusted services supply an authenticated principal. Each method checks the requested scope and required action before lookup. The write transaction compares the expected revision, verifies exact pins, and appends the authored revision plus any dependent blueprint reconciliation markers. A decision transaction binds a human receipt to the exact current specification. Reads return scoped immutable history, current decision state, receipts and markers. Validation and decision eligibility belong to upstream callers.

## Steps

1. Commit the public protocol, digest convention, adapter fixture and migration contract for hosted integration.
2. Implement domain-local SQLite versioning and append-only storage. Serialize competing edits and reject stale expected revisions or decisions.
3. Exercise contract, restart, failure and contention paths. Review the branch diff, verify the scoped and existing tests, and open the individual PR.

## Testing

Use unittest with an adapter-construction callable and fixture principals. Assert exact provenance, immutable history, draft state, stale edits, scoped denial, bad pins, retained decisions and reconciliation through a fresh repository object. Check SQLite migration composition and competing writers. Manually inspect the callable API on a temporary database. Run the repository Python suite with its pinned dependencies.
