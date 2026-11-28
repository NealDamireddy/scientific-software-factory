# Lab Factory

Lab Factory stores immutable revisions of lab and experiment records and pins both when you create a work order. An agent claims the order over MCP and submits a procedure, run plan or analysis for checks against that context. A reviewer can inspect each submission, reject it with a reason, or release a passing submission by number. [Open the reviewer portal](https://neal-lab-factory.vercel.app/)

## Shared lab on Vercel

The shared demo opens with public reviewer access. Anyone with the URL can download existing and new uploads, inspect control reports, replace a used control when the workflow allows it, approve or reject submissions, and run released analyses. Public decisions use one shared reviewer identity. Use data you can share publicly.

Choose **EVOLVE demos** for the EPR workbench, recorded B12 experiment and simulated UV–Vis workspace. These pages use the same site as the reviewer. Choose **B12 analysis** in the reviewer to start a new analysis order, or open the recorded dilution experiment from that page. [Start the combined app locally](../README.md#run-the-app)

### Upload a protocol and readings

Use the [general analysis API and reviewer quickstart](docs/analysis-api.md) to submit a protocol and CSV, inspect a worker-written analysis and compare its prediction with a blind control before approval. Caffeine calibration and direct liquid density use the same backend.

### Find evidence for an experiment

Open the [reference library](https://neal-lab-factory.vercel.app/#references). Leave **All instruments** selected if you do not know the model, choose a technique, or filter by a model number. Enter an objective or choose an example such as **Caffeine in coffee** or **Identify a polymer**. Each finding links to its source and identifies the relevant pages, edition, model relationship and limits.

After choosing a model, use **Browse experiments** to see objectives with a manual, a published method and primary research. For instance, the Hanna HI96800 offers honey moisture and juice soluble solids. The Olympus CX23 offers honey pollen identification and leaf stomatal density. The Agilent 7890B offers beverage ethanol, vegetable-oil fatty acids and olive-oil aroma. Each guide lists the additional equipment or sample conditions that matter. The selection is saved with the exact references you pin.

For the Agilent 1260 Infinity Binary LC, the coffee search pairs the instrument guide with an Agilent method that used that system and independent research on different equipment. Compare the equipment, sample and calibration before adopting a method. Select the records you want and choose **Create order with sources**. The reviewer and a connected agent can reopen the same record versions and cite them in a procedure submission.

To run the same search locally through an MCP client, run these commands from `lab-factory/`. Omit the objective and instrument arguments to list all available models and technique scopes.

```sh
uv sync --locked
uv run --locked python examples/find_references.py --instrument agilent-1260-infinity-binary-lc "Measure caffeine in coffee"
uv run --locked python examples/find_references.py --instrument hanna-hi96800 "Measure honey moisture"
```

### Review and run the honey moisture analysis

1. Open [Honey moisture](https://neal-lab-factory.vercel.app/#honey) and select an order marked **In review**. The submission shows how the agent uses each of four publications, its calculation, its conversion table, and its numerical tests.
2. Inspect the numbered submission. The independent checks compare all 61 table entries with the International Honey Commission table and all 601 possible mean readings with the expected one-decimal results. Choose **Approve submission** and then **Approve and release** when you are satisfied.
3. Enter `1.4914` and `1.4916` as two simulated measurements of the same sample on the Hanna HI96800 nD20 scale at 20 °C. Choose **Calculate honey moisture**. The result is **18.0 g water per 100 g honey**. Reopen the order to see the inputs, result, reviewer and approved artifact digest.

**Create honey analysis order** opens a fresh order for a connected coding agent. It pins the instrument, objective and four source records. The agent reads the linked publications, writes a calculation and numerical tests, and submits them over MCP. The example submitted for this demonstration is in `examples/honey-analysis.json`. To replay it on a new open order, run the following from `lab-factory/` with your issued agent token in `LAB_FACTORY_AGENT_TOKEN`. Replace `WO-N` with the new order ID and use the worker name assigned to your token.

```sh
uv sync --locked
uv run --locked python examples/submit_honey_analysis.py WO-N --worker lab-agent --url https://neal-lab-factory.vercel.app/mcp
```

### Try the simulated B12 analysis

Use this example to review a calculation and run it on supplied absorbance readings. To see a simulated instrument acquire readings and a coding worker build a second app after dilution approval, open the [EVOLVE demo guide](../EVOLVE.md#run-the-demo).

1. Open [B12 analysis](https://neal-lab-factory.vercel.app/#b12). **Start B12 example** opens a fresh review of the bundled Codex-written Python and runs the factory’s independent reference tests. You can also open an analysis order already submitted by a connected agent.
2. Enter three simulated absorbance readings in AU. Try `0.1020`, `0.1024`, and `0.1028`. Save the readings. They stay with the order while you review the source.
3. Inspect the exact Python, worker, numbered submission and reference results. The tests cover both calibration endpoints, unequal readings, a different slope, and a nonzero intercept. Approve the displayed submission and confirm your decision.
4. Select **Run analysis** on the saved readings. The example returns **16 mg/L**. Try `0.09`, `0.10`, and `0.16` on the same release to see the third replicate put the sample outside the calibrated range. The result and its provenance remain available when you reopen the order.

The fixture represents absorbance at 550 nm with a fixed simulated slope of 0.0064 AU per mg/L and zero intercept. All three readings must lie between 0.0192 and 0.1536 AU, inclusive. The evaluator interprets a bounded arithmetic subset of Python and checks each returned concentration against the frozen calibration. Scope is simulated absorbance inputs. The app records the input readings, pinned context, calibration, reviewer, and digest of the source that produced each result.

### Work orders and agents

Open the [reviewer portal](https://neal-lab-factory.vercel.app/). The portal shows work orders, numbered submissions, checked instructions, artifacts and decision history. Under **Lab context**, create an example using the UV-visible spectrophotometer, or import your own lab and experiment JSON and create an order in **Work orders**.

To submit a newly created example from this directory, set `LAB_FACTORY_AGENT_TOKEN` to your issued agent token. Supply the open order ID shown in the portal and the worker name assigned to that token.

```sh
uv sync --locked
read -r 'order?Open example work order ID: '
uv run --locked python examples/submit_remote_example.py "$order" \
  --url https://neal-lab-factory.vercel.app/mcp --worker lab-agent
```

For a honey fixture upload or an analysis source upload with `--source` (local or hosted), save the claim ID when you take the order and pass it as `--claim-id ID` when uploading work from that claim. A bound upload requires that claim to still be active for your worker. Omitting the flag sends an untagged upload. For an open order, the uploader passes the payload as `untagged_artifact` to `claim_work_order`, which checks untagged eligibility before acquiring the claim.

The prompt above uses zsh. In the browser, open the order and select **Refresh**. Inspect the instrument, command, wavelength, checks and digest, then approve the numbered submission or reject it with a reason. The portal opens the latest submission first and loads earlier artifacts and history on demand. A rejection reopens the order for an agent. The history records the reviewer identity used for each decision and the digest of each approved artifact.

To connect a Codex agent from a shell that has the token, run

```sh
codex mcp add lab-factory --url https://neal-lab-factory.vercel.app/mcp \
  --bearer-token-env-var LAB_FACTORY_AGENT_TOKEN
```

Launch the agent from that environment. Its worker name is listed under **Agent access**. Your deployment administrator issues each worker its own token. [Hosted deployment and access management](docs/hosted.md)

## Local quickstart

Run these commands from `lab-factory/` with uv and Python 3.11 or newer. They use a fresh SQLite database and the example UV-visible spectrophotometer.

```sh
uv sync --locked
db="$(mktemp -d)/labfactory.db"
uv run --locked labfactory --db "$db" lab put examples/uvvis-lab.json
uv run --locked labfactory --db "$db" experiment put examples/b12-experiment.json
uv run --locked labfactory --db "$db" wo create b12-vial-a --kind run_plan --objective "Read the reference solution at 550 nm"
uv run --locked python examples/submit_example.py "$db" WO-1
uv run --locked labfactory --db "$db" wo show WO-1
```

Both records should be at revision 1. The example client starts the stdio server, lists its tools, claims WO-1, reads its pinned context and submits the example artifact. In the CLI output, check submission 1, instrument `uvvis-1`, command `read_absorbance`, and wavelength `550 nm` before approving. In the same shell, record your decision and inspect the release.

```sh
uv run --locked labfactory --db "$db" wo approve WO-1 --submission 1 --by "Local reviewer"
uv run --locked labfactory --db "$db" wo show WO-1
```

Look for `released: submission 1 by Local reviewer` and the approved artifact’s SHA-256 digest in the history. To run the tests, use `uv run --locked pytest -v`.

During local review, use [`wo citation`](#inspect-a-pinned-citation) to read a cited document.

### Inspect a pinned citation

Run `labfactory --db PATH wo citation ORDER DOCUMENT_ID` to see the document's origin, record ID and revision, document ID, kind, title, source, and full stored text. For example, inspect the lab SOP pinned to the quickstart order.

```sh
uv run --locked labfactory --db "$db" wo citation WO-1 sop-cuvette
```

The document ID must match exactly one document across the order's pinned lab and experiment revisions. Unknown IDs and IDs found in both records produce an error.

### Recover an abandoned claim

In the reviewer portal, open the in-progress order, choose **Requeue claim**, and enter the reason. From the local CLI, read the active claim number with `wo show`, then requeue that specific claim. For example, if WO-1 shows `claim: 2`, run

```sh
uv run --locked labfactory --db "$db" wo requeue WO-1 --claim 2 --by "Local reviewer" --reason "The worker disconnected"
```

The order reopens with its original pins, submissions and audit history. A stale claim number leaves the current claim intact. Private deployments record the signed-in reviewer. The public demo records its shared reviewer identity.

## Web UI

The combined reviewer portal runs at `/` and links to the EVOLVE evidence demos at `/evolve/`. The standalone researcher interface in `web/` provides sample projects, procedure and run-plan review, and browser-side analysis and simulation. To launch its sample mode or develop against its live API contract, see the [researcher web UI guide](web/README.md).

## Reviewer API and remote workers

The reviewer HTTP API and authenticated MCP endpoint share the versioned records used by the CLI. A reviewer can connect an uploaded analysis to a released procedure and trace a saved result back to its approved submission, instrument record and SOP revision. Read the [backend setup and analysis workflow](docs/analysis-api.md) for authentication, storage, sample requests and backup requirements.

## Connect a coding agent

Use absolute paths to the project and the database containing your lab’s work orders. To connect Claude Code to the quickstart database from the same shell, run

```sh
claude mcp add labfactory -- uv run --locked --project "$PWD" labfactory --db "$db" serve
```

For Codex, use this entry in `~/.codex/config.toml`, substituting your project and database paths. Each path is a single argument, including spaces.

```toml
[mcp_servers.labfactory]
command = "uv"
args = ["run", "--locked", "--project", "/absolute/path to/lab-factory", "labfactory", "--db", "/absolute/path to/labfactory.db", "serve"]
```

The four agent tools are `list_work_orders`, `claim_work_order`, `get_work_order_context`, and `submit_artifact`. A rejected order reopens with the submitted artifact and reviewer's reason in its context.

`get_work_order_context` also returns the briefing: the `skills` pinned to the work and a `reference_library` of suggested sources matched to the objective and instruments. A procedure work order returns it as a top-level `briefing` field; an analysis request (`APP-` or `PLOT-`) returns it at `contexts[0].briefing` inside `offline_app` or `drift_plot`. Suggested sources are pointers only; a worker cannot cite one until its text is added to the project.

Before starting work, save the `claim_id` returned by `claim_work_order` or, when resuming your active claim, by `get_work_order_context` under `work_order`. Pass that ID to `submit_artifact` and reuse it on every retry of the same work. If the claim was recovered and the same worker later reclaimed the order, submissions under the new claim require its ID.

After a rejection, a worker can still submit a revised artifact without a claim ID if their earlier claim on that order was never recovered. Sending an artifact with the same digest as any of that worker's rejected submissions on the order requires the current claim ID.

## Release and review

For run plans and procedure actions, checks verify the instrument, command, required and allowed settings, units, and inclusive limits. Procedure checks also resolve each step’s citations, verify that hand-measured amounts have known units, and flag numeric unit expressions such as `550nm` and `5 minutes` in notes. The structured action supplies the checked instruction. The matcher covers the expressions listed in the core plan. Free-text notes and hand-measured amounts still require human judgment.

A citation must identify exactly one document across the pinned lab and experiment. `wo show` displays the checks recorded at submission. Approval runs the current checks against the same pinned revisions, including for submissions awaiting review during an upgrade. If an updated check fails, reject that submission with the reason so the next worker can correct it.

**What a release certifies.** Against the pinned revisions, every check above passed for the exact artifact whose digest the approval recorded, and a named person approved that submission. It does not certify that the instrument's driver implements a command correctly, which is the instrument agent's job, or that the science is right, which is the reviewer's job.

**Trust assumption.** Local approval uses the identity supplied to `labfactory wo approve`. A process with shell access as that user can run the command. The hosted API authenticates reviewers and MCP workers separately. Named sign-in is the default. Deployments that explicitly enable public review give every visitor reviewer access under one shared identity.
