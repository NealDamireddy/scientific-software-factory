# WO-17 review and acceptance evidence

Base `ae7d2f3d2f2cb98d52f7e6a5d8ffda911096bf08`. The only production changes are archive admission, two archive-specific validation modules and presenter readiness. The committed package is untouched. The archive-only service validates before exposing tasks or creating a live store.

## Baseline and acceptance

| AC | Evidence on this branch |
| --- | --- |
| AC-B12-003.2 | All five independent mutations were served as verified by the pinned base, including HTTP 200 from the child task route. See baseline.json. The dedicated tests call the same Lab constructor and demo.readiness for every rejected package. A coherent historical out-of-range rerun retains raw counts and a withheld estimate. |
| AC-B12-003.4 | Detector counts and settings, the six standards, frozen fit/digest, result, approval, actual volumes, sources, dependency lock, optical-checks@1 and open review are cross-checked. The historical v1 declines the two valid prepared fixtures. V2 must pass all sixteen. Missing, duplicated or fabricated checks fail. |
| AC-B12-004.2 | Six successful real loopback GETs cover the task list, both original task IDs, both sources and child evidence. With replay unavailable the fixture reports warnings, generation disabled and a read-only archive. All readings carry simulated provenance. |
| AC-B12-004.3 | A clean Chrome session opened the archive-only presenter, selected the historical child, downloaded the evidence and received HTTP 200 on the replay POST. Two originals appeared in history; generation was disabled. The fresh model-connected submit/approve sequence belongs to the later WO-14 rehearsal. |

## Retained-package mutation diagnostics

| Mutation | Admission failure |
| --- | --- |
| Saved task result 999 mg/L | followup.measurement.result.concentration_mg_l differs between task and measurement |
| All copied preparation/result parents changed to an unrelated vial | followup.preparation.parent_id differs from original vial |
| Approval factor changed to 4 | followup.approval.factor differs from actual preparation volumes |
| Approval removed | followup.approval is missing |
| Empty extended release checks | followup.checks requires the completed optical-checks@1 suite |

## Supported sandbox and presenter

`python3 -m factory.demo --archive-only --check` passed the macOS Seatbelt private-read, private-write and loopback-denial probes. `python3 -m factory.replay_bundle public/b12/completed.json` executed both archived sources separately. Direct task a921d6aadbcd41beb3b442a65182988f withheld concentration for U-01. Prepared task 7b92c13361464fdea79aa5cffcab0f7d returned 16.003414887195827 mg/L diluted and 32.006829774391655 mg/L corrected, factor 2. The shared frozen calibration was c2821b055967b3bf67a858b5e90488d12c755b257898881f568d7cf09da102d2.

A separate fixture with replay disabled exercised retained inspection. Another fixture injected a sandbox replay disagreement after successful preflight and confirmed failure. The first unprivileged HTTP run could not bind a local socket. The real loopback and supported-sandbox reruns used the host permissions required for those checks.

## Independent review round 1

**CHANGES_REQUESTED.** The reviewer reproduced three additional contradictions through the task API. A withheld follow-up could display an unrelated parent, an invalid factor or a non-null diluted concentration. An optional revealed score could claim an incorrect signed error. A boolean volume in the copied input compared equal to an integer in the task. The fixes validate populated result lineage, both withheld concentrations, public score arithmetic and JSON boolean types. The independent 48-test suite passed before the fixes; regression cases were added to exercise these findings.

## Integration contract

Run `assert_archive_rejected(self, package, r"(?i)attempt|measurement|saturat")` from `tests.test_archive_consistency` on an export claiming that the actual WO-16 rejected attempt completed. Supply the actual attempt ID in the claimed measurement. Confirm no corrected concentration or hidden label at the producer, stable acquisition count after restart and durable rejected evidence. An earlier rejected attempt can precede a later correctly linked completed retry. The historical fixture predates attempt IDs.

Construct a valid sample-renamed, approved 4× release through the actual WO-19/WO-16 request and acquisition APIs. Open the package using `Lab(store, archive=package, allow_generation=False)`. Assert the two experiment IDs and presented source bytes match the exported runs. Assert the origin IDs, worker receipts, verification suites, source revisions, actual parent/child IDs, approval, completed attempt ID, frozen calibration and results match producer evidence. Fetch the child evidence and replay through the presenter. Source revisions may agree for verified prepared-source reuse. Combined checks are outstanding on this lane. Re-run when any reviewed head or integration base changes.

The verification delegate implemented the retained suites and reuse provenance. The test delegate reproduced the HTTP baseline and added the dedicated mutation, compatibility and journal cases. The independent reviewer sought admission bypasses. The lead owned the measurement checks, API wiring, browser and sandbox verification, delivery and final inspection.

## Independent review round 2

