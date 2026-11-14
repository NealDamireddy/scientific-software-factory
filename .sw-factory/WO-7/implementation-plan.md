# WO-7 implementation plan

## Summary

Implement a separately runnable, loopback virtual UV–Vis instrument with a durable SQLite job store and a trusted HTTP client. Apply REQ-VIS-001 and REQ-VIS-002 at both the adapter and service boundaries.

## Code reuse and package structure

Use factory.context for JSON files and SHA-256, existing optical detector constants and absorbance quality checks from factory.optics, and Python's SQLite and HTTP libraries. Follow the existing factory.lab process-lock pattern. Keep the existing B12 simulator and its profile intact.

- factory/uvvis_contract.py and registry/uvvis-api-v1.schema.json define v1 request/response shapes and capability pinning.
- factory/uvvis_service.py owns private sample models, reference readings, job identities, transactions, cancellation and restart reconciliation.
- factory/uvvis_http.py owns loopback routing and the CLI. factory/uvvis_adapter.py speaks HTTP and validates capability pins before a write.
- tests/test_uvvis_api.py exercises an isolated store, injected public profile and temporary private sample data.

## Components and flow

VirtualInstrumentAdapter obtains the live projection, recomputes its canonical digest and checks instance, revision, requested settings and pinned digest. VirtualUvVisService repeats those checks and captures a reference bound to instance, revision, wavelength and path. An acquisition references the blank, sample IDs, settings and an idempotency key. One job owns the instrument at a time. The worker commits each reading before starting its next replicate. On restart an unfinished job becomes interrupted with its existing readings available. Responses expose counts, actual timing and simulated provenance. Only the simulator process loads private sample parameters.

## Steps

1. Implement versioned contracts and shared validation of pins and requested settings. Load the public projection and schema supplied by WO-6.
2. Add a process-exclusive job store, synthetic detector and asynchronous worker with configurable noise and replicate duration.
3. Add the six loopback routes, bounded adapter requests and safe retries.
4. Exercise independent HTTP, concurrency, retry and restart tests, then provide the service and adapter entry points to the joint smoke check.

## Testing

Run the virtual UV–Vis tests with unittest. Use a controllable worker clock to exercise partial progress, cancellation and interruption. Test mismatch, unsupported/missing settings, invalid/incompatible blanks, duplicate submissions, concurrent starts, bounded failure and private-field exclusion. Exercise both concentration and time-varying synthetic samples. The lead reviews the diff and runs the re-opened project and existing B12 gates across both PRs.
