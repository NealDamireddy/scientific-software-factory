# EVOLVE — A software factory for lab instruments

EVOLVE turns a scientist’s measurement request into a tested analysis app. A coding worker writes the Python analysis, the instrument recipe and the result view. The factory checks the recipe against the instrument’s capabilities, runs the generated Python offline against independent reference cases, and releases the source revision that passes.

**Watch the software change during an experiment.** A researcher asks for the concentration of a mystery vitamin B12 sample. The first app measures it on a **simulated 550 nm spectrophotometer** and withholds the estimate because the reading exceeds the calibration range. Once the principal investigator approves dilution, EVOLVE builds a second version while the researcher prepares the vial. The factory tests the new version on 2× and 4× dilutions and reruns the original direct-sample checks. A reviewer can trace the final estimate back to the readings, the dilution volumes, the frozen calibration and the exact Python that produced it. [Completed run](public/b12/completed.json)

## What we built at EVOLVE

For the November 13–14, 2026 hackathon theme **“Build your own software factory,”** we built the lab and instrument registry, simulated instruments, work-order pipeline, code-generation and verification steps, approval workflow, and replayable evidence workbench. On the first evening, we used the same factory to build two electron paramagnetic resonance (EPR) apps. One measures spectral linewidth. The other fits signal intensity against inverse temperature. The B12 experiment added a second instrument and demonstrated how the factory revises an app when the experiment changes. [EPR work orders](orders/) · [B12 rehearsal](docs/DEMO-RUNBOOK.md)

**We used no pre-existing team materials.** An earlier team project, Flipper AI, inspired the idea of checking software against a specific instrument’s capabilities. Codex generated the scientific applications from project-specific inputs. [Generation records](generated/) · [Project notices](docs/NOTICE.md)

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

## Online instrument demo

From this directory, run `npm run build` and `python3 -m scripts.serve_assay_demo` in the project Python environment. Open http://127.0.0.1:8776/b12/demo/. Click **Insert experiment specs**, then **Generate analysis app**. The presenter passes the specification to the local authenticated Codex CLI and checks the generated Python against five calibration cases. Click **Inspect generated files** to see the recipe and analysis. **Run on simulator** takes three fresh readings and executes the verified app in the local sandbox. **Show paper comparison** reveals its estimate from a published absorbance using the same calibration. **Download run evidence** includes the specification, generated files, receipts and results. Generated apps remain available until the presenter server stops.

The hosted `/b12/demo/` generates a Python application from the inserted protocol, verifies five calibration cases, and runs it in the browser. The build receipt identifies the hosted generator, including whether Vercel AI Gateway supplied the calibration expression.

## Researcher workspace

Open `/` or `/workspace/` to select a lab project. Build application opens the specification editor. Refine data filters recorded measurements by sample and result status. **Fixture demo** keeps revisions and saved runs in the current browser tab. The fixture controls can return access or service failures. End session clears demo changes. The EPR workbench at `/epr/` and the B12 archive at `/b12/` retain their recorded workflows.

The preset specifications and approvals come from the WO-8 service. Its calibration fixture supplies the complete synthetic frozen fit. Their digests and corresponding records are in [the producer fixture](fixtures/workspace/producer-records.json). Regenerate it with `python -m tests.test_workspace_golden --write` in the project Python environment. Specifications created or edited in a browser tab have fixture-local records and approvals.

**Live workspace** uses the versioned workspace API at the same origin, or at the trusted origin supplied through `NEXT_PUBLIC_WORKSPACE_API_URL` at build time. It sends the workspace session cookie and requires a project ID. Vercel previews use fixtures only and display the source commit from `VERCEL_GIT_COMMIT_SHA`. Live smoke testing requires the authenticated WO-12 service and WO-11 evidence endpoint.

Run `npm ci`, `npx playwright install chromium`, `npm run build` and `uv run --frozen npm test` to exercise the production export. Browser tests use isolated fixture data and intercepted API responses. The Python producer independently verifies downloaded session evidence.

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

For serial virtual UV–Vis experiments, see the [local scheduler and two-experiment test](docs/EXPERIMENT-SCHEDULER.md).

## Third-party software, services and data

