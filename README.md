# Lab Factory

Lab Factory brings work orders, review and experiment evidence into one web app. Start at **Work orders** to review lab procedures and analysis software. Choose **EVOLVE demos** to replay a recorded experiment or explore the simulated researcher workspace. [Lab Factory guide](lab-factory/README.md)

## Run the app

With Node.js, npm and uv installed, run these commands from the repository root.

```sh
npm ci
npm start
```

Open [Lab Factory on localhost](http://127.0.0.1:8000/). The local reviewer saves work orders in `runs/lab-factory/portal.sqlite3`. The EVOLVE workbench at `/evolve/` serves recorded evidence from the same site. Its researcher workspace uses simulated data in the browser tab.

| What do you want to do? | Where to start |
| --- | --- |
| Try a protocol and CSV with simulated caffeine or density readings | [Upload and review an analysis](lab-factory/docs/analysis-api.md) |
| Create a local work order, connect an agent, or review a submission | [Local quickstart](lab-factory/README.md#local-quickstart) |
| Find an instrument manual or published method for an experiment | [Reference library guide](lab-factory/README.md#find-evidence-for-an-experiment) |
| Explore the standalone researcher UI with sample projects, browser-side analysis and simulation | [Researcher web UI](lab-factory/web/README.md) |
| Watch a simulated experiment change an analysis app, or replay its evidence | [EVOLVE demo and evidence workbench](EVOLVE.md) |

The shared portal uses public reviewer access. Anyone with its URL can read uploads and make review decisions. Use the supplied examples or data you can share publicly. [Deployment and access](lab-factory/docs/hosted.md)

## Working in the repository

**Lab Factory** lives in `lab-factory/`. Its [Python service, CLI and MCP tools](lab-factory/src/labfactory/) and [reviewer portal](lab-factory/public/) share one deployment. To run its tests, start at the repository root.

```sh
cd lab-factory
uv sync --locked
uv run --locked pytest tests
```

**EVOLVE** supplies the demos. Its Python instrument presenter lives in `factory/`, the web workbench in `app/`, and the recorded runs in `public/b12/` and `public/evidence/`. `npm run build:lab` builds the demo pages into Lab Factory’s static assets. Fresh instrument simulation and app generation run with the local Python presenter. [EVOLVE setup, replay and verification](EVOLVE.md)

If you also see `evolve-ui/` in your working directory, it is a separate local Git checkout.

Both apps use the [local Codex worker launcher](lab-factory/src/lab_codex_worker/). Lab Factory includes it in its Python package, and EVOLVE installs it from this repository with `uv sync --locked`. Each app supplies its own prompt, response schema and timeout.

Both projects have a B12 example. In Lab Factory, a reviewer checks a submitted calculation and runs it on three supplied absorbance readings. In EVOLVE, a simulated instrument measures a sample, the first app withholds an out-of-range result, and an approved dilution prompts a second app revision. Each project has its own release records. [Lab Factory B12 walkthrough](lab-factory/README.md#try-the-simulated-b12-analysis) · [EVOLVE completed run](public/b12/completed.json)

## License

[MIT License](LICENSE) · [EVOLVE third-party notices and scientific sources](EVOLVE.md#third-party-software-services-and-data)
