# Run the local experiment scheduler

The scheduler accepts an idempotency key, an immutable specification digest and an instrument ID. Submit the same three values to recover the existing run; changing the inputs under an existing key is an error. One local dispatcher can serve concurrent submitters. The first queued run for each instrument keeps its FIFO position while it waits for approval, a trusted recipe or its calibration.

The concrete local backend binds one application to one virtual instrument. It needs the saved-context approval and preparation services from [WO-8](https://github.com/NealDamireddy/scientific-software-factory/pull/6) and the verified release repository and sandbox from [WO-9](https://github.com/NealDamireddy/scientific-software-factory/pull/4). The scheduler and its standalone tests are usable without those modules. With both installed:

```python
from contextlib import closing
from threading import Event, Thread
from factory.approved_acquisition import ApprovedAcquisition
from factory.experiment_adapters import LocalExperimentBackend
from factory.experiment_scheduler import ExperimentOrchestrator
from factory.release_planner import ReleasePlanner
from factory.scientific_release import verify_release

# specs: ExperimentSpecificationService; releases: ReleaseRepository
# instrument: WO-7 VirtualInstrumentAdapter pinned to the saved lab profile
backend = LocalExperimentBackend(
    app_db, specs, ApprovedAcquisition(specs, app_db, instrument),
    ReleasePlanner(specs, releases, app_db, verifier=verify_release),
)
with closing(ExperimentOrchestrator(app_db, backend)) as worker:
    stop = Event()
    thread = Thread(target=worker.serve, args=(stop,))
    thread.start()
    try:
        run_id = worker.submit(submission_key, spec_digest, instrument.pin["instrument_id"])
        # Keep the worker running while the host accepts requests.
        # worker.status(run_id) reads a snapshot; worker.cancel(run_id) records intent.
        serve_requests(worker, run_id)  # your local host's request loop
    finally:
        stop.set()
        thread.join()
```

`status()` reports approval, recipe, software, acquisition, analysis, blockers, original remote job IDs, release and outcome. Software and analysis attempts record UTC times and monotonic worker durations. The acquisition start/finish come from the instrument. After a complete acquisition, `software_wait_s` counts from remote finish to verified software readiness; `software_wait_pending` distinguishes an open wait from a final duration. Waiting for a calibration or downloading records can independently delay analysis. A cancellation can suppress a result even when measurements have already completed.

Concentration analysis returns a calibration reference when a valid positive-slope fit can be frozen from the measured standards. A subsequent approved time course may pin this exact reference, including its blank. Its local series ID maps to one remote job per point. The interval is a minimum between actual starts: a delayed worker records late measurements at their actual times. It never fabricates missing timestamps.

Keep the SQLite database and its sibling scheduler-locks directory together on a local filesystem. Keep the instrument store separate. Restart the worker against the original application database and instrument. A lost submit response is reconciled with the original key; once a remote ID is known only that job is polled. An unreachable or unknown job keeps the instrument lease. If a cancellation has no confirmed remote ID, the worker performs read-only identity lookup: an unresolved submission stays blocked because re-submitting might start an acquisition after cancellation. Do not clear the lease to force progress.

Run the standalone and time-course tests with:

```sh
uv run --frozen python -m unittest tests.test_experiment_scheduler tests.test_scheduled_acquisition -v
```

With WO-8 and WO-9 present, run `uv run --frozen python -m unittest tests.test_experiment_composition -v` on a host that permits loopback HTTP and the supported scientific sandbox. Its candidate source is a fixed test fixture; approval, measurements, timing, calibration, release verification and analysis are real local operations. It does not exercise a model-connected generation session.
