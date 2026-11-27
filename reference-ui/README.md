# Emory Biophysics reference UI

A standalone Next.js and TypeScript prototype for visual review. All scientific records, approvals, and instrument activity are illustrative. Local browser storage holds demo changes. Use a separate browser profile for a fresh workspace.

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
npm start
```

## Automatic experiment context

Create a reusable procedure in **Skills** and enable it. Add a service in **Connectors** and choose **Connect** to include its simulated connection. Start an experiment to capture the current selection for the simulated coding agent. Each run keeps its own snapshot in Evidence, so later edits apply to subsequent runs. **Settings → Download agent context** also provides a manual copy of the current configuration.

In Evidence, expand a run under **Agent context by run** to inspect the instructions, selected connectors, and any simulated review findings. Calibration review and Evidence summary can produce findings from the illustrative readings. Custom skills appear as loaded instructions.

The export contains the active skill instructions and when to apply them, alongside the selected connector descriptions and any configured endpoint. A coding agent can use it to select a workflow or plan an integration. A simulated connector describes configuration only. A live implementation would need its own authenticated MCP client and tool discovery.
