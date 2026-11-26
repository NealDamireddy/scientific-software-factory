# Operating a shared Lab Factory

The Vercel project root is `lab-factory/`. Vercel builds the Python function from `uv.lock`, serves the browser portal from `public/`, and routes the reviewer API and Streamable HTTP MCP through the same application. The existing local CLI and stdio server continue to use the SQLite path supplied on the command line.

## Who can review

The shared Vercel demo uses public reviewer access. Anyone with the URL may read all work orders, download uploaded protocols and readings, inspect numerical control reports, approve or reject a numbered submission, and run an approved analysis. Public reviewers may also submit jobs and supply replacement controls when the workflow allows it. This applies to records uploaded before public review was enabled as well as new uploads. The history keeps prior decisions and attributes new public decisions to a single shared identity.

Other deployments use named reviewer sign-in by default. Set `LABFACTORY_PUBLIC_REVIEW=1` and redeploy to enable public review. To restore named sign-in, configure the reviewer map and session key, remove the flag, and redeploy. MCP workers require their own bearer tokens in both modes.

## Shared reference collection

The application bundles source metadata, publisher links, evidence locations, original summaries and scope notes. A read-only SQLite index serves the same collection to the reviewer portal and to agents. Search matches indexed terms, handles configured synonyms and ranks findings within the chosen instrument or technique. The evidence brief quotes the collection's summaries and links back to the records. Searches work offline after installation. Opening a publisher's document requires access to that site.

Agents can discover the following JSON resources with MCP resources/list and resources/templates/list over HTTP or stdio.

| Resource URI | Contents |
| --- | --- |
| `labfactory://references/catalog` | Exact model IDs, technique scopes, source counts and curated experiments with objectives, source IDs and equipment requirements |
| `labfactory://references/search/{instrument}/{query}` | Matches, limitations and citations for a URL-encoded objective. Use `all` for a cross-instrument search. |
| `labfactory://references/source/{source_id}` | One current curated record with its publisher link and digest |

Creating a reference work order snapshots only the selected records in the lab's private database. The agent reads that snapshot through `get_work_order_context`. Its document IDs are available for citations. Published procedures enter the work order as external references. Selecting a model supplies planning context. Local firmware, accessories, performance and executable commands still need to be established by the lab. The SHA-256 digest identifies the curated record. The publisher hosts the underlying document.

To expand coverage, add a model to an `instruments*.json` array and records to a source JSON array in `src/labfactory/reference_data/`. Record the publisher, stable URL, edition or DOI, precise locator, scope, technique and search topics. Give each record a unique ID. Link a model only when the manufacturer documents it or the authors say they used it. Technique labels, synonyms and example searches live in `search.json`. Run the suite and check a supported objective and an unsupported one before deploying the edition.

The `experiments` entries in `search.json` pair an objective with published procedures, independent research and requirements such as detectors or optical accessories. Each model has at least two guides. The suite runs each applicable guide against each model and checks the citations in the returned brief. For a procedure that explicitly prescribes a model, use `method_instrument_ids`. For equipment the publication actually used, use `instrument_ids`. Record a documented incompatibility in the scope note and `excluded_instrument_ids` so the procedure stays out of searches for that model. Selecting an experiment prioritizes its curated references. A reviewer can also enter a free-text objective.

## Honey analysis submissions

A reviewer creates a honey order from the shared portal. The order pins the HI96800 manual, Hanna’s honey application guide, the IHC method and Barbour et al.’s study. A connected worker gets the references, original publisher links, instrument, objective and submission format from `get_work_order_context`. Creating an order leaves it open for the worker. To replay the previously authored example, use the client command in the README.

