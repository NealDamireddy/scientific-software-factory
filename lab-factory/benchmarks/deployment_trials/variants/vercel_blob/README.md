# Vercel Python with private Blob snapshots

**The pinned backend passed the shared workload, API worker replacement and a restore into a new, empty local Blob service. Live Vercel Preview and managed Blob remain unverified.** The same canonical output SHA-256 appeared in all three runs, `fbcbe5d9a473506b746e2de497749faf587d7c32100721994e8502370fce8b67`. Machine-readable evidence includes the full canonical result, source and fixture hashes, per-scenario status, measured traffic and timings. [Evidence](./evidence.json)

## What ran

The driver extracted Git commit `62badef1d608d94903da475bfd2b689cb80f9c49` to a temporary directory. Uvicorn served the committed `api/index.py` entry point, reviewer API and stateless HTTP MCP implementation. Each storage operation ran the committed adapter and SQLite transaction. A trial-only HTTP transport redirected its private Blob GETs and PUTs to a second process on loopback. The sidecar checked authorization, served strong ETags, enforced create-only and ETag-conditional writes under a lock, and atomically replaced files on disk. Its ETags are quoted SHA-256 digests. The adapter requested `cache=0` and identity encoding when fetching bytes. [API harness](./worker.py) · [Storage sidecar](./blob_sidecar.py)

The shared runner used named reviewer access, two generated agent identities and its explicit loopback HTTP cookie handling. `VERCEL_ENV=preview` enabled the committed guard against an app-local database. A separate certificate-verified HTTPS check ran with `VERCEL=1` and confirmed the actual Secure reviewer cookie authenticated subsequent requests. The Blob selection path had only the disposable Blob token configured. The web UI was outside the test.

