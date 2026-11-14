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
