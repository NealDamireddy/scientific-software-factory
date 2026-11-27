# Emory Biophysics reference UI

A Next.js and TypeScript research workspace with a simulated experiment workflow and a local measurement-record reviewer. The experiment fixtures, instrument activity and approvals are illustrative. The record reviewer works on measurements you supply. Local browser storage holds demo changes. Use a separate browser profile for a fresh workspace.

## Run locally

From this directory with Node.js 22 or newer:

```sh
npm ci
npm run dev
```

Open the localhost address printed by Next.js. The app includes its Geist font files through the Geist package.

## Review the B12 workflow

1. Enter “Vitamin B12 concentration” in the homepage composer and select the B12 project.
2. Open the draft and start the simulation. Inspect the flagged original sample alongside its calibration range.
3. Request changes and resubmit, or approve a simulated repeat. Compare the original and repeated runs and inspect their evidence.
4. Open the seeded absorbance time course to compare the two visualization types.

## Verify the build

```sh
npm run build
npm run typecheck
node --experimental-strip-types --test app/*.test.mjs app/review-skills/*.test.mjs
npm start
```

## Automatic experiment context

Create a reusable procedure in **Skills** and enable it. Add a service in **Connectors** and choose **Connect** to include its simulated connection. Start an experiment to capture the current selection for the simulated coding agent. Each run keeps its own snapshot in Evidence, so later edits apply to subsequent runs. **Settings → Download agent context** also provides a manual copy of the current configuration.

In Evidence, expand a run under **Agent context by run** to inspect the instructions, selected connectors, and any simulated review findings. The built-in skills are grouped by family in Skills. Enable individual checks before starting the experiment. Checks apply at start, result, or repeat according to the available evidence. Each applicable check records its stage, verdict and evidence references. Custom skills appear as loaded instructions.

The export contains the active skill instructions and when to apply them, alongside the selected connector descriptions and any configured endpoint. A coding agent can use it to select a workflow or plan an integration. A simulated connector describes configuration only. A live implementation would need its own authenticated MCP client and tool discovery.

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