The submitted program chooses operations and supplies a conversion table, source roles and numerical tests. The host interprets the submitted operations on decimal numbers. For this example the agent chose to average the duplicate indices, linearly interpolate between tabulated values and round half up to one decimal place. Hanna and IHC publish the table. Interpolation and the reporting rule are choices in this simulation. The paper provides evidence of use on the same instrument. [Hanna application, p. 3](https://hannainst.de/media/8c/17/87/1675090525/Honiganalyse2023.pdf) · [IHC method 1, pp. 10–14](https://www.ihc-platform.net/wp-content/uploads/2024/08/ihcmethods2009.pdf) · [Barbour et al., physicochemical analysis](https://link.springer.com/article/10.1007/s44473-026-00307-1)

The verifier compares the submitted table with a digest calculated independently from the 61 published IHC pairs. It runs the agent’s tests and checks its numerical output for all 601 representable duplicate means in the supported interval. Each input must be a simulated 20 °C nD20 reading in increments of 0.0001. The overlap of the method and meter is 1.4740–1.5040. A reading outside that interval withholds the estimate. The digest on the approval identifies the exact artifact run. A result receipt records both readings, units, approval, worker, and the editions of all four source records. Validation on physical instruments or real honey requires a separate experiment.

## B12 source and result records

**Start B12 example** submits the checked-in `src/labfactory/b12_example.py` as a bundled example and runs the verifier for this work order. It reuses source written for this simulation. For a new agent-authored implementation, a reviewer can send `POST /api/b12/orders` with `{"mode":"agent"}` using a same-origin JSON request. This opens an ordinary MCP work order. The agent receives the pinned protocol and a function signature, writes its implementation, and submits `{"source":"..."}` through the existing tools. The command below submits a source file in the environment of its issued worker.

```sh
uv run --locked python examples/submit_remote_example.py "$order" \
  --url https://neal-lab-factory.vercel.app/mcp --worker lab-agent \
  --source src/labfactory/b12_example.py
```

The factory evaluates arithmetic, local assignments, indexing of the three readings, `sum(readings)` and `len(readings)` in a bounded interpreter. Expected reference values belong to the factory. Approval rechecks the numbered submission. Each saved reading set can be run on that approved release, and repeated requests return its original receipt. Reopening an order retrieves the stored readings, results and review history.

## Storage

The deployed service uses one **private Vercel Blob** in the same region as the function. Each operation reads the current SQLite snapshot, runs the core transaction and conditionally replaces the snapshot using its ETag. A competing write causes the callback to repeat against current history. If an upload loses its acknowledgement, inspect the order and its submission numbers before resubmitting.

The total SQLite snapshot is limited to **8 MiB**, including revisions, submissions and history. This backend is intended for a small lab. Back up the private object `labfactory/lab.sqlite3` to a location your lab controls. The backup is a regular SQLite database and can be opened with the local CLI. Provision a transactional database before growth reaches the limit. The supported Turso configuration uses `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN`. Setting a database URL switches the application to that database, so migrate and verify the existing history first.

Remote artifacts are limited to 128 KiB of compact UTF-8 JSON, 256 steps, 256 settings per action and 256 characters per instrument ID or command. Reviewer JSON imports are limited to 1 MiB per request.

## Production configuration

Link the project directory to the intended Vercel project and connect a **private** Blob store to Production. The integration supplies `BLOB_READ_WRITE_TOKEN`. Use the following additional Production environment variables and redeploy after changes.

| Variable | Value |
| --- | --- |
| `LABFACTORY_PUBLIC_ORIGIN` | The portal’s HTTPS origin, such as `https://neal-lab-factory.vercel.app` |
| `LABFACTORY_PUBLIC_REVIEW` | Set to `1` for public review. Leave unset for named reviewer sign-in. |
| `LABFACTORY_REVIEWERS` | Required for named sign-in. JSON object mapping reviewer names to salted PBKDF2-SHA256 password verifiers. |
| `LABFACTORY_AGENTS` | JSON object mapping unique worker names to SHA-256 digests of separately issued high-entropy tokens |
| `LABFACTORY_SESSION_KEY` | Required for named sign-in. Independent random signing secret, at least 32 characters. |

Keep an administrator copy of each verifier map in a password manager or a private directory outside the repository. To add or rotate one credential, generate a random secret in your password manager. From `lab-factory/`, run the matching command below and paste the secret at its hidden prompt. Each command prints only the verifier to place in that identity’s map.

```sh
uv run --locked python -c 'from getpass import getpass; from labfactory.hosted_auth import password_hash; print(password_hash(getpass("Reviewer password: ")))'
uv run --locked python -c 'from getpass import getpass; from labfactory.hosted_auth import token_digest; print(token_digest(getpass("Random agent token: ")))'
```

Preserve the map entries for identities that continue to need access. After changing the production environment, deploy the project again. Restrict or retire previous deployment URLs that still use the old environment. Named reviewer sessions expire after eight hours. Changing a reviewer’s verifier or the session signing key invalidates affected sessions on the new deployment.

Give each agent only its own bearer token and worker name. The four MCP tools list work, retrieve pinned context, claim and submit. A reviewer can approve or reject using the portal or the reviewer API. The release event records the reviewer identity, submission number and reviewed artifact digest. The Vercel project and storage administrators are trusted to manage credentials and stored data.
