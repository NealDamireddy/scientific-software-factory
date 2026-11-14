# WO-13 implementation plan

## Summary

Add a researcher workspace at /workspace/ alongside the existing B12 and EPR archives. The page consumes project-scoped workspace responses in explicit fixture or live mode.

## Code reuse and package structure

Use the existing Next.js static export, Instrument Sans and archive routes. Place the client, isolated fixture adapter, context/specification editor, run views and route styles together in app/workspace. Reuse the WO-6 context fixture and align field names with WO-8 specification/approval, WO-9 verified results and WO-10 run timing. Add browser acceptance checks under tests and a package test command.

## Components and flow

A project/session-scoped client loads immutable context and specification histories plus recorded runs. The editor sends expected revisions and approval digests through this boundary. Run views render server-supplied states, timings, release identities and withheld results. Evidence is requested through the same client. Access denial resets the project view. Read failures retain the last snapshot with its timestamp. Switching project or mode unmounts the former scope. Fixture data stays in an isolated browser session and never uses shared services.

## Steps

1. Define versioned operations, error envelopes, credentialed live transport and an isolated fixture adapter.
2. Build structured context and specification editors with explicit confirmation, immutable revision selection and operation feedback.
3. Present independent run stages, recorded wait, provenance and scientific results with authorized downloads. Integrate project/session navigation, refresh and empty states.
4. Exercise both adapters in browser tests, run existing regressions and production export, then record review and delivery evidence.

## Testing

Use production-export browser checks with isolated fixtures and intercepted live HTTP responses for denial, revision conflicts, stale snapshots, evidence, session changes and archive links. Test both experiment types and malformed or withheld measurements. Run Python regression discovery and compare any sandbox failures against the documented runtime requirements. Real authenticated smoke tests depend on WO-11/12 service availability.

## Follow-up verification of immutable specification context

Resolve historical project revisions by their full reference, then use the lab and instrument recorded for that revision. Preserve the original specification context on edits, approvals and submissions, including when older fixture records already exist. Selecting another context starts a separate specification. Verify identical project payload digests across different revisions, forged requests, new IDs and the approval status of both revisions through the fixture and Chromium.

## Producer-conformance audit

Compare the fixture against complete WO-6 context, WO-8 specification/approval and frozen calibration records, then reproduce discrepancies through the API boundary and Chromium. Capture reproducible producer fixtures, test read-only digest projections, exercise duplicate instrument and unresolved draft handling, and verify preview source identity against a real preview-mode build. Recheck the original WO-13 acceptance criteria, record remaining upstream dependencies, run the combined suite and monitor the published PR checks.
