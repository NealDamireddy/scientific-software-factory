# Single-host persistent service

The pinned Lab Factory ASGI backend passed the shared caffeine and density workload on an arm64 Mac running macOS 26.2. It served real HTTP and MCP requests on IPv4 loopback with a named reviewer and disposable bearer credentials. The canonical outcome matched after an ASGI `SIGKILL`, after stopping and restarting the entire service, and after restoring a live SQLite backup into a new directory. The test ended with the listener closed and both private runtimes removed. [Recorded evidence](evidence.json)

| Check | Observation |
| --- | --- |
| Caffeine | The wrong candidate passed its own examples and failed the independent control. Approval and execution of that revision were denied. Submission 2 passed a fresh control and produced 24 and 45 mg/L. |
| Density | Submission 1 passed its control and produced 1.08 and 0.8 g/mL. |
| Concurrent claim | Two authenticated agents raced for one order. One won and one claim event persisted. |
| Recovery | All three recovery paths replayed the original two receipts. The database retained 3 orders, 3 submissions, 3 control reports, 4 uploaded files, 11 events and 2 run receipts. All inspected snapshots had the same logical digest and passed SQLite integrity and foreign-key checks. |
| Worker interruption | A real MCP worker was killed between its committed claim and its first submission. A fresh process with the same worker identity resumed the claim, submitted the pinned density artifact once and reached human review. |

The canonical workload SHA-256 is `22adbb480970b1b8e0c11b0c4ff1681e6b085bf27a9f6b38ce20d16986b07282`. The request-sequence SHA-256 is `aab0510e295999dd4baed668d379bbe3ab29ee241c5c86b5cddfeed5f32acae6`. The canonical output SHA-256 is `fbcbe5d9a473506b746e2de497749faf587d7c32100721994e8502370fce8b67`. The evidence also includes the runner, candidate source, complete artifact, control, protocol and CSV hashes. The database fingerprint includes timestamps and identifies snapshots from the same run.

## Measurements

| Operation | Elapsed |
| --- | ---: |
| Extract pinned source, validate config and start to HTTP readiness | 559 ms |
| Complete shared workload, including reviewer login and both MCP clients | 275 ms |
| Kill ASGI child and wait for replacement HTTP readiness | 693 ms |
| Start detached supervisor and server on existing volume | 410 ms |
| Take online backup / restore into a new SQLite file | 44 ms / 60 ms |
| Start service on restored volume / run common verification | 462 ms / 205 ms |
| Authenticated `GET /api/orders`, median of 12 sequential requests | 0.769 ms |
| Worker exit observed to verified replacement submission | 289 ms |

These wall times describe the recorded run with an existing Python environment and a 135,168-byte database. CLI timings include subprocess startup. The read sample reused one HTTP connection. The backup ran while the service was available and the trial workload was idle. [Timings and individual read samples](evidence.json)

## Reproduce the comparison

Run from the repository root on a POSIX host with Git, the benchmark files and Git object `62badef1d608d94903da475bfd2b689cb80f9c49`. The trial used the supplied `lab-factory/.venv/bin/python` with Python 3.14.9 and SQLite 3.53.1. On a fresh checkout of the pinned revision with the benchmark files present, `uv sync --locked --project lab-factory --python 3.14.9` prepares this environment. The process requires permission to open a loopback TCP socket and a private Unix control socket.

```sh
py=lab-factory/.venv/bin/python
trial=lab-factory/benchmarks/deployment_trials
variant="$trial/variants/single_host"
"$py" -B "$variant/trial.py" --output "$variant/repeat-evidence.json"
```

Choose a new evidence filename for each run. The driver archives the committed backend, uses the independent runner's `credentials`, `env`, `run`, `offline` and `verify` commands, then exercises worker recovery on a fourth synthetic order after common verification. Each server runs the committed `api.index:app` with Uvicorn in its extracted package. The server gets explicitly supplied trial auth settings, a local database path and the packaged source path. It uses the project's locked Python dependencies. The worker probe uses the committed `tabular_worker.process` with a fixed candidate supplied through its author callback.

