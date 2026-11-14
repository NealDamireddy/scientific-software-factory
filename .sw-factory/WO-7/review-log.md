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
