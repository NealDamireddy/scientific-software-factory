# EVOLVE: a scientific software factory for each research lab

EVOLVE gives every research lab its own scientific software factory. When a lab is onboarded, it brings its instruments and the context behind them: what each instrument can actually do, its configuration and firmware, and the lab's protocols and calibrations. Each experiment then adds its own context: the question, the samples, the method and the approvals.

With that context, the factory does two jobs:

1. **Guide the scientific procedure.** A researcher working on an experiment can ask for help with the procedure. The factory answers from the lab's own context and from published procedural standards, much as a senior lab member teaches an undergraduate how the lab does things. The person running the experiment signs off on the procedure before following it.
2. **Remove the coding barrier to analysis.** From the same context, the factory generates the analysis software for the experiment and verifies it before release, so data can be analyzed as soon as it is collected. Nobody in the lab has to write code.

## Why a lab needs its own factory

General-purpose language models fail in research labs in predictable ways:

- They ignore instrument limits and firmware. This is worst for custom or uncommon research instruments that no model has seen.
- They have no memory of the lab: its devices, protocols, past decisions and results.
- Their answers and code can't be traced back to the evidence behind them.

EVOLVE answers these failures with three rules:

- **Context comes from the lab.** It doesn't come from what a model assumes about an instrument.
- **People make the scientific decisions.** Agents propose procedures and write code. A researcher or PI approves.
- **EVOLVE owns verification, release and evidence.** Generated code runs offline in a sandbox and is checked against the instrument's real limits and independent reference cases. Only the exact code that passed is released. Every result traces back to its readings, calibration, sample preparation, approvals and source.

Day-to-day users are undergraduates, postdocs and PIs. Each lab runs its own deployment.

## What exists today

| Status | Capability | Where |
| --- | --- | --- |
| **Demonstrated end to end** | B12 scenario. A PI asks how much vitamin B12 is in a vial. EVOLVE builds an analysis app for a simulated 550 nm spectrophotometer. The app withholds an out-of-range result. After the PI approves a dilution, EVOLVE generates, verifies and releases a v2 that the old v1 fails. | `factory/assays/b12/` |
| **Demonstrated end to end** | First prototype: EPR linewidth and Curie-fit apps generated from structured work orders, verified offline and replayed in the browser. | `factory/assays/epr/` |
| **Built and tested** | Versioned lab, project and experiment-specification context, with approval. | `factory/lab_context/` |
| **Built and tested** | Virtual UV–Vis instrument API and trusted client. Acquisitions are pinned to the instrument profile. | `factory/instruments/` |
| **Built and tested** | Generation, sandboxed verification, release and reuse of concentration and time-course apps. | `factory/software/` |
| **Built and tested** | Approved acquisitions and a serial experiment scheduler. | `factory/experiments/` |
| **Built, not yet connected** | Storage for the instrument catalog, scientific artifacts, runtime work orders, and Postgres versions of these stores. Only tests use them so far. | `factory/knowledge/`, `factory/software/runtime_work_order*`, `factory/postgres/` |
| **Fixture data only** | Researcher workspace. Its live mode needs the authenticated workspace API, which is not built. | `app/workspace/` |
| **Not built** | The procedure assistant (job 1). Designed as the Scientific Agent System proposal: lab memory, evidence-linked planning and protected evaluation. | 8090 work orders WO-20 to WO-27 |
| **Not built** | Live instrument control, lab onboarding, and the authenticated multi-user API. | Under design |

Open questions are tracked rather than settled. They include how labs are onboarded, what is shared between lab deployments (for example, published procedures), how live instrument control should work when different experiments need different data from the same instrument, and which lab is the first real user. All instruments in this repository are simulated, and no result here is a physical-instrument validation.

## Repository map

