# Lab Factory

Lab Factory stores immutable revisions of lab and experiment records and pins both when you create a work order. An agent claims the order over MCP and submits a procedure or run plan for checks against the pinned context. A local reviewer can inspect each submission, reject it with a reason, or release a passing submission by number.

## Shared lab on Vercel

Open the [reviewer portal](https://neal-lab-factory.vercel.app/) and sign in with your named reviewer account. The portal shows work orders, numbered submissions, checked instructions, artifacts and decision history. Under **Lab context**, create an example using the UV-visible spectrophotometer, or import your own lab and experiment JSON and create an order in **Work orders**.

To submit a newly created example from this directory, set `LAB_FACTORY_AGENT_TOKEN` to your issued agent token. Supply the open order ID shown in the portal and the worker name assigned to that token.

```sh
uv sync --locked
read -r 'order?Open example work order ID: '
uv run --locked python examples/submit_remote_example.py "$order" \
  --url https://neal-lab-factory.vercel.app/mcp --worker lab-agent
```

The prompt above uses zsh. In the browser, open the order and select **Refresh**. Inspect the instrument, command, wavelength, checks and digest, then approve the numbered submission or reject it with a reason. The portal opens the latest submission first and loads earlier artifacts and history on demand. A rejection reopens the order for an agent. The history records the signed-in reviewer and the digest of each approved artifact.

To connect a Codex agent from a shell that has the token, run

```sh
codex mcp add lab-factory --url https://neal-lab-factory.vercel.app/mcp \
  --bearer-token-env-var LAB_FACTORY_AGENT_TOKEN
```

Launch the agent from that environment. Its worker name is listed under **Agent access**. Your deployment administrator can issue separate credentials for each worker and reviewer. [Hosted deployment and access management](docs/hosted.md)

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

## Release and review

For run plans and procedure actions, checks verify the instrument, command, required and allowed settings, units, and inclusive limits. Procedure checks also resolve each step’s citations, verify that hand-measured amounts have known units, and flag numeric unit expressions such as `550nm` and `5 minutes` in notes. The structured action supplies the checked instruction. The matcher covers the expressions listed in the core plan. Free-text notes and hand-measured amounts still require human judgment.

A citation must identify exactly one document across the pinned lab and experiment. `wo show` displays the checks recorded at submission. Approval runs the current checks against the same pinned revisions, including for submissions awaiting review during an upgrade. If an updated check fails, reject that submission with the reason so the next worker can correct it.

**What a release certifies.** Against the pinned revisions, every check above passed for the exact artifact whose digest the approval recorded, and a named person approved that submission. It does not certify that the instrument's driver implements a command correctly, which is the instrument agent's job, or that the science is right, which is the reviewer's job.

**Local trust assumption.** The local approval command names the submission and takes the reviewer name from `--by`. A process with shell access as your computer user can run it. For the shared service, the browser signs in as a named reviewer and agents authenticate separately with their own bearer tokens. Keep reviewer passwords, session cookies and deployment credentials outside the agent’s environment.
