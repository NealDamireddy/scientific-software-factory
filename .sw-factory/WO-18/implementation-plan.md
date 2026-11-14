# WO-18 implementation plan

The trusted adapter binds the lifecycle of each simulated acquisition to the instrument, profile revision, profile digest and requested job. Keep the v1 wire format readable for existing clients and durable jobs. Keep the scheduler's distinction between a definitive rejection and an untrustworthy successful submission.

## Code and flow

1. Use the v1 response schemas and configured pins in factory/uvvis_adapter.py. Validate returned identity before exposing a job, blank or reading. Compare measurement envelope and individual records with the requested ID. Establish pin identity even for empty partial results. For unknown submissions, preserve reconciliation by the original idempotency key.
2. Establish ownership by reading the requested job before sending cancellation. Include pins with the POST so factory/uvvis_http.py can confirm the live service and durable job match before performing the side effect. Keep existing bodyless clients working. Use the complete canonical pin digest on each job-route request so a replacement service cannot answer with an original instrument’s historical job. Old v1 servers reject this qualified target before mutation. Share pin_sha256 in the v1 contract module. No schema, database or scheduler migration.
3. Enforce a single monotonic body-read deadline, exact declared length and the existing 64 KiB limit before dispatch. Preserve service cleanup, thread joining and loopback origin validation.
4. Use dedicated identity, timeout and scheduler integration tests. The adapter and HTTP delegates own distinct production/test files. The lead owns scheduler integration coverage and execution records. An independent reviewer assesses both boundaries.

## Verification

- Run the new lifecycle and deadline regressions against the pinned production code first. Save failing output. Exercise the real HTTP server with correct and mismatched adapters, incomplete bytes, a held-open client and post-shutdown lock reacquisition.
- Exercise a saved-context scheduler through a real adapter with an accepted but unverifiable response. Restart with the stored dispatch key and compare actual simulator job rows. Run the existing UV–Vis API/profile, saved-context, scheduler, time-course and composition suites.
- Compile Python, inspect diff, run the supported Python regression suite, and collect lane PR CI. Repeat saved-context acquisition, scheduler reconciliation, composition and full integration gates on the combined WO-15–19 checkout. WO-14 is deferred.
