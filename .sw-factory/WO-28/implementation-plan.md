# WO-28 implementation plan

## Summary

Persist lab-private catalog, source and integration evidence streams in SQLite. Each revision binds the caller identity, predecessor, creation time and canonical content digest. A separate human receipt approves an exact catalog head.

## Code reuse and package structure

Use factory.context_repository.canonical_json and RevisionConflict, factory.context.digest, and the temporary-store unittest pattern from tests/test_context_repository.py. Put the public protocol and records in factory/catalog_contract.py, structural validation in factory/catalog_validation.py and SQLite transactions in factory/catalog_repository.py. Publish portable cases in tests/test_catalog_contract.py and fixtures under tests/fixtures/catalog_examples.py. Bind the contract to SQLite and exercise migration invariants in tests/test_catalog_repository.py.

## Components and flow

A trusted principal authorizes an action on the owning lab before repository lookup. The repository stores validated content and exact same-lab source citations. The curation service supplies scientific judgments. Catalog pins retain revision identity and digest across later edits and approvals. Evidence stores independent test facts separately from documented claims.

## Steps

1. Commit the protocol, record and payload shapes, example inputs, portable suite entry point and migration rules for WO-45.
2. Add structural validation and an additive catalog-only migration. Serialize revision comparisons, source checks and writes in one transaction. Bind approval to the current exact pin and preserve earlier receipts.
3. Exercise authorization, history, evidence origins, concurrent requests, durable pins and startup against a shared file. Record review and hand off one PR to main.

## Testing

Run the portable suite against a fresh SQLite file per test, reopen independent repository instances, race writers, try denied and forged inputs, and verify source and evidence corrections. Exercise migration rollback, shared database coexistence and SQL immutability in SQLite-specific tests. Run project-compatible unittest discovery and inspect a manual reopen/read of an approved revision.

## WO-45 adapter handoff

CatalogRepository in factory/catalog_contract.py defines the entire callable surface. The three fresh payload factories in tests/fixtures/catalog_examples.py show the wire-independent JSON records. Catalog claims may omit citations or record unresolved gaps while in draft. Source references identify a document revision or an ISO access date, and claims pin exact source revision IDs. CatalogRecord.approval is read from a separate immutable receipt. Passing the previous catalog pin to get by lab/kind/record ID and revision retrieves the original ID, digest, contents and decision.

Run tests/test_catalog_contract.py by inheriting CatalogRepositoryContract and unittest.TestCase, assigning open_repository to a zero-argument factory backed by a fresh isolated store for each test. Reopening must preserve data and permit independent concurrent writers. SQLiteCatalogRepository(db_path) in factory/catalog_repository.py will implement the protocol. Version 1 creates catalog_schema_version, catalog_revisions and catalog_approvals atomically, and leaves the global user_version and other domains alone. Hosted schema layout is adapter-owned. Preserve the same lab/stream/revision uniqueness, receipt binding, immutable history and atomic conflict semantics.

Hosted adapters can subclass CatalogDomainRepository in factory/catalog_domain.py and implement only _transaction(kind, lab_id, record_id, *, write), yielding a CatalogTransaction. Its five methods read a revision or head, return ordered history, check exact same-lab source existence, append a revision and insert a receipt. The write context must serialize a stream before reading its head, including simultaneous creation of an absent stream. The base class owns authorization, input validation, pins, timestamps, stale-write detection, human receipt policy and retry semantics.
