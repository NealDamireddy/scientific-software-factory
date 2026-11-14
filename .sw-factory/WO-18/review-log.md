# WO-18 engineering review

## Round 1 — changes requested

The independent reviewer checked both production boundaries and the three dedicated tests. The adapter delegate also cross-reviewed the server's cancellation critical section. On the first implementation a service replacement between successful preflight and the unqualified job GET could return a copied historical job with the original pins. A real second service recovered the copy as interrupted while the owner still reported running (job 8b1794c7f86149e18b27f4e706823349). The adapter accepted an empty historical measurement envelope in a second probe. A pre-WO-18 server would also ignore a JSON body sent to its original cancellation URL.

**Finding:** The historical job identity does not establish the identity of the service that produced the reply. A false terminal state could release the FIFO lease. Require a producer precondition on the exact HTTP request doing the work, including cancellation. Keep the old route usable for existing clients. Tests should exercise a different live service that holds a copied job database, plus downgrade rejection before mutation.

**Verdict:** CHANGES_REQUESTED.

## Round 2 — independent engineering review

The reviewer approved the production and regression files in commit `60b964aedaa62a025061c0864a2ee0485b51ab20` and checked the mixed-version probe. Their independent loopback run used Unicode instrument IDs. Service B reopened a copy of A's job `5d943ea5304f493fa5dffc8b2b932fc9`. Each guarded operation returned HTTP 409 when B served the final request. A remained running and B's historical job remained interrupted. The handler checks the supplied precondition using the service that actually handles the request. The production adapter verifies returned job/record fields, blank, sample membership and replicate identity. The HTTP body reader enforces one deadline across partial reads.

The lead exercised actual versions in separate processes. The old server returned 404 for the updated cancellation preflight and for the guarded POST itself. The old owning adapter then polled the same job and observed running. Against the updated server, the original unqualified v1 client acquired, polled, cancelled and retrieved incomplete measurements. See `mixed-version.log` and rerun `python .sw-factory/WO-18/check_compatibility.py` from a checkout containing the pinned commit.

### Wire contract and rollout

The updated adapter appends `?pin_sha256=<64 lowercase hex>` to `GET /v1/acquisitions/{id}`, `GET /v1/acquisitions/{id}/measurements` and `POST /v1/acquisitions/{id}/cancel`. Hash the UTF-8 canonical JSON object containing schema_version, instrument_id, profile_id and profile_sha256 using SHA-256. Canonical serialization uses sorted keys, no insignificant whitespace and unescaped Unicode. The digest is an identity precondition, not a credential. The updated cancel POST also sends this pin object as a JSON body. A foreign live digest returns 409. An unsupported target returns 404. Upgrade the service first. An old server can accept an acquisition through the original submit endpoint, but an updated client cannot poll or cancel it until the server is upgraded. The new adapter never falls back to unguarded lifecycle routes.

### Acceptance evidence

| Criterion | Evidence on the lane |
| --- | --- |
| VIS-001.1 | `test_contract_and_fresh_measurements` verifies the public profile and simulated projection. `test_persisted_instance_matches_live_profile_and_readings` binds it to saved context and live results. |
| VIS-001.4 | `test_lost_response_retries_only_keyed_write` closes the service then checks acquisition capabilities are unavailable. Dedicated truncated, foreign and malformed response cases fail explicitly. |
| VIS-002.1 | Saved project context drives an actual 650 nm acquisition. The returned job, blank, approved settings, timestamps, separate responses and records match. Replacement-service tests reject incorrect live origin and historical job identity. |
| VIS-002.2 | Real records retain pins, blank and requested replicates. Substituted envelope IDs, records, sample names, duplicate or out-of-range replicates and incomplete sets marked complete are rejected. |
| VIS-002.4 | The reopened scheduler recovered the original dispatch key after an accepted POST omitted its job ID. Assertions count exactly one job, one blank and 12 readings. Conflicting successful and truncated HTTP replies and a rejection after a 503 keep reconciliation uncertain. |
| VIS-002.5 | Foreign cancel attempts leave the owner's job running. Owner cancellation and restart retain partial records and terminal state. Mixed-version POST rejection also leaves the owner running. |
| VIS-002.7 | A competing acquire is rejected while the instrument is busy. Restart and uncertainty retain the FIFO lease, and a waiting run remains queued. Cross-process instance locks and replacement-after-close cases pass. |
| HTTP shutdown | The held-open client still owned its descriptor when server shutdown completed and a replacement reopened the same store and instance. It then read HTTP 408. Both jobs and readings tables were empty. Trickle traffic timed out, and a short valid JSON prefix returned 400 after premature EOF. |
| Adjacent VIS behavior | Existing API invalid-settings/blank, public provenance and hidden-model separation checks exercise VIS-001.2/.3 and VIS-002.3/.6 on the unchanged v1 JSON schemas. |

