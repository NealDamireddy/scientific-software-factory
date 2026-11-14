# WO-8 implementation plan

## Summary

Deliver a local application service that binds approval, recipe compilation, software preparation and acquisition evidence to immutable context. Use the integrated WO-6/7 code on main and the public WO-9 verifier handoff.

## Code reuse and package structure

- factory/specifications.py uses ContextRepository, canonical JSON and the public UV–Vis profile to build and validate pinned specifications. SQLite stores immutable drafts and separate approval records.
- factory/release_planner.py uses agent.invoke_worker, the existing bounded artifacts and source revision algorithm. Inject the release repository and independent verifier. Retain preparation states, parent selection, worker receipts and candidate files locally.
- factory/approved_acquisition.py uses the specification service and VirtualInstrumentAdapter. Record the approved submission before dispatch, then associate it with its returned job.
- Cover each service in its own test module, including tests/test_context_acquisition_integration.py.

## Components and flow

Load a project revision and its exact lab revision by ID. Create a draft with a versioned experiment contract, settings, samples, calibration inputs and outputs. The researcher explicitly confirms the reviewed digest. Editing creates another draft. Only a persisted approval can produce the trusted recipe or authorize a preparation. Match releases by scientific contract, scoped settings and capabilities. Reuse verified source when compatible, otherwise stage a capped candidate with its worker receipt and submit it to the injected verifier. Acquire blank and readings separately using pins, durable submission identity and the trusted adapter.

## Steps

1. Implement specification creation, inspection, editing, confirmation, approval and verifier/acquisition projections.
2. Implement the preparation decision, filtered prompt, durable transitions and independent verifier boundary.
3. Integrate approved acquisition with saved submissions and one loopback composition test.
4. Review the diff against the 14 scoped acceptance criteria and correct blocking findings.

## Testing

Run focused specification and planner tests for missing or incompatible fields, calibration and schedule, edited and stale approvals, reuse, revision, unsupported contracts, worker failure and receipt retention. Run the named composition test with fresh SQLite databases, a pinned 650 nm revision and a newer 450 nm revision. Run full unittest discovery, the named pytest selector, compile checks and git diff --check. Verify B12 sandbox/replay regressions using the repository runtime.
