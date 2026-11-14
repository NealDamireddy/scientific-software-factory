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
