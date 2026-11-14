<!--lint disable strong-marker-->

# Review Log: WO-7

**Work Order:** WO-7 — Expose the virtual UV–Vis instrument API and adapter
**Initialized At (UTC):** 2026-11-14T18:15:33Z

This file records review and verification rounds. Append new rounds; do not overwrite prior rounds.

---

## Round 1

The lead reviewed the HTTP client and tests. Two input-boundary issues required changes. Poll, cancel and measurements interpolated caller-supplied IDs into paths. Idempotency keys admitted characters outside the HTTP header encoding. A privacy test searched timestamps for the text of a private concentration and could fail nondeterministically. The lead also exercised the combined worktrees with the real loopback service and obtained 12 measurements at the saved project's 650 nm.

**Verdict** CHANGES_REQUESTED

## Corrections

The adapter checks each job ID against the service's 32-hex format before building a path. Both sides now apply the same printable-ASCII submission-key rule. Regression cases cover all three job operations, malformed keys and direct service validation. The privacy assertion checks the private field names and the public schema restricts all record fields.

## Round 2

The lead independently reviewed the service, adapter, HTTP API, versioned schemas and tests, and verified the fixes from round 1. Review covered both linked requirements, instance and profile matching, compatible references, private models, durable job exclusivity, idempotency and public measurement structure. The HTTP server binds to loopback and rejects foreign hosts and origins. The private sample file is available only to the simulator.

All 58 cases in the standalone Python unittest suite passed, including the existing B12 checks. The lead independently ran all six UV–Vis cases and verified an actual process crash after the first replicate. Reopening the store returned the same interrupted job, with one incomplete reading retained and no duplicate acquisition.

The combined local components reopened the project and acquired 12 records at its pinned 650 nm, including three unknown replicates. The work orders assign approval and recipe compilation to WO-8.

The combined test suite passed all 67 cases. Fresh job `36d94e40fc964d8d97f76c3304b27707` produced the 12 records above. The B12 replay returned 32.006829774391655 mg/L for the follow-up, with hold-out benchmark MAE 0.00554009 mg/L. PR #3 is linked on the In Review work order.

**Verdict** APPROVED
