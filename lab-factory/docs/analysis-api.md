# Lab Factory backend API

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

## Upload and run an analysis

The client requires an explicit service origin. The two example datasets use simulated caffeine measurements and liquid density. For a named deployment it prompts for credentials or reads the reviewer name and password-file path from `LAB_FACTORY_REVIEWER` and `LAB_FACTORY_REVIEWER_PASSWORD_FILE`.

```sh
lab_url=https://lab.example.org
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

## Storage and recovery

For remote SQL, configure `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN`. A small hosted lab can instead use an 8 MiB SQLite snapshot in a private Blob store configured with `BLOB_READ_WRITE_TOKEN`. Changing backend selects a different database. Migrate and verify the records before switching.

When Blob holds uploaded files, back up the database **and** every referenced `uploads/<sha256>` object under the snapshot prefix. This applies to both Blob snapshots and Turso with Blob uploads. Snapshot-only storage uses `labfactory/lab.sqlite3` by default. During recovery, restore the database and uploads to a private destination and verify that the protocol and readings download with the SHA-256 hashes from their saved records. With database-only storage, the original file bytes are stored in the database.
