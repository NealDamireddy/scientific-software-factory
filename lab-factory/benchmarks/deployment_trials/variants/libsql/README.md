# Stateless API with remote SQL

The benchmark runs the committed Lab Factory API and its Turso storage adapter against an independent, official libSQL `sqld` 0.24.32 process. All processes run on one Apple Silicon Mac. The only custom network component is a loopback TLS proxy that forwards the Hrana request and response bodies and counts requests. The database executes the SQL, maintains transactions and owns the data files. The upstream binary and archive SHA-256 values are in [evidence.json](evidence.json). [Official sqld release](https://github.com/tursodatabase/libsql/releases/tag/libsql-server-v0.24.32) · [Hrana v3 specification](https://github.com/tursodatabase/libsql/blob/libsql-server-v0.24.32/docs/HRANA_3_SPEC.md)

A dedicated, authorized hosted preview was unavailable. Managed Turso, Vercel cold starts, WAN latency, provider failover and multi-host recovery remain unverified.

## Measurements

All three fresh private deployments produced the same canonical outcome before interruption, after replacing the API, after restarting SQL, and after restoring SQL from a backup. Caffeine returned **24 and 45 mg/L** on approved submission 2. Density returned **1.08 and 0.8 g/mL** on submission 1. The wrong caffeine candidate passed its authored tests and failed the independent control. The runner confirmed that the failed revision could neither be approved nor executed. The original uploads, approval digests and replayed receipts survived each recovery.

| Observation | Median | Range across three deployments |
| --- | ---: | ---: |
| Shared acceptance workload, including named login and client startup | 924 ms | 762–978 ms |
| API kill to first successful authenticated order read, including the offline check | 565 ms | 539–1,347 ms |
| Replacement API spawn to first successful authenticated order read | 392 ms | 384–1,107 ms |
| SQL kill to first successful authenticated order read, including outage probes | 433 ms | 365–470 ms |
| Clean SQL stop, cold backup, restore and first successful authenticated order read | 397 ms | 355–1,261 ms |
| Analysis worker kill to reviewer-confirmed passing submission | 554 ms | 505–1,492 ms |

Timing uses the controller's monotonic clock and includes local process and client overhead. The first successful order read is the recovery endpoint in the table. The full post-recovery acceptance checks are timed separately in the JSON. The three samples characterize this host and fixture.

- The common workload generated **453 SQL HTTPS requests** per deployment, comprising 420 Hrana cursor calls and 33 pipeline calls, all successful. Counts exclude API startup, recovery probes and supplemental jobs. The SQL outage returned HTTP 503 on an authenticated order read in 3.68–5.91 ms. The session endpoint still returned HTTP 200.
- The cold backup covered **nine files, 369,816–373,677 bytes** across samples. The SQL image contained the uploaded originals. Each restore produced the same SHA-256 manifest as its source image before the restored database was opened. All three common outcomes survived.
- Two clients in the common race produced one persisted claim. The supplemental race sent the two authenticated claims through different live API processes. Both subsequently reported the same owner and exactly one claim event. The separate analysis-worker interruption left zero submissions and one committed claim. With the same identity, the replacement found the in-progress job and produced exactly one passing submission.

| SHA-256 | Value in all three samples |
| --- | --- |
| Shared workload | `22adbb480970b1b8e0c11b0c4ff1681e6b085bf27a9f6b38ce20d16986b07282` |
| Request sequence | `aab0510e295999dd4baed668d379bbe3ab29ee241c5c86b5cddfeed5f32acae6` |
| Canonical outcome | `fbcbe5d9a473506b746e2de497749faf587d7c32100721994e8502370fce8b67` |

The eight source-file digests in the fixture manifest match their original Git blobs. The full candidate artifacts, candidate source strings, fresh control and runner have separate digests in [evidence.json](evidence.json).

## Deployment and recovery boundaries

- Uvicorn serves the unmodified `api.index:app` from a Git archive of `62badef1d608d94903da475bfd2b689cb80f9c49`. The package includes the committed example JSON used by `POST /api/example`. Each API process starts in its own empty working directory.
- The API reads `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN`. Its unmodified `turso-serverless` 0.1.0 adapter validates a trial-only TLS certificate using `SSL_CERT_FILE`. The proxy and the SQL daemon both authenticate the disposable bearer. The same SQL token reaches the daemon over a loopback connection. The API uses a fresh HTTP client and a SQL transaction per storage operation. Originals, receipts, control reports and review history reside in SQL. This configuration needs one durable SQL directory and a reachable SQL service.
- The HTTP reviewer and MCP clients each exercise their own authentication paths. The shared runner generates random identities and a session-signing key. For local HTTP it explicitly forwards the secure reviewer cookie after login. API processes share the verifier and signing configuration. The synthetic analysis worker uses its own bearer and the fixed density candidate.
- The common runner submits the fixed caffeine and density fixtures, verifies each output and races two claimants. The controller kills the initial API with SIGKILL between completed requests. The runner checks the outage and verifies the original state on a replacement API at the same address. A second API reads the same released order through a separate port.
- The SQL crash test kills the database after acknowledged operations while both API processes stay alive. Recovery reopens the same data directory. A separate cold restore shuts SQL down cleanly, copies the complete image into a backup, verifies the files by SHA-256 and size, and starts a new daemon from a separate restored directory. Both checks use the unchanged runner's `verify` command.
- Two supplemental orders follow the final common verification. One races authenticated claimants through different API processes. The other interrupts an analysis worker after its committed claim and resumes with a new process under the same identity. Supplemental orders are excluded from the common fingerprint and workload request counts.

The benchmark uses explicit process replacement. Automatic scheduling, worker takeover by a different identity, ambiguous in-flight commits, TLS rotation, sustained load, live backup and off-host restore remain unmeasured. A single SQL daemon and its disk are shared dependencies for every API process.

## Reproduce on Apple Silicon

Run from the repository root with the project's installed virtual environment. The provisioner checks the pinned release archive and executable. Pass `--archive /path/to/libsql-server-aarch64-apple-darwin.tar.xz` to reuse a local copy. The shell block places the binary in a fresh temporary directory and preserves the output JSON at the path printed at the end.

```sh
(
  set -eu
  py=lab-factory/.venv/bin/python
  variant=lab-factory/benchmarks/deployment_trials/variants/libsql
  runtime_dir=$(mktemp -d)
  trap 'rm -rf "$runtime_dir"' EXIT
  result_dir=$(mktemp -d)
  "$py" -B "$variant/provision_engine.py" "$runtime_dir"
  "$py" -B "$variant/trial.py" --sqld "$runtime_dir/sqld" \
    --samples 3 --output "$result_dir/evidence.json"
  echo "$result_dir/evidence.json"
)
```

Each sample extracts a fresh backend, selects four ephemeral loopback ports and uses the shared runner's `credentials`, `env --private`, `run`, `offline` and `verify` commands. All phases use the same API origin, disposable credentials and, where required, private state file. The harness removes its data, backup copies, credentials and TLS keys after reaping the processes. The published JSON contains the runner state, input and source hashes, outcome, SQL counters, per-scenario results, timings and cleanup observations.
