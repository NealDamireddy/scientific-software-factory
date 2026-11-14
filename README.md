# EVOLVE

A local scientific software factory. The B12 demonstration builds a direct-vial app,
then adds prepared-sample support after PI approval. Acquisition uses a **simulated
550 nm instrument**, not physical hardware.

## Run the demo

From this repository's root on the presenter laptop:

```sh
uv run --frozen python -m factory.demo
```

Open **http://127.0.0.1:8765/**. The launcher checks the Python environment,
archived-source and calibration digests, actual offline sandbox behavior, exact
replay of the saved results, and Codex installation/login before opening the
service. It does not generate software during these checks.

You need [uv](https://docs.astral.sh/uv/getting-started/installation/), Python
3.11–3.14, an authenticated Codex CLI, and macOS Seatbelt (`sandbox-exec`) or Linux
bubblewrap (`bwrap`) with working namespaces. Fresh generation needs the coding
worker's model connection. Scientific execution is offline; EVOLVE does not call
8090. The readiness check does **not** prove model connectivity or build latency.

To check without starting a service or creating a scientific task:

```sh
uv run --frozen python -m factory.demo --check
```

### Previous-run fallback, without Codex

```sh
uv run --frozen python -m factory.demo --archive-only
```

The local presenter always includes the committed **Previous completed run**, even
with an empty live store. Its original task IDs, source revisions, measurements,
and evidence stay read-only and are not copied into or promoted as live releases.
Archive-only mode disables fresh generation. If the sandbox is unavailable, you
can still inspect and download the run, but cannot re-execute its Python. Recorded
replay outcomes describe the original run, not a new execution.

During live generation, select a previous run, then **View fresh task** to return
to the same live task. All live evidence remains in `runs/b12`; never delete it to
recover from a startup error. Use `--port 8766` or `--store runs/b12-rehearsal-02`
when you deliberately need a different port or a separate rehearsal store.

**[Five-minute rehearsal and troubleshooting](docs/DEMO-RUNBOOK.md)**

## Verify and reproduce

```sh
uv run --frozen python -m unittest discover -s tests -v
uv run --frozen python -m factory.replay_bundle public/b12/completed.json
uv run --frozen python -m factory.benchmark public/b12/completed.json --out runs/b12-evaluation-01
```

Run scientific tests on a host where the runner can apply its own sandbox. Missing
or blocked isolation is a failure, not permission to execute generated code
without it. Each benchmark needs a new output directory; existing output is never
overwritten.

The four held-out simulated vials have a committed MAE of approximately
0.00554 mg/L against a 1 mg/L engineering target. The six published commercial
means have a MAE of approximately 4.71980 mg/L, including two explicitly labeled
benchmark-only extrapolations that the released assay withheld. This is not
physical-instrument validation. See [retained evaluation](public/b12/evaluation/report.json).

The existing static EPR/B12 workbench remains available with `npm ci` and
`npm run dev`; `npm run build` exports it to `out/`. Node and the web build are not
required for the local B12 demo. The lower-level `python -m factory.lab` entry point
remains available without the launcher's readiness checks or bundled fallback.

### Researcher workspace

Open `/workspace/` for the UV–Vis researcher interface. **Fixture demo** keeps revisions and saved runs in the current browser tab. The fixture controls can return access or service failures. End session clears demo changes. The EPR workbench at `/` and the B12 archive at `/b12/` retain their recorded workflows.

The preset specifications and approvals come from the WO-8 service. Its calibration fixture supplies the complete synthetic frozen fit. Their digests and corresponding records are in [the producer fixture](fixtures/workspace/producer-records.json). Regenerate it with `python -m tests.test_workspace_golden --write` in the project Python environment. Specifications created or edited in a browser tab have fixture-local records and approvals.

**Live workspace** uses the versioned workspace API at the same origin, or at the trusted origin supplied through `NEXT_PUBLIC_WORKSPACE_API_URL` at build time. It sends the workspace session cookie and requires a project ID. Vercel previews use fixtures only and display the source commit from `VERCEL_GIT_COMMIT_SHA`. Live smoke testing requires the authenticated WO-12 service and WO-11 evidence endpoint.

Run `npm ci`, `npx playwright install chromium`, `npm run build` and `npm test` to exercise the production export. Browser tests use isolated fixture data and intercepted API responses.
