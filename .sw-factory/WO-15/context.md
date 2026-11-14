<!--lint disable strong-marker-->

# Work Order Entity Index: WO-15

**Initialized At (UTC):** 2026-11-14T21:06:54Z
**Current Status:** In Review, verified by a read-only Factory lookup at the start of the follow-up.

## Work Order

- WO-15: Reject invalid frozen calibrations in time-course releases (`e650ee81-4107-4dc0-8c09-6e6c3bfc15d2`)

## Requirements

- Context-driven scientific app releases (`3b942afc-ee12-42d9-8197-530241b183ef`)

## Blueprints

- Context-driven scientific app releases (`bf6bc85f-a0b5-45c8-8520-47dc27e304f5`)
- Context-driven virtual UV–Vis factory (`f316ff04-4015-495e-b5b8-742b2bea79fb`)

## Referenced Blueprints

Blueprints reached through `@…` mentions and links while reading linked blueprints.

- Local scientific software factory (`e406f284-f7d5-47e9-be16-7e0586f6059d`)
- Lab and project experiment context (`fbb53944-7834-46e2-a011-47008ff16266`)
- API-backed virtual UV–Vis acquisition (`41991def-9634-4f82-a3ea-61dcb8331403`)
- Serial experiments and reproducibility evidence (`127c7cf3-f150-4ddd-bb5b-5e0c95e38ea7`)
- Hosted research workspace and delivery checks (`0d865da4-887b-4011-910f-19a7213d9c23`)

## Delivery

- Branch: 8090/wo-15-frozen-calibration-e650ee81
- Pull request: https://github.com/NealDamireddy/scientific-software-factory/pull/14

## Baseline and dependencies

- Initial worktree HEAD and remote main both matched ae7d2f3d2f2cb98d52f7e6a5d8ffda911096bf08 before editing.
- Knowledge Base Plan (9f095369-805b-4489-bc06-961275cbc2cd). Factory owns frozen calibrations, the independent offline verifier and release decisions.
- WO-8 aa0f100 already rejects nonempty time-course standards at specification approval/compilation. WO-10 4c9e6e9 validates the concentration-derived fit before freezing. The pinned-base publication reproduction bypassed neither guard: it submitted five deficient candidates to the real independent release verifier.
- The integration coordinator confirmed publisher/compatibility ownership for this lane. The approved candidate protocol is time_course@1 and the mandatory verifier suite is scientific-release@6. The concentration compatibility policy and legacy storage format are preserved.
- No lane implementation dependency. WO-11, WO-12, model-connected preparation and the WO-14 live rehearsal are outside this lane. The integration owner will repeat the combined-tree gates after all five heads are frozen.