## Operate the service and restore a snapshot

To keep the service and volume across shell exits, use a private directory on a persistent disk. The example uses port 8765. Set `port` to an available local port before starting. Run the following shell commands from the repository root, in the same shell.

```sh
umask 077
py=lab-factory/.venv/bin/python
trial=lab-factory/benchmarks/deployment_trials
variant="$trial/variants/single_host"
mkdir -p "$HOME/.local/state"
trial_state=$(mktemp -d "$HOME/.local/state/labfactory-single-host.XXXXXX")
port=8765
base="http://127.0.0.1:$port"
credentials="$trial_state/credentials.json"
envfile="$trial_state/server-env.json"
state="$trial_state/acceptance-state.json"
live="$trial_state/live"
restored="$trial_state/restored"

"$py" "$trial/acceptance.py" credentials --credentials "$credentials"
"$py" "$trial/acceptance.py" env --private --base-url "$base" --credentials "$credentials" > "$envfile"
"$py" "$variant/service.py" start --runtime "$live" --port "$port" --env-file "$envfile"
"$py" "$variant/service.py" status --runtime "$live"
"$py" "$trial/acceptance.py" run --base-url "$base" --state "$state" --credentials "$credentials"
```

`status` reports both process IDs, the generation and HTTP readiness from `GET /api/session`. A successful authenticated `GET /api/orders` or common verification checks the database path as well. The supervisor holds the loopback socket and respawns its Uvicorn child after a crash. Its Unix control socket and log live inside the private runtime. The `stop` operation shuts down both processes and leaves the package, credentials configuration and database on disk.

```sh
"$py" "$variant/service.py" crash --runtime "$live"
"$py" "$trial/acceptance.py" verify --base-url "$base" --state "$state" --credentials "$credentials"
"$py" "$variant/service.py" stop --runtime "$live"
"$py" "$trial/acceptance.py" offline --base-url "$base" --state "$state"
"$py" "$variant/service.py" start --runtime "$live"
"$py" "$trial/acceptance.py" verify --base-url "$base" --state "$state" --credentials "$credentials"
```

The SQLite database contains the uploaded bytes as well as the application records. The backup tool uses SQLite's online backup API, verifies the copied database and publishes it under a new filename. Preserve the private server configuration and trial credentials separately for the named identities. To restore, stop the existing listener and start a fresh service on the original port so the runner can verify the saved state.

```sh
"$py" "$variant/volume.py" backup "$live/volume/lab.sqlite3" "$trial_state/backup.sqlite3"
"$py" "$variant/service.py" stop --runtime "$live"
mkdir -p "$restored/volume"
"$py" "$variant/volume.py" restore "$trial_state/backup.sqlite3" "$restored/volume/lab.sqlite3"
"$py" "$variant/service.py" start --runtime "$restored" --port "$port" --env-file "$envfile"
"$py" "$trial/acceptance.py" verify --base-url "$base" --state "$state" --credentials "$credentials"
"$py" "$variant/service.py" stop --runtime "$restored"
```

## Deployment limits

The measurements cover this Mac, one local disk and loopback HTTP. The runner explicitly supplies the reviewer's Secure cookie on loopback. Internet routing, TLS, a rented VM, sustained load and multi-host failover remain unverified. The common run used two simultaneous claimants. It killed the ASGI process after completed transactions.

The supervisor runs independently of the invoking shell. Host reboot and abrupt death of the supervisor itself were outside the trial. Startup after a reboot requires starting the supervisor again. A backup on the same disk protects against loss of the active database file only as far as that disk remains readable. The test restored into a new directory on that disk. Worker recovery used the same named identity and a fresh process started by the probe. Live model generation and automatic worker scheduling remain unmeasured.
