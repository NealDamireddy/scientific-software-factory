# Lab Factory core and reviewer workflow

Updated November 27, 2026. The original review used `62badef`. The integrated branch includes the shipped web UI and backend from `main` at `10bad3f`. The [architecture design](../specs/2026-11-25-lab-factory-architecture-design.md) describes the original core. This checkout also includes hosted review, pinned references, and analysis workers.

## Existing behavior to preserve

| Capability | Baseline evidence |
| --- | --- |
| Canonical units, immutable lab and experiment revisions, and compatible pins at order creation | `tests/test_units.py`, `tests/test_context.py`, `tests/test_store.py`, `tests/test_workorders.py` |
| Structured commands, rendered settings, and unique citation resolution across both pinned records | `tests/test_artifacts.py`, `tests/test_checks.py` |
| Single-winner claims, numbered submissions, rejection history, and exact-artifact approval under current checks | `tests/test_workorders.py`, `tests/test_cli.py` |
| Four worker tools and the complete claim, correction, review, and release flow over stdio | `tests/test_agent.py`, `tests/test_mcp_stdio.py` |
| Hosted reviewer access, worker authentication, and analysis-specific checks | `tests/test_hosted_portal.py`, `tests/test_hosted_mcp.py`, `tests/test_tabular_acceptance.py` |

The local CLI trusts its operator. A private hosted deployment authenticates a named reviewer. The shared demo attributes decisions to one public identity. An artifact digest identifies exactly what was approved. Scientific judgment and attribution to an individual depend on the reviewer and deployment.

### Numeric expressions in procedure notes

The procedure matcher recognizes digits with an optional decimal fraction, optional whitespace, and a unit token. A letter immediately after the token prevents a match, so `2 steps` remains ordinary prose. Examples include `550nm`, `25 °C`, and `5 minutes`. The case-sensitive symbols are `nm`, `um`, `uL`, `mL`, `L`, `ms`, `s`, `min`, `h`, `K`, `degC`, `mT`, `G`, `T`, `AU`, `°C`, `µL`, `μL`, `µm`, and `μm`. The matcher also accepts singular and plural forms of nanometer, micrometer, microliter, milliliter, liter, millisecond, second, minute, hour, and hr. Additional words are sec, mins, kelvin, celsius, gauss, tesla, and millitesla. Spelled-out units match case-insensitively. A reviewer still evaluates free-text notes and hand-measured amounts.

## Abandoned claim recovery

An operator can return an in-progress order to the queue with a reason. The local CLI and hosted reviewer workflow must identify the claim being acted on, so a stale review cannot release a subsequent claim. Preserve the order ID, both pinned revisions, submission numbering and history. Record the reviewer, previous worker and reason atomically. A replacement identity can claim and submit. A late submission by the former worker must fail without adding a submission or event. Recovery remains a reviewer action. Workers retain the four existing MCP tools. A worker captures its claim ID before starting work and submits that ID with the result. If the same identity returns after displacement, a delayed submission carrying the old ID or omitting the ID after a manual requeue must fail without a state change. Preserve compatibility for legacy clients whose identity has a single unambiguous claim.

Verify recovery both before the first submission and after failed checks. Exercise wrong-state and stale requests, persistence on reopen, and a race between recovery and a passing submission. Confirm that hosted access uses the existing reviewer policy. The portal displays the age and UTC start time of the active claim. The reviewer decides when to recover it.

Rejection reopens an order for revision. For an untagged retry, compare the incoming artifact digest with artifacts previously rejected for that worker on that order. A match leaves the order, submissions and history intact. A changed artifact from a legacy client remains eligible for the normal checks. A submission explicitly bound to the current claim can intentionally repeat the original artifact. Untagged content changes alone cannot establish which claim produced them.

## Pinned citation lookup

A local reviewer can run `labfactory --db PATH wo citation ORDER DOCUMENT_ID` to inspect a document from the exact lab or experiment revision pinned to the order. Show the origin, record ID and revision, document ID, kind, title, source and full stored text. Use the same unique-resolution rule as procedure checks. An unknown or ambiguous citation fails clearly. Reading a citation must leave order state and history intact.

Verify lab and experiment documents through the CLI after updating both source records. Exercise unknown and colliding IDs, a missing order, and reopening the database. Link the command from the reviewer quickstart.

## Independent delivery and integration

Use the same committed baseline for four isolated checkouts. One implementer and one verifier own each feature. Each verifier writes behavioral acceptance cases against the plan and demonstrates the missing behavior on the baseline before receiving the implementation. Use disposable databases, separate working directories and fresh processes. Run each verifier's cases against its candidate, then run both sets and the package suite against the integrated branch. Keep the working checkout and its uncommitted changes intact.

## Verification record

| Question | Independent result |
| --- | --- |
| Can workers edit a neighboring checkout? | Each of the four workspace-write sandboxes permitted a local write and denied a write to a neighboring checkout. |
| Does lookup keep the original evidence? | All six CLI cases in `test_citation_lookup_acceptance.py` failed against the baseline. They passed after implementation, including different pinned lab and experiment revision numbers, later edits, a collision and a database reopen. |
| Can a reviewer recover work and preserve its history? | Eight cases in `test_claim_recovery_acceptance.py` failed against the baseline. Its existing MCP access check already passed. The completed recovery tests exercise the audit event, original pins, failed submissions, a different replacement worker and a race with a passing submission. |
| Can delayed work cross a same-identity reclaim after manual requeue? | The verifier reproduced acceptance of stale tagged and untagged payloads in the first implementation. Both are refused by the repaired server. A current tagged payload and a legacy first claim still pass. The original successful-reclaim case now supplies the replacement's saved ID. The four regression cases are in `test_claim_generation_acceptance.py`. |

During PR review, two additional cases failed on the port to `main`. An untagged retry reinstated a rejected artifact, and an ineligible prebuilt upload acquired a claim before failing. The focused regression suite is in `tests/test_review_followup.py`. The uploader now checks eligibility inside the claim transaction, and submission checks the digest again before writing.

From `lab-factory/`, run `uv run --locked pytest tests -q` to repeat the package checks. The portal recovery flow was also exercised in Chromium against a disposable local deployment.
