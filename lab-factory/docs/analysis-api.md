# General analysis API

One work order pins an uploaded protocol, a column mapping, optional reference-library editions, units, standards and the original batch of readings. The same endpoints support both example datasets in `examples/tabular/`. The caffeine protocol uses integrated HPLC peak areas. The density protocol uses net mass and measured volume. Both datasets are simulated.

## Try the hosted service

Run these commands from `lab-factory/`. The client connects to the public demo without a reviewer name, password or cookie. Anyone with the URL can download uploaded files, inspect control reports, approve or reject submissions, and run released analyses. Use the simulated datasets below or other data you can share publicly.

```sh
uv sync --locked
uv run --locked python examples/analysis_client.py create --example caffeine
uv run --locked python examples/analysis_client.py create --example density
uv run --locked python examples/analysis_client.py list
```

Set `order` to a returned ID. When the status is `in_review`, inspect the source, authored tests, artifact digest, and blind-control report. After reviewing the result you can approve the exact submission and run its original batch.

```sh
order=WO-N
uv run --locked python examples/analysis_client.py show "$order"
uv run --locked python examples/analysis_client.py approve "$order" --submission 1
uv run --locked python examples/analysis_client.py run "$order" --submission 1
```

For your own experiment, use `create --config mapping.json --protocol protocol.md --csv readings.csv --control certificate.json`. The config contains `objective`, `unit`, `mapping` and `range_gate`. The certificate contains numeric `expected` and `tolerance` on the reported sample basis. For a new batch use `run "$order" --submission 1 --csv next.csv --control next-certificate.json`.

## HTTP contract

Send JSON writes with the lab’s origin in the `Origin` header and `Content-Type: application/json`. A public deployment identifies itself with `"access_mode": "public"` at `GET /api/session`. Send reviewer requests directly. All public decisions use the same reviewer identity.

Other deployments require named reviewer sign-in by default. There, use `POST /api/login` with `name` and `password` and keep the session cookie. To use the example client against a named deployment, pass `--url https://your-lab.example` before the command. Set `LAB_FACTORY_REVIEWER` or enter the reviewer name at its prompt. The client prompts for the password or reads the file named in `LAB_FACTORY_REVIEWER_PASSWORD_FILE`, and signs out after each command.

| Method and path | Request or result |
| --- | --- |
| `POST /api/analysis/orders` | Send `objective, protocol_name, protocol, csv_name, csv, mapping, unit, control_expected, control_tolerance`. Optional `range_gate` (defaults true), `reference_ids` and a UUID `request_id`. Returns an open order ID. Reuse a request ID with the identical upload to retry creation. |
| `GET /api/analysis` | Lists general analysis orders with their statuses. |
| `GET /api/analysis/orders/{id}` | Returns the numbered submissions, exact source and tests, numerical control reports, approval history and run receipts. |
| `GET /api/analysis/orders/{id}/uploads/protocol`, `.../uploads/readings` | Downloads the original UTF-8 protocol or CSV. |
| `POST /api/analysis/orders/{id}/control` | After a used control and a failed or rejected submission, provide a fresh `signal, factor, expected, tolerance` before another blind verification. |
| `POST /api/orders/{id}/approve` or `.../reject` | Send a positive integer `submission`; rejection also requires `reason`. Approval binds the reviewed artifact digest. |
| `POST /api/analysis/orders/{id}/runs` | Send `submission` for the original batch. For a new batch also send `csv_name, csv, control_expected, control_tolerance`. The same released program receives the new standards. |
| `GET /api/analysis/orders/{id}/runs/{run_id}/readings` | Downloads the CSV for a saved run. |

The intake accepts UTF-8 TXT/Markdown protocols and rectangular CSVs with unique headers and IDs. Map `id,role,signal` to the uploaded column names, and optionally `known,factor`. CSV roles are `standard`, `control`, and `unknown`. Enter known values on standard rows only. Each batch requires one control and at least one unknown. A missing factor mapping uses 1, so identify any required dilution or volume explicitly. The result unit and sample basis apply to the expected control value and its absolute tolerance. With the range gate enabled, at least two distinct standard signals are required and every evaluated signal must be within their interval. The direct-density example switches this gate off.

## What the verifier establishes

The Mac worker reads the disclosed protocol, mapping, standards, result unit and selected references through the existing four MCP tools. It writes a numerical Python function plus its explanation and tests. The host interprets a bounded arithmetic subset of Python with helpers for regression, reductions and scalar math. The execution environment supplies one anonymous signal and row factor at a time. The MCP author context omits the raw CSV, sample IDs, unknown readings, control readings and certificate values. Keep expected answers out of the uploaded protocol, objective and references. In the public demo anyone can use the reviewer API to download the CSV, inspect a completed control report, or replace an eligible used control. Keeping the check blind relies on the author using only the MCP interface.

Public test failures can be repaired with the same sealed control. Once a candidate reaches the blind check, its number, source digest, and control edition identify the attempt. The worker receives the decision, and the reviewer sees the assigned value, prediction, absolute error, tolerance and unit. Each new batch has its own control. A failed control withholds all unknowns. An individual out-of-range reading withholds that sample. Passing a simulated control tests the calculation at that point; physical instrument performance requires separate measurements.

## Background author on the lab Mac

The Vercel service retains the orders. The user-selected author uses the existing local Codex sign-in and a dedicated MCP worker token. From a committed release on macOS, install it as the signed-in user's background job:

```sh
python3 scripts/install_analysis_worker.py --url https://neal-lab-factory.vercel.app/mcp \
  --worker lab-agent --token-file "$HOME/.config/labfactory/neal-lab-factory/agent-token"
launchctl print "gui/$(id -u)/com.labfactory.analysis-author"
```

It checks the queue at login and every 90 seconds while the Mac is awake and online. An interrupted claim can be resumed by the same worker. The installed worker uses a version-specific Python environment under `~/.local/share/labfactory/analysis-worker/`. Its logs are in the `logs/` subdirectory. An explicit `needs_input` stops that order for reviewer attention. Correct incomplete inputs by creating a new order with a revised protocol or mapping. To process one order manually, run `python -m labfactory.tabular_worker --url URL/mcp --worker NAME --token-file PATH --order WO-N` in the project environment.
