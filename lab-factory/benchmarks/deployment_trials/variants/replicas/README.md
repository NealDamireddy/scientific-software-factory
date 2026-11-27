# Two API replicas and a separate MCP worker

Four successive authenticated reads of the same order returned HTTP 200 from replica B after replica A stopped. The response bytes matched those served by both replicas before the interruption. After every serving process stopped, two fresh API processes and a fresh proxy reopened the same SQLite database. A replacement worker finished a claim that its predecessor had made before it was killed.

## What ran

The supervisor extracts Git commit `62badef1d608d94903da475bfd2b689cb80f9c49` into a private temporary directory. Two independent Uvicorn processes run `labfactory.hosted:application`, the same ASGI callable as the pinned Vercel entrypoint. They share the same local SQLite file, WAL mode and disposable named-reviewer and MCP identities. A third process accepts HTTP on loopback, alternates requests between the APIs, and records the responding upstream in `X-Lab-Replica`. It tries the second upstream if it cannot connect to the first. An ambiguous write outcome yields an error to the caller.

The unchanged common runner submits the caffeine and density candidates and races two authenticated MCP clients. A separate OS worker then exercises process death and recovery on one additional density order. The operator gives this worker only its own token and the fixed candidate projection. The worker reads author context, claims or resumes the named order, and submits through the proxy using the MCP SDK. It receives no reviewer credential, control certificate or database handle. Every application decision and numerical calculation runs in the pinned backend.

## Measured results

| Scenario | Observed result |
| --- | --- |
| Caffeine | The incorrect candidate passed its authored tests and failed the held-back control. Its approval and execution were denied. After a fresh control, submission 2 passed and returned 24 and 45 mg/L. |
| Density | Submission 1 passed and returned 1.08 and 0.8 g/mL. Both released programs, source uploads, approvals and receipts survived restart. |
| Concurrent claims | Two MCP identities raced for one order. One claim won and one claim event persisted. |
| Loss of API A | A's port refused connections. B and the proxy kept their PIDs. Four proxied data reads from B took 2.28–4.05 ms each. |
| Full service restart | The runner observed an unavailable connection. Both replacement APIs served the same order bytes. The database device and inode matched, and SQLite reported `quick_check=ok` before and after restart. The serving processes took 1.61 s to restore. |
| Worker interruption | The controller sent SIGKILL after the worker confirmed its claim and before submission. A fresh process resumed the same order under the same identity, passed its control and exited in 1.28 s from launch. A third invocation detected the existing submission. The order had one claim and one numbered submission. |

The common workload took 0.43 s, and its post-restart verification took 0.71 s. Two trials from separately initialized databases produced identical common acceptance JSON. These are single-host loopback measurements, including client overhead. Replication here provides continuity during an API process loss. The proxy, disk and host are each a single point of failure. SQLite WAL requires processes on the same host with the database and its WAL and shared-memory files on a compatible local filesystem. Writers serialize. Cross-host failover, sustained load, automatic worker reassignment and a hosted deployment remain unverified. No independently available disposable SQL service was identified for this trial.

| SHA-256 | Value |
| --- | --- |
| Common workload | `22adbb480970b1b8e0c11b0c4ff1681e6b085bf27a9f6b38ce20d16986b07282` |
| Common request sequence | `aab0510e295999dd4baed668d379bbe3ab29ee241c5c86b5cddfeed5f32acae6` |
| Canonical outcome before and after restart | `fbcbe5d9a473506b746e2de497749faf587d7c32100721994e8502370fce8b67` |

The unmodified common runner state is in [acceptance.json](acceptance.json). The runner hash, eight verified source-file hashes, candidate hashes, scenario results, PIDs, timings and cleanup checks are in [evidence.json](evidence.json).

## Reproduce the full trial

From the repository root, use the installed Lab Factory virtual environment, the common runner and its fixtures. The output directory can be new or empty. The trial creates and removes a separate private runtime, including the credentials and database. Three consecutive loopback ports must be available.

```sh
py=lab-factory/.venv/bin/python
bench=lab-factory/benchmarks/deployment_trials
variant="$bench/variants/replicas"
output_dir=$(mktemp -d)
"$py" -B "$variant/trial.py" --port 18460 --output "$output_dir"
cat "$output_dir/evidence.json"
```

## Start, fail over, stop and restore manually

The following commands use the same entrypoint and fixed acceptance workload. `verify` reads the saved orders and replays their receipts while A is stopped. The automated trial above adds the instrumented worker interruption and checks every listening port.

```sh
(
  set -eu
  py=lab-factory/.venv/bin/python
  bench=lab-factory/benchmarks/deployment_trials
  variant="$bench/variants/replicas"
  runtime_dir=$(mktemp -d)
  url=http://127.0.0.1:18460
  svc() { "$py" -B "$variant/services.py" --runtime "$runtime_dir" --port 18460 "$@"; }
  common() {
    "$py" -B "$bench/acceptance.py" "$1" --base-url "$url" \
      --credentials "$runtime_dir/credentials.json" --state "$runtime_dir/state.json"
  }
  cleanup() {
    svc stop all && rm -r "$runtime_dir"
  }
  trap cleanup EXIT

  svc start all
  common run
  svc status
  svc stop a
  common verify
  svc start a
  svc stop all
  common offline
  svc start all
  common verify
)
```

The first start creates random mode-0600 credentials through the common runner and applies its private `env` configuration to both APIs. For this loopback HTTP trial, the runner explicitly forwards the reviewer's Secure session cookie on the local reviewer requests. `svc stop all` closes the supervisor and children while preserving the runtime for restoration. The example removes the disposable runtime when the subshell exits.
