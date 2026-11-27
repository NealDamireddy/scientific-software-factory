# Lab Factory core and reviewer workflow

Updated November 27, 2026. Implementation baseline: `62badef`. The [architecture design](../specs/2026-11-25-lab-factory-architecture-design.md) describes the original core. This checkout also includes hosted review, pinned references, and analysis workers.

## Existing behavior to preserve

| Capability | Baseline evidence |
| --- | --- |
| Canonical units, immutable lab and experiment revisions, and compatible pins at order creation | `tests/test_units.py`, `tests/test_context.py`, `tests/test_store.py`, `tests/test_workorders.py` |
| Structured commands, rendered settings, and unique citation resolution across both pinned records | `tests/test_artifacts.py`, `tests/test_checks.py` |
| Single-winner claims, numbered submissions, rejection history, and exact-artifact approval under current checks | `tests/test_workorders.py`, `tests/test_cli.py` |
| Four worker tools and the complete claim, correction, review, and release flow over stdio | `tests/test_agent.py`, `tests/test_mcp_stdio.py` |
| Hosted reviewer access, worker authentication, and analysis-specific checks | `tests/test_hosted_portal.py`, `tests/test_hosted_mcp.py`, `tests/test_tabular_acceptance.py` |

The local CLI trusts its operator. A private hosted deployment authenticates a named reviewer. The shared demo attributes decisions to one public identity. An artifact digest identifies exactly what was approved. Scientific judgment and attribution to an individual depend on the reviewer and deployment.

## Abandoned claim recovery

An operator can return an in-progress order to the queue with a reason. The local CLI and hosted reviewer workflow must identify the claim being acted on, so a stale review cannot release a subsequent claim. Preserve the order ID, both pinned revisions, submission numbering and history. Record the reviewer, previous worker and reason atomically. A replacement identity can claim and submit. A late submission by the former worker must fail without adding a submission or event. Keep recovery outside the four worker MCP tools.

Verify recovery both before the first submission and after failed checks. Exercise wrong-state and stale requests, persistence on reopen, and a race between recovery and a passing submission. Confirm that hosted access uses the existing reviewer policy.

## Pinned citation lookup

A local reviewer can run `labfactory --db PATH wo citation ORDER DOCUMENT_ID` to inspect a document from the exact lab or experiment revision pinned to the order. Show the origin, record ID and revision, document ID, kind, title, source and full stored text. Use the same unique-resolution rule as procedure checks. An unknown or ambiguous citation fails clearly. Reading a citation must leave order state and history intact.

Verify lab and experiment documents through the CLI after updating both source records. Exercise unknown and colliding IDs, a missing order, and reopening the database. Link the command from the reviewer quickstart.

## Independent delivery and integration

Use the same committed baseline for four isolated checkouts. One implementer and one verifier own each feature. Each verifier writes behavioral acceptance cases against the plan and demonstrates the missing behavior on the baseline before receiving the implementation. Use disposable databases, separate working directories and fresh processes. Run each verifier's cases against its candidate, then run both sets and the package suite against the integrated branch. Keep the working checkout and its uncommitted changes intact.
