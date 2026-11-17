# WO-37 implementation plan

## Summary

Store ordered, append-only records per scoped work order. A shared Python domain layer validates transitions before a storage adapter atomically compares and appends at the expected stream version.

## Code reuse and placement

Use canonical_json and RevisionConflict from factory/context_repository.py and digest from factory/context.py. Place the public contract, shared transition logic and local adapter in factory/runtime_work_order*.py. Place shared adapter behavior and local database checks under tests/test_runtime_work_order*.py with a JSON fixture in tests/fixtures/.

## Components and flow

Callers supply a trusted principal and exact lab/project/order scope on every call. The repository checks the action, compares the command with prior idempotency receipts, validates pins and predecessors against current history, and appends one record under a unique scope/version constraint. Snapshots and decisions carry exact digests. Recovery writes an interrupted state for an identified uncertain attempt using the same concurrency guard. Services own dispatch, review and decision eligibility.

## Steps

1. Publish the Python signatures, command shapes, fixture construction and migration expectations.
2. Implement shared validation, state transitions and the local SQLite adapter.
3. Exercise reopen, retry and concurrency behavior against clean and shared database paths. Review the full branch against the linked requirements.

## Testing

Run the repository contract through unittest with a temporary SQLite file and fresh connections. Verify canonical digests, idempotency, pin changes, terminal history, human attribution, scope denial and atomic claims. Check migration rollback/coexistence and run the existing Python suite where supported. Inspect a persisted order through a separately opened repository.

## Coordinator review follow-up

Rebuild the record table under SQLite schema version 2 using WITHOUT ROWID. Verify both fresh and upgraded files reject explicit hidden-rowid replacement. Exercise rollback after a populated version-1 history has been copied, then retry and compare the original records and their digests.