```
factory/                 Python factory runtime
  context.py             Shared helpers: repository root, JSON, digests, order resolution
  lab_context/           Lab, project and experiment-specification records
  knowledge/             Instrument catalog and scientific artifacts (storage only so far)
  instruments/           Virtual UV–Vis instrument API, service and trusted client
  software/              Coding worker, sandbox, verification, releases, runtime work orders
  experiments/           Approved acquisitions and the experiment scheduler
  assays/b12/            B12 dilution scenario, presenter service, archive and benchmark
  assays/epr/            EPR prototype (python -m factory.assays.epr)
  postgres/              Hosted storage adapters
app/                     Next.js researcher workspace and archives
api/                     Vercel functions for the hosted B12 preview
registry/                Lab, instrument and schema records
orders/, generated/      EPR work orders and their generated apps
fixtures/, data/, public/  Reference fixtures, benchmark data and retained evidence
tests/                   Python and browser tests
docs/                    Runbook, scheduler guide, notices and development history
.sw-factory/, .agents/   8090 work-order records and the work-order skill
```

## Run the demo

The recommended demo is the **Lab projects** home page with the local presenter. From the repository root:

```sh
npm ci
npm run build
uv run --frozen python -m scripts.serve_assay_demo
```

Then open [Lab projects](http://127.0.0.1:8776/):

1. **Vitamin B12 assay** generates an analysis app, runs it on the simulator, compares it with a published result and downloads the run evidence. Locally, a Codex worker writes the app. This needs an authenticated Codex CLI and a macOS Seatbelt or Linux bubblewrap sandbox. The hosted `/b12/demo/` page builds the same app from a fixed protocol template, and its build receipt names the generator.
2. **Visible absorbance assay** and **Assay development** open the researcher workspace on demo data.
3. **Lab archives** holds the recorded EPR prototype and the full B12 dilution run.

The full B12 dilution story, with a live v1 → v2 build on stage, runs with `uv run --frozen python -m factory.assays.b12.demo`. See the [five-minute runbook](docs/DEMO-RUNBOOK.md). For serial UV–Vis experiments, see the [scheduler guide](docs/EXPERIMENT-SCHEDULER.md).

## Verify and reproduce

```sh
uv run --frozen python -m unittest discover -s tests -v
uv run --frozen python -m factory.assays.b12.replay_bundle public/b12/completed.json
uv run --frozen python -m factory.assays.b12.benchmark public/b12/completed.json --out runs/b12-evaluation-01
npx playwright install chromium && uv run --frozen npm test
```

Scientific tests need a host where the runner can apply its own sandbox. Missing isolation is a failure, never permission to run generated code without it. Benchmarks need a new output directory each time.

The retained B12 evaluation reports two figures, and neither is an accuracy result:

- **Software regression check: 0.0055 mg/L.** This is the mean absolute error on four simulated vials. The simulator and the analysis share one ideal linear model, and the only error source is detector noise, so the figure shows the code computes what the model says. It does not measure accuracy, and the panel has no diluted or out-of-range vials.
- **Calibration transfer to published data.** The frozen simulator calibration applied to six published commercial-instrument means ([Laganovska et al. 2020](https://doi.org/10.1016/j.ohx.2020.e00108)) gives a mean absolute error of 3.5 mg/L on the four rows the released app reported. The other two rows (20 and 24 ppm) are above the calibrated range, so the app withheld them; scored with a benchmark-only linear extrapolation they miss by 7.1 mg/L. For comparison, calibrating those six points against themselves with leave-one-out gives 1.0 ppm. Most of the error is therefore the simulated calibration not transferring to that instrument (about a 20% slope difference), not the method.

See the [retained evaluation](public/b12/evaluation/report.json).

## How EVOLVE is developed

EVOLVE's requirements, blueprints and engineering work orders live in an 8090 Software Factory project. Codex implements the work orders in this repository. Those are development tools: a lab running EVOLVE needs no 8090 credentials, and its coding worker uses its own model connection. The project began at the November 13–14, 2026 EVOLVE hackathon. Its history is in [docs/history](docs/history/README.md).

## License

MIT, see [LICENSE](LICENSE). Third-party software, services, data and scientific sources are listed in [docs/NOTICE.md](docs/NOTICE.md).
