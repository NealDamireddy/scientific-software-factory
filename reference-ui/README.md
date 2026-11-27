# Emory Biophysics reference UI

A Next.js and TypeScript research workspace with a simulated experiment workflow and a local measurement-record reviewer. The experiment fixtures, instrument activity and approvals are illustrative. The record reviewer works on measurements you supply. Local browser storage holds demo changes. Use a separate browser profile for a fresh workspace.

## Run locally

From this directory with Node.js 22.6 or newer, run the workspace on the loopback address printed by Next.js. Live skill delivery also uses Python 3.11+ on macOS or Linux and a signed-in Codex CLI on the server’s PATH.

```sh
npm ci
npm run dev
```

For a production build on your own machine, use `npm run build` and `npm run start:local`. The ordinary hosted start command keeps the local worker disabled.

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

Enable a built-in or custom skill in **Skills**, then start an experiment. The local workspace sends its objective, project, simulated method, instrument, run mode and the enabled skill instructions to the signed-in Codex worker. A repeat takes a fresh snapshot. Connector addresses and harness settings stay in the workspace. The worker returns a planning review. Measurements, instrument control and scientific approvals remain simulated.

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
