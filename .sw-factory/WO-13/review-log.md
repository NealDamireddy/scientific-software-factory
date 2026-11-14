# WO-13 review and verification

## Round 1 · implementation 45011b8

Three independent cross-reviews covered the change from main in coherent groups.

| Review area | Result |
| --- | --- |
| Structured editors, revision and fixture contracts | Changes requested. The fixture accepted overlapping or duplicate sample IDs, an incomplete fourth standard, and a project concentration unit unsupported by the scientific contract. |
| Run progress, result presentation, scientific provenance and run tests | Approved. Independent stages and backend times remain intact. Results retain actual timepoints, units, calibration, source revision, withheld values and review findings. Terminal incomplete acquisitions suppress completed results. |
| Project/session lifecycle, security, preview guards, archive routes, delivery configuration and access tests | Approved. Scope changes unmount protected content and invalidate pending requests. Authorization errors clear records and sanitize server detail. Polling failures keep the recorded snapshot. Previews disable live operations. |

**Verdict** CHANGES_REQUESTED.

## Round 2 · correction 268515c, integrated with main 582d13b at 76e9b99

The editor reviewer approved the corrected fixture. It now checks the combined identifier namespace and count, every standard, distinct positive levels and supported units. Browser coverage exercises duplicate and overlapping IDs, an incomplete standard and a project specifying mol/L. The existing typed live transport continues to delegate validation to the API.

| Verification on integrated branch | Result |
| --- | --- |
| Locked install and production export | npm ci and npm run build passed, including TypeScript and static export of /, /workspace/ and /b12/. |
| Browser regressions | 25 Playwright tests passed against the production export. Includes 22 workspace tests and three existing archive tests. |
| Python regressions | All 70 unittest cases passed with OS sandbox and loopback instrument enabled. An earlier run encountered an instrument lock in use. The unchanged suite passed on retry and again after integrating main. |
| Archived scientific evidence | Both B12 releases replayed. The benchmark completed and all five EPR artifact manifests verified. |
| Browser exploration | Inspected the seeded runs on a 1360 × 920 desktop and all three workspace tabs at 375 × 812. No horizontal page overflow or JavaScript page errors. |

The fixture and intercepted HTTP checks cover optimistic revisions, exact-digest approval, reapproval, both experiment types, unsupported fields and preserved drafts, independent progress and pending wait, withheld estimates, incomplete evidence, session/project changes, expired/unauthenticated/forbidden reads, operations and downloads, and stale/unavailable execution. Authenticated persistence across restarts, real approvals/submissions, live producer results and authorized evidence require WO-11/12. Both upstream orders were in Backlog during verification. These live checks remain pending.

**Verdict** APPROVED for WO-13 fixture-tested delivery.

## Follow-up · protected specification fields

Chromium reproduction confirmed a gap in WO-8 parity. The editor now presents units, validation criteria and expected outputs as read-only. New drafts derive the first two from their pinned project revision and outputs from the experiment type. Ordinary edits retain the original project pin. The fixture rejects divergent projections on save and rechecks stored records before approval and submission. Regression coverage includes forged requests, previously persisted invalid records, changing experiment type and adopting revised project criteria in a new specification.

## Follow-up · immutable context across specification revisions

Compared the editor and fixture with WO-8 start and edit semantics. Existing revisions retain their original project, lab and instrument references. New specifications receive new IDs and can select a historical project and its recorded lab. The fixture rejects attempts to change the original references, including previously stored repinned revisions, on edit, approval and submission.

Independent review approved the change. The production export, TypeScript check and all 29 Playwright tests passed. The direct fixture and Chromium regressions exercise equal project payload digests across different revisions, historical starts, edits, distinct IDs, fresh approval and preservation of the earlier approval. Three targeted WO-8 producer tests also passed. Live authenticated integration remains pending.

## Producer-conformance audit

Three fresh reviewers compared WO-13 and its linked 8090 records with WO-6/8/9 on main at 69b6d33 and the WO-10 scheduler on its implementation branch. WO-11 and WO-12 were still in Backlog.

| Area | Reproduction and correction |
| --- | --- |
| Specification and calibration provenance | The old adapter hashed its public specification projection and calibration reference metadata. The checked-in capture now comes from the producer's SQLite context, specification and approval services and its persisted frozen-fit test fixture. Python regenerates it and checks the complete payload digests. Browser tests follow each run's reference through evidence to the full record. Session edits have separate fixture-local provenance. |
| Context edits | Chromium on the old export saved two instruments with the same ID as lab revision 2. The corrected response identifies the duplicate row, preserves the input and revision, and allows a corrected retry. Context identifier and list checks cover other UI-reachable WO-6 constraints. |
| Drafts and approvals | The old fixture rejected an incomplete draft at save. Scientific findings now accompany the saved draft and gate approval. Tests reopen partial and out-of-range drafts, correct them, and approve the selected digest, including an older unapproved revision. Mutating protected protocol fields and substituting context pins still fail. |
| Preview and execution state | The preview now displays the build's Vercel source commit. CI builds a preview and checks identity and live-request isolation in Chromium. Interrupted acquisition displays the scheduler's blocked analysis state. A zero-byte HTTP 200 evidence response yields an error. |
| Live integration | The hosted provider contract remains unverified. Fixture operations, intercepted HTTP, a Vercel build and producer regeneration demonstrate frontend behavior only. Authenticated restart persistence, real job orchestration and authorized private evidence remain pending the upstream services. |

Independent cross-review also found a persisted specification projection could change under an existing digest. Approval, submission and evidence export now check the projection against the complete record and its digest. Tests exercise both captured and session-created records and preserve the original time-course draft alongside its approved revision.

Verification passed with a clean npm install, production export including TypeScript, all 37 Playwright tests, 104 Python tests, offline regeneration of the final producer capture and the WO-8-to-WO-9 handoff for both experiments. A separate preview export displayed its configured source SHA and issued zero live workspace requests. Independent reviewers approved the lifecycle, evidence and preview changes.

**Verdict** APPROVED for fixture-tested delivery.
