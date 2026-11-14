# WO-8 review log

## Round 1 — changes requested

Two independent reviewers checked the specification/acquisition and preparation changes against main. The focused tests passed. Reviewers reproduced four gaps.

| Area | Blocking finding | Acceptance impact |
| --- | --- | --- |
| Time-course acquisition | Creating a new reference breaks the frozen calibration's blank identity. | Blueprint contract and calibration compatibility |
| Specification review | Four unsupported settings produced only the first field correction. | AC-CTX-002.3 |
| Preparation state | Killing the process could leave a task generating or verifying indefinitely. | AC-APP-001.5 |
| Release discovery | A new planner database could miss an older compatible release in the shared repository. | AC-APP-003.1 |

Verdict: CHANGES_REQUESTED

## Round 2 — approved

The specification and acquisition reviewer approved 99a4335 after running the field, schedule, reference, approval, retry and adapter regressions (18 tests and 10 subtests). The planner reviewer approved 4245cff after eight preparation tests and a separate 12-caller concurrency probe that dispatched exactly one worker. A terminated worker retained its interrupted attempt. Verification recovery distinguished an unpublished candidate from one with an exact published manifest. A separate task database selected the older compatible release after a newer, incompatible release became active. The lead also checked serialization of malformed worker diagnostics and the duplicate-plan read path.

| Acceptance criteria | Verification |
| --- | --- |
| AC-CTX-002.1–.5 | Drafts show context, settings, outputs, criteria and calibration inputs. Review requires explicit field confirmation, reports all missing/incompatible settings and stores the actor and timestamp against the immutable digest. Edits require new approval. |
| AC-APP-001.1–.5 | Preparation records include pinned revision headers, a filtered contract-specific prompt and worker receipt. Tests cover unsupported types, pending, failed and interrupted attempts, candidate retention and verifier-only publication. |
| AC-APP-003.1–.4 | Tests cover sample-only source reuse, frozen calibration changes under a compatible contract, added capability, changed settings/contract, historical release discovery and preservation of the previous source. |
| Saved context drives fresh acquisition | The exact WO-14 pytest selector passed. Job 6dd34d7c97dd4dae820c5c2faf24f9b6 produced 12 timestamped 650 nm readings, three each for three standards and the opaque unknown, with a matching profile digest and blank. The project already held a newer 450 nm revision. |
| Real verifier handoff | In isolated temporary stores the planner supplied fixture worker source to the open WO-9 verifier at 907a4f4. All 51 concentration and 47 time-course checks passed under macOS Seatbelt. Each sample-only edit reused the previous source revision. No WO-9 code is included in this branch. |
| Regressions | Repository Python runtime ran unittest discovery: 87 passed. B12 offline replay returned review for U-01 and 32.006829774391655 mg/L for U-01-D1. Python compileall and git diff --check passed. |

Backend-only scope. The loopback instrument and verifier were real. Worker responses used fixtures; a live model generation rehearsal is separate. Scoped locks protect task ownership and allow recovery after process death. The host controls candidate paths, reads immutable revisions and retains verifier evidence. A transport retry reuses its saved acquisition request and job identity.

Verdict: APPROVED

## Round 3 — approval and integration review

Reproduced the original failure at 5c7592b. A saved 201-character instrument ID passed review and persisted approval, then recipe compilation raised InstrumentError. At 8e47eb1 the review and compiler use the same acquisition-schema pin validator. A 200-character ID approves and compiles. A 201-character ID yields an instrument.instrument_id correction and stays draft.

The service resolves a supplied calibration reference from the run service's SQLite store, recomputes the full canonical payload digest and matches the calibration identity, lab/project, instrument, profile, settings, units and blank. Missing and forged references fail before approval. Deleted and altered records fail at use. An independent reviewer exercised the actual WO-10 calibration writer, approved its result and compiled the pinned 650 nm time-course recipe.

The required loopback acquisition test passed. Job 034fbcd15863420a92fbc6758ef6a587 produced 12 readings after the project changed to 450 nm. Each reading used the acquired reference's dark and blank counts, fell within the job's recorded start and finish, and retained the approved 650 nm setting.

The reproducible fixture-worker handoff used WO-8 8e47eb156ba9afb2959b1b24fe9c7f2a9700191a and WO-9 ab6ad5e39a1d6b0c97cf6f91ccbfdfb779ef9e87. The real scientific-release@5 verifier passed 53 concentration checks and 49 time-course checks. Both sample-only edits reused the same release ID and source revision with zero worker calls. The report records every check name, category and status, the approved specification digests, release IDs, source revisions and composed Git tree. [Handoff report](handoff-report.json)

Reproduce from a repository containing both commits, using the project's Python runtime on a supported offline sandbox host:

```sh
python scripts/check_wo8_wo9_handoff.py 8e47eb156ba9afb2959b1b24fe9c7f2a9700191a ab6ad5e39a1d6b0c97cf6f91ccbfdfb779ef9e87
```

Full discovery passed 89 tests under macOS Seatbelt. The archived B12 replay withheld the original estimate and reproduced 32.006829774391655 mg/L for the follow-up. Python compileall and git diff --check passed.

Independent review verdict: APPROVED

## Final review before merge

The shared SQLite calibration lookup matches the WO-10 writer in the local implementation. An independent review found no blocking issue. Introduce a resolver when a separate calibration store or hosted adapter is added.

The candidate includes the live-worker contract correction from PR #9 and the integration workflow from main at 582d13b. The correction describes the public measurement fields and directs time-course analysis to use the frozen fit with an empty standards array. The independent reviewer checked the prompt against the verifier and the previous authenticated live rehearsal.

At implementation tree 82a5287, all 89 Python tests passed. The fixture-worker handoff against WO-9 at 1c2eb04 passed 53 concentration checks and 49 time-course checks. Both sample-only edits reused verified source with zero worker calls. The latest repair head 664a241 has the same tested tree. The offline B12 replay reproduced the follow-up estimate of 32.006829774391655 mg/L.

Verdict: APPROVED