A credential-free Vercel CLI 54.18.4 `deploy --dry --format=json` against a fresh archive and empty `--global-config` exited 1 asking for credentials. The workspace already had a root project link. A new private store connection defaults to OIDC, whereas this commit expects a read/write token. Supplying that token to a separate staging project requires explicit provisioning. Hobby includes usage within quota. No cloud resources were provisioned or billed in this trial. [Blob authentication](https://vercel.com/docs/vercel-blob#when-to-use-a-read-write-token) · [Blob usage and pricing](https://vercel.com/docs/vercel-blob/usage-and-pricing)

## Results

| Observation | Measured result |
|---|---|
| Caffeine intake, private control and release | Candidate 1 passed its own tests and failed the independent control. Approval and execution were rejected. A fresh control permitted candidate 2 to pass and produce 24 and 45 mg/L. |
| Density intake and release | Candidate 1 passed and produced 1.08 and 0.80 g/mL. |
| API worker restart | The runner observed an unavailable connection after shutdown. A replacement process at the same origin recovered both releases, their source, uploads, approval history and receipts. Replaying each run returned its saved receipt. |
| Empty-store recovery | A new storage process with an empty directory and fresh token received a backup over HTTP. The restored database and all originals matched their hashes. SQLite integrity and foreign keys passed. |
| Concurrent claims | Two MCP identities produced one winner and one stored claim. A separate race through two simultaneously running API processes also left one claim, visible from both processes. |
| Analysis-worker crash | The pinned worker was killed after committing its claim and before submitting. Another identity could not take the order. A fresh process under the owner's identity submitted the fixed density candidate once, 1.880 seconds after the kill. A third invocation preserved the same submission and history. |

The canonical backup held a **135,168-byte SQLite database plus four external originals totaling 2,213 bytes**. The database included three work orders, three submissions, three control editions, three verification reports, two run receipts and eleven history events. The four originals were the caffeine and density protocols and CSVs. The supplemental worker probes ran after the canonical restore checks. Their extra orders are excluded from these counts.

| Local measurement | Seconds |
|---|---:|
| Acceptance run, including driver startup and login | 1.1195 |
| Start a replacement API process through first successful session request | 0.6251 |
| Verify the replacement worker against prior state | 0.8014 |
| Download and check the complete backup | 0.0175 |
| Restore all objects to an already running empty store and check the snapshot | 0.0231 |
| Verify the new store through the replacement API | 0.8012 |

The acceptance run made 32 successful snapshot GETs, transferred 4,325,376 snapshot bytes on reads, and committed 14 full-object PUTs totaling 1,892,352 bytes. One conditional PUT returned 412 during the run. The recorded byte totals cover successful object payloads. These single-run, same-machine timings do not establish managed-service performance, billing, cold-start behavior, or quota headroom.

## Reproduce locally

From the repository root, use the existing Lab Factory environment, Git and an `openssl` CLI supporting `req -addext`. The commands bind only loopback sockets. Use a new output path to keep the recorded trial for comparison.

```sh
lab-factory/.venv/bin/python -B lab-factory/benchmarks/deployment_trials/variants/vercel_blob/trial.py \
  --output /tmp/vercel-blob-replay.json
lab-factory/.venv/bin/python -B -m pytest -q -p no:cacheprovider \
  lab-factory/benchmarks/deployment_trials/variants/vercel_blob/test_blob_sidecar.py
```

The driver runs the shared `credentials`, `env`, `run`, `offline` and `verify` commands with a fresh private credential file. It validates the shared input manifest against the committed source. It reuses the same runner state and origin across both recoveries. All servers, temporary credentials, local certificate and key, storage directories, backups and logs are removed when the driver exits. The measured artifact digests, canonical outcome and submitted source hashes can be compared across trials. SQLite bytes can vary across independent runs because they include generated identifiers and timestamps. [Trial driver](./trial.py) · [Worker crash probe](./worker_recovery.py)

## Deploy an isolated Preview

The following procedure is for an authorized staging account. The remote build, protected Preview routing, function timeouts, cache consistency and hosted Blob responses still require a live test.

1. In a fresh temporary directory, extract `git archive 62badef1d608d94903da475bfd2b689cb80f9c49 lab-factory`. Link the extracted `lab-factory` directory to a new throwaway Vercel project in the intended staging account. The committed `vercel.json` targets `iad1`, gives `api/index.py` 60 seconds, and routes `/api/*` and `/mcp` to the same function. The project root contains `uv.lock` and `pyproject.toml`. The local harness files are unnecessary for a real deployment. [CLI deployment](https://vercel.com/docs/cli/deploy)
2. Create an empty **private** Blob store in the function region. Connect only the new project's Preview environment and select the option that supplies `BLOB_READ_WRITE_TOKEN`. The application derives the private snapshot URL from its token by default. Keep `LABFACTORY_LOCAL_DB` and `TURSO_DATABASE_URL` unset so requests select the Blob adapter. [Private Blob connections](https://vercel.com/docs/vercel-blob#connecting-a-store-to-your-projects)
3. Choose a stable HTTPS staging origin for the entire run, restart and restore. Use the shared runner's `credentials --credentials FILE` in a private directory. Run `env --allow-isolated-remote --base-url URL --credentials FILE` there and transfer the generated `LABFACTORY_*` configuration to Preview only. This configures the reviewer, agent verifiers, signing key and allowed origin. Treat the `env` output as secret. [Vercel environment variables](https://vercel.com/docs/environment-variables)
4. Deploy the extracted directory with `vercel deploy --target preview`. Point the chosen staging origin to that Preview. For Vercel-protected staging, supply the staging project's automation bypass secret to the runner through `LAB_TRIAL_PROTECTION_BYPASS`. The application still checks its own reviewer and agent credentials. Run `run --base-url URL --state STATE --credentials FILE --allow-isolated-remote` against the empty store. [Protected automation access](https://vercel.com/docs/deployment-protection/methods-to-bypass-deployment-protection/protection-bypass-automation)
5. For a remote outage claim, `offline` must observe a connection failure or HTTP 502, 503 or 504 at that same origin. After a redeploy or restore, run `verify` with the original URL, credential file and state. An uninterrupted Vercel rollout can establish repeat-read persistence. It cannot establish a service outage or identify which physical worker served a request. Retire the disposable deployment, staging credentials and store after verification.

## Back up and restore

1. Quiesce writers and use an authorized **private, consistent GET** for `labfactory/lab.sqlite3` (`cache=0`, `Accept-Encoding: identity`). Save the bytes, their SHA-256 and the backup time. Run SQLite `PRAGMA integrity_check` and `PRAGMA foreign_key_check` against a read-only copy. [Vercel consistent private reads](https://vercel.com/docs/vercel-blob#caching)
2. Run `SELECT digest FROM tabular_files WHERE local_text IS NULL` on that snapshot. For every returned SHA-256, fetch `labfactory/uploads/<digest>` privately, check its bytes against the digest, and retain it alongside the database. The SQLite file contains the index, reports and receipts. Downloadable originals live under those digest keys.
3. Restore into an empty private store under new staging credentials. Upload each verified original to its exact original pathname with suffixing and overwrites disabled, then publish the snapshot to `labfactory/lab.sqlite3` last. The CLI command shape is `vercel blob put FILE --access private --pathname PATH --content-type application/octet-stream`. Select the isolated destination store explicitly through its matching credentials. Fetch the new snapshot and originals again and verify the hashes. [Blob CLI](https://vercel.com/docs/cli/blob)
4. Point the isolated Preview at the restored store, apply its new token and redeploy. Keep the same staging origin and application identities for the saved runner state. Run `verify` and compare the canonical result fingerprint. The trial exercised this ordering over the local storage HTTP interface. [Tested backup and restore implementation](./backup.py)

The adapter caps the database at **8 MiB** and each original at **128 KiB**. On a definitive snapshot write conflict it repeats the transaction against the latest object, up to four attempts. If the response to a PUT is lost, the caller must check order history to learn whether it committed. Each successful change replaces the current snapshot. Recovering an earlier point in time requires a separately retained backup and its referenced originals.