### Evidence boundaries

Identity fault cases inject altered responses at the server method or route and pass them through real HTTP. Store backup/restart, mixed-version, held-socket, saved-context and scheduler reconciliation checks operate real servers and SQLite databases. The scheduler reconciliation case takes software preparation offline to isolate the acquisition. Full composition uses fixture-generated candidate source with actual sandbox verification, release persistence, approval, scheduling and acquisitions. The development failure in `scheduler-base-loopback.txt` counted HTTP responses instead of unique job IDs. Its two identical IDs established the retry behavior. `scheduler-wo10-control.txt` verifies the corrected assertion on baseline production code. The first restricted run in `scheduler-base.txt` could not bind localhost. Both failed attempts are retained.

Upstream contracts ship in the pinned base. WO-6 supplies the public context/profile, WO-7 supplies the v1 service, WO-8 supplies the approval trace, WO-9 the release verifier and WO-10 the durable FIFO scheduler. WO-10 commit `ca31fbf` already classifies unreadable successful submissions as uncertain. No other remediation lane's head was required. WO-14 remains deferred.

**Code verdict:** APPROVED for independent 8090 evaluation.

### Repeat on an updated head or combined tree

Run from the project root with locked Python dependencies in an environment that permits loopback and the scientific execution sandbox. Run these sequentially on any single host because uvvis-demo-01 has a host-wide exclusive lock.

```sh
python -m unittest -v tests.test_uvvis_identity tests.test_uvvis_http_timeout tests.test_uvvis_api tests.test_uvvis_profile_handoff
python -m unittest -v tests.test_context_acquisition_integration tests.test_uvvis_scheduler_identity tests.test_experiment_scheduler tests.test_scheduled_acquisition tests.test_experiment_composition
python -c 'from tests.test_context_acquisition_integration import test_saved_project_context_drives_fresh_acquisition as check; check()'
python .sw-factory/WO-18/check_compatibility.py
python -m compileall -q factory tests .sw-factory/WO-18/check_compatibility.py
python -m unittest discover -s tests -v
git diff --check ae7d2f3d2f2cb98d52f7e6a5d8ffda911096bf08 HEAD
```

The integration owner must rerun the saved-context, scheduler, actual HTTP and mixed-version cases against all five heads. The aggregate additionally requires the planner/publisher handoff, scientific sandbox regressions, B12 replay/benchmark, EPR verification, production build and browser checks specified by WO-15. A combined head and its CI results remain outstanding. These are independent of the deferred WO-14 model-connected rehearsal.

### Responsibilities

The adapter delegate wrote the adapter and identity module, reproduced the base failure and cross-reviewed the cancellation handler. The HTTP delegate wrote the HTTP handler and body/guard tests. The read-only reviewer reproduced the replacement-service bug and reviewed its fix. The lead implemented the shared digest helper, scheduler regression and two-version probe, verified both contributions, integrated them and recorded the evidence.

### Local verification record

Two early 150-test runs and one 58-test run collided with another process holding the host-wide test identity uvvis-demo-01. They are recorded as failed runs. See full-suite.log (2 lock errors), full-suite-retry.log (5 lock errors) and final-focused.log (7 lock errors). Local full output lives under runs/WO-18. The preliminary 41-test integration run passed before the request-target correction. Final-check evidence follows below.


The final coordinated run passed all 150 discovered tests in 83.355 seconds, zero skips (Python 3.14.9, macOS). See exclusive-full-suite.txt. This includes all 58 lane-focused tests, actual saved-context acquisition, scheduler restart, scientific sandbox composition, B12 and EPR Python regressions. Source compilation and base-relative whitespace checks passed. The 2-second body deadline applies after headers have been parsed. Handling a slow or unfinished header is outside WO-18.

**Final independent engineering verdict: APPROVED.** PR #16 is a lane review branch. The five-lane aggregate checks are outstanding; the user requested that branches stay separate. The Factory tracker still shows Backlog. Approval review rejected the requested move to In Progress, and publication authority excludes status transitions.
