# Lab Factory backend API

Open **Analysis** in the combined reviewer portal to upload a protocol and a CSV, inspect the worker’s numerical checks, and review a batch control. The browser and CLI use the same [simulated caffeine and density files](../public/examples/tabular/). [Start the local portal](../../README.md#run-the-app) · [Open the shared analysis demo](https://neal-lab-factory.vercel.app/#analysis)

## Run the service

Run commands from `lab-factory/`. Install the locked environment with `uv sync --locked`. The ASGI application is `labfactory.hosted:application`. Start it behind an HTTPS reverse proxy with the public host preserved. For local development, bind the upstream server to loopback:

```sh
uv run --locked uvicorn labfactory.hosted:application --host 127.0.0.1 --port 8000
```

Configure these environment variables before starting the service.

| Variable | Purpose |
| --- | --- |
| `LABFACTORY_LOCAL_DB` | Absolute path to a local SQLite database for development. |
| `LABFACTORY_PUBLIC_ORIGIN` | The HTTPS origin clients use. The MCP transport checks this host. |
| `LABFACTORY_AGENTS` | JSON object mapping worker names to SHA-256 digests of distinct, high-entropy bearer tokens. |
| `LABFACTORY_REVIEWERS` | JSON object mapping reviewer names to the salted password verifiers produced by `labfactory.hosted_auth.password_hash`. |
| `LABFACTORY_SESSION_KEY` | Independent random secret of at least 32 characters for signing named reviewer sessions. |

Generate a verifier for each identity using the hidden prompts below. Keep the original secrets in your secret manager. Give each worker only its own token.

```sh
uv run --locked python -c 'from getpass import getpass; from labfactory.hosted_auth import password_hash; print(password_hash(getpass("Reviewer password: ")))'
uv run --locked python -c 'from getpass import getpass; from labfactory.hosted_auth import token_digest; print(token_digest(getpass("Worker token: ")))'
```

Reviewers sign in through `POST /api/login` with `name` and `password`. The server sets a Secure, HttpOnly cookie, so named sessions require HTTPS. For JSON writes, supply the service origin in `Origin` and use `Content-Type: application/json`. Workers authenticate separately with a bearer token at `/mcp`. Worker access is scoped to the lab deployment. A trusted worker can read work-order context across that lab, including the pinned SOPs in a linked experiment. The optional analysis author sends this context to its configured model.

Setting `LABFACTORY_PUBLIC_REVIEW=1` gives anyone who can reach the service reviewer access to **all existing and future records**, including original uploads, control values and approvals. Reserve this mode for a dedicated demonstration database with shareable data. It still requires an agent token map for MCP.

## From a procedure to a result

1. Register the lab and experiment with `POST /api/context/lab` and `POST /api/context/experiment`. See the UV-visible examples in `examples/` for their JSON shapes.
2. Read `GET /api/experiments/{id}` and request a procedure with `POST /api/orders`. Send `experiment_id`, `kind` set to `procedure`, `objective`, `expected_experiment_revision` and `expected_lab_revision`. If either revision changed after the read, the API returns HTTP 409. Refresh before retrying.
3. A worker claims the order and submits it over MCP. Inspect `GET /api/orders/{id}` and `GET /api/orders/{id}/context`, then approve the numbered submission at `POST /api/orders/{id}/approve`.
4. Supply `procedure_order_id` when uploading an analysis. The server verifies the released submission and pins the procedure artifact digest, lab revision and experiment revision. Omitting it creates a standalone analysis.
5. Review the numbered analysis submission and its independent control report, approve it, and request a run. Each linked run receipt records the originating procedure, approved analysis digest and CSV digest. The experiment detail lists linked analyses so you can find them again after an SOP revision.

The link records which procedure the reviewer selected. Physical acquisition and sample identity require evidence from the lab.

## Analysis methods and reference selection

The Lab Factory package implements the analysis-app output described in its [architecture design](specs/2026-11-25-lab-factory-architecture-design.md). Its work orders, storage and releases are separate from EVOLVE's B12 assay at the repository root. Within Lab Factory, an `analysis_app` uses the method bound to its experiment. Each method has its own input validation, verifier and execution endpoint.

| Reviewer workflow | Backend contract |
| --- | --- |
| Simulated B12 | Create an order at `POST /api/b12/orders`, attach simulated readings and run a released analysis on an identified reading. The run records the approved source and pinned calibration. |
| Simulated honey moisture | Create an order at `POST /api/honey/orders`. The work order pins the refractometer and the source editions used for the conversion. The verifier checks the submitted operations and numerical cases. Only a reviewed release can run at `POST /api/honey/orders/{id}/run`. |
| Uploaded tabular data | Create an order at `POST /api/analysis/orders`. Map the columns, provide an independent control and review the submitted calculation. The run verifies the batch control before returning estimates. |
| Published references for a procedure | Browse `GET /api/references` and `GET /api/references/search`, then send the selected records to `POST /api/references/orders`. The order retains the selected editions, publisher links and scope notes. The reviewer and worker can reopen the same citations after a catalog update. |

## Upload and run an analysis

The client requires `--url` before the subcommand. The commands below use the combined local portal. For a named deployment, set `lab_url` to the HTTPS origin of your lab. For the hosted public demo, use `https://neal-lab-factory.vercel.app` and upload only data you can share publicly. The two example datasets use simulated caffeine measurements and liquid density. For a named deployment it prompts for credentials or reads the reviewer name and password-file path from `LAB_FACTORY_REVIEWER` and `LAB_FACTORY_REVIEWER_PASSWORD_FILE`.

```sh
lab_url=http://127.0.0.1:8000
uv run --locked python examples/analysis_client.py --url "$lab_url" create --example caffeine
uv run --locked python examples/analysis_client.py --url "$lab_url" list
```

Use the order ID returned by the server to inspect, approve and run a submission. Substitute the number you actually reviewed:

```sh
order=WO-N
uv run --locked python examples/analysis_client.py --url "$lab_url" show "$order"
uv run --locked python examples/analysis_client.py --url "$lab_url" approve "$order" --submission 1
uv run --locked python examples/analysis_client.py --url "$lab_url" run "$order" --submission 1
```

| Method and path | Request or result |
| --- | --- |
| `POST /api/analysis/orders` | Supply the protocol and CSV text and filenames, `objective`, `unit`, `mapping`, `control_expected` and `control_tolerance`. Optional fields include `range_gate`, `reference_ids`, `procedure_order_id` and a UUID `request_id`. Retrying the identical request with that UUID returns the original order. |
| `GET /api/analysis/orders/{id}` | Returns submissions, verification reports, approvals and saved runs. Linked orders expose `analysis.procedure`. |
| `GET /api/analysis/orders/{id}/uploads/protocol` and `…/uploads/readings` | Download the original UTF-8 files. |
| `POST /api/analysis/orders/{id}/control` | Supply a fresh control for program review after a used control and a failed or rejected submission. The original collection control remains attached to its readings. |
| `POST /api/analysis/orders/{id}/runs` | Send `submission` for the original batch. For a new batch, add `csv_name`, `csv`, `control_expected` and `control_tolerance`. A failed batch control withholds the unknown sample results. |
| `GET /api/analysis/orders/{id}/runs/{run_id}/readings` | Download the CSV identified by the saved receipt. |

The CSV mapping identifies sample ID, role, signal and optional standard value and dilution factor. Supply the expected control value separately, in the reported sample unit. Keep it out of the protocol, objective and worker-accessible SOPs. The worker receives the disclosed standards and protocol. The reviewer can inspect the batch control, its prediction and tolerance.

## Background analysis worker

The local Mac author claims uploaded analysis orders over MCP using its own bearer token and submits code for review. See the [background worker setup](hosted.md#background-analysis-worker).

## Storage and recovery

For remote SQL, configure `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN`. A small hosted lab can instead use an 8 MiB SQLite snapshot in a private Blob store configured with `BLOB_READ_WRITE_TOKEN`. Changing backend selects a different database. Migrate and verify the records before switching.

When Blob holds uploaded files, back up the database **and** every referenced `uploads/<sha256>` object under the snapshot prefix. This applies to both Blob snapshots and Turso with Blob uploads. Snapshot-only storage uses `labfactory/lab.sqlite3` by default. During recovery, restore the database and uploads to a private destination and verify that the protocol and readings download with the SHA-256 hashes from their saved records. With database-only storage, the original file bytes are stored in the database.

### Skill versions on uploaded analysis orders

The authenticated order-creation request accepts an optional `skills` array containing the enabled instructions selected for that order. Each entry supplies `id`, `name`, `whenToUse`, and `instructions`. The server calculates a SHA-256 version for each entry and checks any supplied version. The order retains the original instructions. The reviewer can inspect them in the analysis details, and the coding worker receives them with the public experiment fields on every authoring attempt, including retries. Later workspace edits apply to new orders. Orders created without skills continue to work.

## Project-based offline applications

A signed-in researcher can submit a plain-language objective to `POST /api/analysis/apps`. Send the usual same-origin JSON header and a fresh UUID. For example:

```json
{
  "request_id": "eeab0128-ded3-4e60-bb07-92cbe406d25c",
  "objective": "Align my repeated spectra, plot the combined profile and export the numbers.",
  "project": {"experiment_id": "repeat-spectra"}
}
```

The response contains the request ID. The backend pins the saved experiment, its assigned instruments, lab revision, and project documents at creation. Supply `experiment_document_ids` to narrow the project documents or `lab_document_ids` to include selected lab manuals. Supply `lab_revision` and `experiment_revision` to select older records.

The existing authenticated analysis worker discovers these requests in its MCP queue. Read `GET /api/analysis/apps/{id}` for the pinned context, status, and turn history. At `needs_input`, send `{"turn": 1, "answer": "..."}` to `POST /api/analysis/apps/{id}/answers` with the displayed turn number. The same worker command processes the reopened request. At `ready`, download `GET /api/analysis/apps/{id}/app`. The SHA-256 in the detail response covers the exact downloaded bytes.

This path targets offline HTML and JavaScript. The worker authors the analysis, figure, and controls. The backend packages the document in a sandboxed frame and serves an attachment. A ready artifact is a review candidate. Its digest identifies the downloaded bytes. Scientific acceptance requires running independent inputs. Downloading a candidate creates no approved release record. The existing stage recipe uses the same request lifecycle at `/api/analysis/drift`. A completed spectroscopy trial, its control data, and replay instructions are in [the repeated spectra benchmark](../benchmarks/repeated_spectra/README.md).
