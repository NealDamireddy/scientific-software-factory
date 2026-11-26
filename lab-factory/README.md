# Lab Factory

Lab Factory stores immutable revisions of lab and experiment records and pins both when you create a work order. An agent claims the order over MCP and submits a procedure or run plan for checks against the pinned context. A local reviewer can inspect each submission, reject it with a reason, or release a passing submission by number.

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

## Web UI

The browser interface lives in `web/`. See [web/README.md](web/README.md).

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

**Trust assumption.** Agents connected over MCP cannot approve or release work; only `labfactory wo approve` does, and it names the exact submission a person reviewed. The core does not stop an agent that has shell access as your computer user from running that command itself. If that matters for your lab, don't give coding agents a shell on the machine that holds the database. Enforced human-only release comes with the hosted lab deployment.
