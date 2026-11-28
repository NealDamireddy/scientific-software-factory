# Emory Biophysics reference UI

The research workspace is the frontend for Lab Factory. Start it from the repository root with `npm ci` and `npm start`. Open the address printed by the launcher. It serves the researcher UI, reviewer API and experiment archives from one origin and saves project records in SQLite.

Use `npm start -- --database "/path/to/portal.sqlite3"` to open an existing local Lab Factory database, including one in another checkout. Use `--temporary` for an isolated session. Add `--drift-worker` to process queued stage plots with the signed-in local Codex worker.

## Start an investigation

1. Open **What are you investigating?** and select or create a project. Existing registered experiments appear as projects.
2. Enter the objective. Lab Factory searches the project's recorded datasets, procedures and apps. A clear request opens the matching record or creates a request in that project. Ambiguous requests show choices in the composer.
3. Reopen the investigation from its project. Download the original readings, answer a draft question, review a submission, or download a completed offline app. **Upload project readings** links a tabular intake to this project. Offline app generation requires a running analysis worker. Source-authored procedure drafts use the backend's signed-in Codex CLI.

Tabular intake can use a saved experiment and selected lab or project documents. Choose the permitted Python or MATLAB profile for a worker submission. Lab Factory records the verifier and checks the submitted calculation against the blind control. The temperature example exercises interpolation against a calibration table. Historical stage plots and unassigned tabular uploads can be added to a project from their detail view. Open **Registered lab context → Request a worker draft** in a project to prepare a source-grounded procedure request in the composer. A worker can ask for a missing passage before review.

Use the sidebar for work orders, analysis runs, references, lab context and agent access. Older simulated experiments remain available in **All experiments**. Skills and record review can also run against local example data.

## Frontend development

For hot reload, run the backend on port 8000 with `LABFACTORY_DEV_UI_ORIGIN=http://127.0.0.1:3100 npm start` from the repository root. From this directory run `npm ci` and `LABFACTORY_API_ORIGIN=http://127.0.0.1:8000 npm run dev -- --port 3100`. Next proxies the requests to Lab Factory. Run `npm run typecheck` and `node --experimental-strip-types --test app/*.test.mjs app/review-skills/*.test.mjs` here. Run `npm run test:lab` at the repository root after the combined build.

## Automatic experiment context

Enable a built-in or custom skill in **Skills**, then open a simulated experiment. When serving from the local Python launcher, set `LAB_LOCAL_EXPERIMENT_WORKER=1` to enable local worker delivery. The local workspace sends its objective, project, simulated method, instrument, run mode and the enabled skill instructions to the signed-in Codex worker. A repeat takes a fresh snapshot. Connector addresses and harness settings stay in the workspace. The worker returns a planning review. Measurements, instrument control and scientific approvals remain simulated.

Open **Evidence → Agent context by run** and expand a run. The worker’s receipt shows its review and the exact SHA-256 version of each skill it received. A version covers the skill ID, name, applicability, instructions and stage. The worker must return the acknowledgement attached to this particular request, and the browser independently checks the versions before showing the receipt. A receipt establishes delivery. The review text shows how the worker responded.

If delivery fails, **Retry delivery** uses the same saved instructions and run ID. A completed receipt can be reopened after a refresh. The server stores completed receipts under `$XDG_STATE_HOME/lab-factory/skill-deliveries` (default `~/.local/state/lab-factory/skill-deliveries`), scoped to the local user. Older runs retain their original evidence. Built-in simulation checks are displayed separately from the worker’s response.

See the [single-skill archive evaluation](evaluation/single-skill-archive/README.md) for the matched comparison.

## Review supplied measurements

In Skills, choose **Review a record** and select a local UTF-8 CSV containing exactly the header columns `sample,measurement,value,unit` (column order may vary). The file limit is 1 MiB or 1,000 observations. Each data row should describe one recorded observation. Preserve sample identity and units when normalizing a vendor export, and retain the original export and mapping. A missing unit is evidence of a gap. The included temperature file is illustrative.

**Data intake and provenance** checks the named input and its row-level traceability. **Claim-to-evidence review** checks one numeric claim against a unique observation or, when explicitly selected, the arithmetic mean of the named group and measurement in the same unit. Ambiguous matches stay unassessed. These local checks do not infer units, convert vendor formats, verify instrument authenticity or decide whether a scientific conclusion is valid.

A coding agent can run the same checks without the browser, with Node 22.6+ and no additional runtime dependencies:

```sh
node --experimental-strip-types scripts/review-record.mjs public/examples/measurement-record.csv
node --experimental-strip-types scripts/review-record.mjs observations.csv --claim claim.json
```

For the illustrative temperature CSV, a claim file could contain:

```json
{"sample":"bath-B","measurement":"reference temperature","value":22.1,"unit":"degC"}
```

For a group mean, add `"statistic":"mean"` to the claim and use the group label in the `sample` field.

The command writes JSON to standard output, including the input digest, observations, claim when supplied, verdicts and row citations. Execution errors return a nonzero exit code. Review findings are advisory and appear in the JSON.

## Portable coding-agent skills

Each folder in `skills/` contains a self-contained `SKILL.md`. Point your agent at the relevant file or copy the desired folders into its supported workspace skill directory. Instructions cover evidence selection, applicability, missing information, stopping conditions and what to cite. The portable instructions support broader reasoning than the deterministic checks in the demo. Run `npm run skills:generate` after changing skill definitions and `npm run skills:check` to verify that all eleven files match the catalog.
