# Operating a shared Lab Factory

The Vercel project root is `lab-factory/`. Vercel builds the Python function from `uv.lock`, serves the browser portal from `public/`, and routes the reviewer API and Streamable HTTP MCP through the same application. The existing local CLI and stdio server continue to use the SQLite path supplied on the command line.

## Shared reference collection

The application bundles source metadata, publisher links, evidence locations, original summaries and scope notes. A read-only SQLite index serves the same collection to the signed-in portal and to agents. Search matches indexed terms, handles configured synonyms and ranks findings within the chosen instrument or technique. The evidence brief quotes the collection's summaries and links back to the records. Searches work offline after installation. Opening a publisher's document requires access to that site.

Agents can discover the following JSON resources with MCP resources/list and resources/templates/list over HTTP or stdio.

| Resource URI | Contents |
| --- | --- |
| `labfactory://references/catalog` | Exact model IDs, technique scopes, example queries and source counts |
| `labfactory://references/search/{instrument}/{query}` | Matches, limitations and citations for a URL-encoded objective. Use `all` for a cross-instrument search. |
| `labfactory://references/source/{source_id}` | One current curated record with its publisher link and digest |

Creating a reference work order snapshots only the selected records in the lab's private database. The agent reads that snapshot through `get_work_order_context`. Its document IDs are available for citations. Published procedures enter the work order as external references. Selecting a model supplies planning context. Local firmware, accessories, performance and executable commands still need to be established by the lab. The SHA-256 digest identifies the curated record. The publisher hosts the underlying document.

To expand coverage, add a model to an `instruments*.json` array and records to a source JSON array in `src/labfactory/reference_data/`. Record the publisher, stable URL, edition or DOI, precise locator, scope, technique and search topics. Give each record a unique ID. Link a model only when the manufacturer documents it or the authors say they used it. Technique labels, synonyms and example searches live in `search.json`. Run the suite and check a supported objective and an unsupported one before deploying the edition.

## B12 source and result records

**Start B12 example** submits the checked-in `src/labfactory/b12_example.py` as a bundled example and runs the verifier for this work order. It reuses source written for this simulation. For a new agent-authored implementation, a signed-in reviewer can send `POST /api/b12/orders` with `{"mode":"agent"}` using the portal’s same-origin JSON session. This opens an ordinary MCP work order. The agent receives the pinned protocol and a function signature, writes its implementation, and submits `{"source":"..."}` through the existing tools. The command below submits a source file in the environment of its issued worker.

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
| `LABFACTORY_REVIEWERS` | JSON object mapping reviewer names to salted PBKDF2-SHA256 password verifiers |
| `LABFACTORY_AGENTS` | JSON object mapping unique worker names to SHA-256 digests of separately issued high-entropy tokens |
| `LABFACTORY_SESSION_KEY` | Independent random signing secret, at least 32 characters |

Keep an administrator copy of each verifier map in a password manager or a private directory outside the repository. To add or rotate one credential, generate a random secret in your password manager. From `lab-factory/`, run the matching command below and paste the secret at its hidden prompt. Each command prints only the verifier to place in that identity’s map.

```sh
uv run --locked python -c 'from getpass import getpass; from labfactory.hosted_auth import password_hash; print(password_hash(getpass("Reviewer password: ")))'
uv run --locked python -c 'from getpass import getpass; from labfactory.hosted_auth import token_digest; print(token_digest(getpass("Random agent token: ")))'
```

Preserve the map entries for identities that continue to need access. After changing the production environment, deploy the project again. Restrict or retire previous deployment URLs that still use the old environment. Reviewer sessions expire after eight hours. Changing a reviewer’s verifier or the session signing key invalidates affected sessions on the new deployment.

Give each agent only its own bearer token and worker name. The four MCP tools list work, retrieve pinned context, claim and submit. A reviewer uses the separate browser sign-in to approve or reject. The release event identifies the authenticated reviewer, submission number and reviewed artifact digest. The Vercel project and storage administrators are trusted to manage credentials and stored data.
