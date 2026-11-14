# WO-10 implementation plan

Persist one FIFO run per submission in a local SQLite application database. Recipe approval, preparation of verified software, remote acquisition, and analysis have independent states. Use a polling worker to advance runs as prerequisites arrive.

## Code reuse and package structure

Use WO-8’s specification service and approved keyed acquisition, WO-7’s HTTP adapter for remote state, and the WO-8 planner with WO-9’s verified release repository. Define injected boundaries so the scheduler is usable and testable on main while the dependency branches are under review. Keep the simulator and its store unchanged.

## Components, flow and steps

1. Add the experiment run store and orchestrator. Submit an immutable specification digest and instrument ID with an idempotency key. Serialize state transitions across local workers; claim and persist instrument ownership and a stable dispatch key before external I/O. Reconcile known job IDs by polling, and unidentified submissions using their original key.
2. Add trusted adapters for recipe/approval/calibration readiness, acquiring and polling, verified preparation and isolated analysis. Run build and analysis in independent worker threads; record attempts before execution and recover interrupted work without confusing it with an active worker. Capture remote acquisition times and local worker timings; expose open or final wait separately from nonsoftware blockers.
3. Document worker usage and dependency composition. Leave simulator internals, generation, verification, hosted APIs, frontend and evidence export unchanged.

## Testing

Use a deterministic clock and controlled instrument/release doubles in tests/test_experiment_scheduler.py for FIFO, lease contention, both completion orders, cancellation, calibration/approval blockers, timing and restart with a lost submit or poll response. Exercise real adapters in an isolated integration checkout with available dependency revisions, building on WO-8’s saved-context acquisition fixture. Run the full unittest discovery suite (including B12 replay and sandbox) with the project Python and inspect a status response.

## Implementation details resolved in execution

The scheduled time-course adapter uses one application series identity with a stable keyed submission for each point, preserving the remote IDs and approved blank. The trusted backend freezes the concentration fit for the subsequent time course. WO-7's HTTP adapter now distinguishes malformed successful responses (uncertain) from explicit request rejection. Scheduling, time-course and concrete composition tests live in separate modules.

## Review remediation on the dependency-complete candidate

Bring merged WO-6 through WO-9 and the integration workflow onto the WO-10 branch. Isolate the two review findings by file ownership. Verify terminal time-course reports before they can change durable state, and re-poll malformed historical terminal entries using the saved remote ID. Check that the scheduler retains then releases its lease through restart. Validate the standard replicates and fit before persisting a calibration. Exercise the real analysis entry point with a mixed-model standard and a valid calibration whose unknown is outside its range. Run the scientific suite, composition and PR integration workflow against the updated tree.
