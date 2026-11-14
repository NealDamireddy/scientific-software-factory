# WO-19 implementation plan

## Summary

Select a verified live B12 release before invoking a worker. A request gets its own task ID, source bytes, original provenance and measurement. An explicit approval binds a supported dilution factor to the direct run, its sample, source and observed range evidence.

## Code reuse and package structure

Use factory/b12_build.py for immutable three-file source revisions and factory/optics.py for protocol checks. Encapsulate B12 compatibility, digest and provenance inspection in factory/b12_reuse.py. Reuse WO-8 compatibility comparison where the contracts overlap. Legacy B12 records are filesystem tasks, with different schemas and verifier receipts from the SQLite UV–Vis planner. Retain the existing planner's behavior. Lab.submit/enqueue/generate/revise/approve/prepare and HTTP dispatch implement request flow. Keep Lab.collect, Lab.rerun and followup.py with WO-16.

## Components and flow

1. POST /api/tasks accepts an optional sample_id, default U-01. Persist it independently of the brief. Select an original live verified release by matching capability, context, verification and pinned contract evidence. Persist rejection reasons. Checked source copies share a revision, while opaque run IDs remain distinct.
2. Lab.generate prepares source and uses collect(task_id) for fresh and reused measurements. Stage reused revision and origin_task_id before collection. The analysis payload, raw samples and resulting identity must match the request. Fresh generation retains parallel acquisition.
3. Proposal includes 2× and 4× options. Approve defaults to 2× for existing clients and deduplicates by origin/factor. Different factors get distinct approvals. Persist linked observed readings, calibration reference and strongest standard. Prepare validates actual volumes against approval and actual parent. Prepared release reuse requires a verified prepared contract, otherwise retain independent parent checks and candidate generation.
4. Use the existing rerun, evidence and read-only archive paths. Preserve original worker and checks, including verification provenance for reused source. Original verified files and tasks remain intact on failures.

## Testing

Reproduce the base failure before edits. Add dedicated request-flow tests with known direct and prepared source. Count coding-worker calls, assert stable revisions, distinct run IDs, immutable provenance, evidence linkage, both concentration fields and actual sample identity. Use a test collection adapter for the WO-16 caller contract only. Exercise legacy inputs, missing or incompatible capability, digest tampering, archive boundaries and idempotence. Run focused, full Python, compile and diff checks. Run supported sandbox checks explicitly. Reserve saturated/restart/archive refusal on the combined head for integration. Compare actual changes to the plan and request independent review.

Review refinements resolve the current direct parent back to its original source before approving or generating. Both historic and new verification reports use the exact optical-checks@1 fixtures and the original result matcher extracted from factory/optics.py. The planner exposes its compatibility field comparison for both release formats. The pre-existing Lab retry test now seeds known verified evidence. HTTP rerun forwards an explicit retry_of to WO-16; an empty body follows the existing call. The combined owner wires WO-16's direct analysis outcome recorder around the shared call to Lab.analyze_direct.