**APPROVED.** The reviewer inspected the final production and test changes at `230ecfd70ed6233ce21262509c317b92f02253c8`. All 51 archive, consistency, readiness and replay tests passed on macOS with HTTP and Seatbelt. Six independent probes confirmed field-specific rejection of the incorrect signed error, input-only boolean volume, and four false result fields on a withheld follow-up. The unchanged control remained inspectable. No open lane review findings.

The lead's final focused command, `python3 -m unittest tests.test_archive_consistency tests.test_archive tests.test_demo tests.test_replay_bundle tests.test_optics tests.test_followup tests.test_lab -q`, passed all 66 tests including all 28 dedicated archive cases. Python compilation, Git whitespace checks and the comparison of the committed archive to the pinned base passed. The bundle SHA-256 is ad634ddf20aa275f0dc1b23f5bf8dd493be04cd271579096215dbfc25f64c272. The final delivery commit adds execution records only. GitHub checks are recorded against that exact head in the draft PR.

## External review on 7dae053

**CHANGES_REQUESTED.** Three blocking P2 findings were recorded on [WO-17](https://factory.8090.ai/project/57fbf0e2-015b-4e28-93cd-ae06b55fadc4/work-orders/17#comment=03b6ed9e-79f2-460c-8958-2a307c5eb04c). On an isolated checkout of 7dae053cf1015456230a02f783c66c9f3b3b9c3e the lead reproduced all five altered-package probes below. Each passed archive-only readiness with replay unavailable and returned HTTP 200 with a verified archived task. An unchanged sixth control also returned HTTP 200.

| Finding | Mutation | Admission requirement |
| --- | --- | --- |
| Direct result lineage | Set parent_id to an unrelated vial, preparation_id to a fake ID and factor to 4 | A direct result permits absent or null parent_id, preparation_id, factor and diluted_mg_l. Each populated field is rejected independently. |
| Follow-up sample | Change only followup.sample_id | A declared task sample must match the preparation, input, raw records and result. The historical task omits this field. |
| Temporal evidence | Date approval in 2099, corrupt a completed attempt's three journal timestamps, or delete followup.measurement.time, each in a separate package | Check required timezone-aware timestamps and compare actual instants in producer order. Historical direct data uses raw timestamps. Only journaled runs require journal milestones. |

## Review of corrections

The lineage agent corrected both identity checks. The timing agent traced the B12 producers and implemented chronological validation. The regression agent exercised the archive validator, readiness with replay unavailable and admission to the task service. The lead repeated the before/after HTTP probes and tested the historical run in Chrome. In a second pass the lineage agent reviewed the temporal changes and found a discrepancy specific to the optional direct calibration-standard journal copy. The correction compares that checkpoint with the frozen raw standards, including their timestamps.

The chronology uses inclusive ordering from the original task and readings through approval, follow-up creation, acquisition and measurement completion. A successful journaled attempt has start, acquisition and finish times. A failed attempt can end before acquisition. A retry follows its predecessor's finish. Earlier rejected detector output is retained for inspection. The validator accepts equal instants with different offsets. It does not invent a historical verification timestamp.

All five altered-package probes now fail readiness and task service admission with the affected fields identified. The historical control returned HTTP 200. The separately executed macOS Seatbelt probe denied private-file and network access. Both archived results reproduced, including the withheld direct estimate and 32.006829774391655 mg/L follow-up. A clean Chrome session inspected the evidence, showed generation disabled and received a successful replay response with both match flags set.

The combined WO-16/WO-19 exports and the later WO-14 live-generation rehearsal remain outstanding. On the combined tree also exercise WO-19's new revision-bound verification receipt fields with its shared receipt checker, including rejection of a stale receipt. Historical packages predate these fields. Final-head CI and freeze details are recorded on PR #15.

The optional calibration checkpoint shape was compared with the WO-16 writer's working tree; it was absent from that lane's published b9708648 head at inspection. Its tests here are fixtures. The archive preserves WO-19's newer optional source-verification receipts; the standalone lane does not independently authenticate those receipt digests. At integration, recompute and compare available verification, parent_verification and origin_parent_verification receipts using their correct revisions, checks, workers and contracts. Mutate each digest alone and exercise prepared-source reuse with a different experimental parent. Retain the no-receipt historical positive control and report any unavailable original-parent inputs explicitly.

WO-19 confirmed the origin receipt can be recomputed with verification_receipt(origin_parent_revision, origin_parent_checks, origin_parent_worker, release_contract). Check origin_parent_task_id as a separate lineage reference. For a different original parent the two-run archive lacks its source bytes. Receipt consistency is testable from the retained inputs; rehashing those absent source bytes requires the original release store.

**Lane review verdict: APPROVED for resubmission.** The independent temporal review confirmed all three review findings and the additional checkpoint discrepancy are closed. Twelve historical, reuse and journal positive controls passed. The reviewer's 60 archive/readiness/replay tests passed. The lead ran 75 focused tests, including all 37 dedicated archive-consistency tests, with macOS Seatbelt and loopback HTTP. Python compilation, Git whitespace checks and the committed bundle SHA-256 comparison passed.