| Tool or material | Use in EVOLVE | License or governing terms |
| --- | --- | --- |
| 8090 Software Factory and MCP | Requirements, blueprints and engineering work orders used to build EVOLVE | Sponsor-provided service under the Hackathon Participant Agreement, §11. [Event rules](https://evolve-8090.devpost.com/rules) |
| 8090 Software Factory plugin | Work-order skill and templates in `.agents/skills/software-factory/` | MIT. Copyright (c) 2026 8090 Solutions Inc. [Upstream license](https://github.com/8090-inc/software-factory-plugin/blob/main/LICENSE) |
| OpenAI Codex CLI and hosted model | Development assistance and generation of candidate apps. The EPR generation records identify `gpt-6.1-sol`. | CLI under [Apache-2.0](https://github.com/openai/codex/blob/main/LICENSE). Model access under the applicable [OpenAI terms](https://openai.com/policies/). |
| CPython and uv | Local scientific runtime and reproducible environment | Python Software Foundation License and bundled notices. uv is available under MIT or Apache-2.0. |
| jsonschema, jsonschema-specifications, attrs, referencing, rpds-py | Validate lab records and work orders | MIT. The conditional typing-extensions dependency uses the Python Software Foundation License. |
| macOS Seatbelt or Linux bubblewrap | Isolate generated Python during verification and replay | Seatbelt is supplied under the macOS software license. bubblewrap uses [LGPL-2.0-or-later](https://github.com/containers/bubblewrap/blob/main/bubblewrap.c). |
| Node.js, npm CLI, Next.js, React and React DOM | Build and serve the evidence workbench | Node.js, Next.js, React and React DOM use MIT with applicable bundled notices. npm CLI uses Artistic-2.0. |
| Pyodide | Replay archived Python in the browser | MPL-2.0. Bundled CPython, Emscripten and other components retain their upstream licenses. [Pyodide distribution](https://github.com/pyodide/pyodide) |
| Lucide React and Instrument Sans via Fontsource | Interface icons and typeface | Lucide uses ISC with MIT notices for Feather-derived icons. Instrument Sans uses SIL Open Font License 1.1. |
| TypeScript, @types/node and @types/react | Type-check the researcher workspace | TypeScript uses Apache-2.0. Both type definition packages use MIT. |
| Playwright and Chromium | Browser tests | Playwright uses Apache-2.0. Chromium uses a BSD-style license with additional component notices. |
| GitHub, GitHub CLI and GitHub Actions | Source hosting, review and automated tests | GitHub CLI, actions/checkout, actions/setup-node and astral-sh/setup-uv use MIT. Hosted services follow the [GitHub terms](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service). |
| Vercel and Vercel CLI | Web hosting and deployment | CLI under [Apache-2.0](https://github.com/vercel/vercel/blob/main/packages/cli/package.json). Hosting under [Vercel’s terms](https://vercel.com/legal/terms). |

The Python and JavaScript lockfiles identify the resolved package versions and transitive dependencies. [uv.lock](uv.lock) · [package-lock.json](package-lock.json)

**Scientific sources.** The external B12 benchmark transcribes six mean absorbances and their concentration labels from the commercial-instrument column of Table 1 in Laganovska et al., *Portable low-cost open-source wireless spectrophotometer for fast and reliable measurements* (2020). The simulated readings are generated separately. The B12 design notes cite the absorption coefficient from Ahmad et al., and the EPR instrument record credits Bruker’s *Xenon* primer for linewidth background. [Laganovska et al.](https://pmc.ncbi.nlm.nih.gov/articles/PMC9041175/) · [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) · [B12 design references](docs/B12-DEMO-PLAN.md) · [EPR instrument record](registry/instrument.json)

## Event use and credentials

The local demo uses simulated instruments and needs no 8090 credentials. At the event, use only designated EVOLVE areas and the equipment, systems and networks provided for the event. For fresh generation, authenticate Codex locally. Keep API keys, credentials and access tokens out of source files, evidence exports, screenshots and presentations. Local `.env*` files are excluded by [.gitignore](.gitignore).

## Project license

Copyright (c) 2026 Scientific Software Factory contributors. The team licenses its hackathon contributions under the [MIT License](LICENSE). Third-party software, services and data retain the licenses and terms listed above.
