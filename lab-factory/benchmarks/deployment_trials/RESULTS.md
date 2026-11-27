# Deployment results

## Decision

Use a single supervised API process with a persistent database for a one-machine lab pilot when the lab can operate that machine and keep independent backups. It was the simplest arrangement in this trial to recover after a process crash and restore from a database backup. For a shared internet service, keep the working hosted API and test moving its metadata to a transactional service before the current 8 MiB snapshot cap becomes a constraint. The official libSQL server experiment exercises that code path. The separately tested content-addressed uploads can stay in private object storage.

Add API replicas when continued service during an API process failure is a requirement. Two processes on one host continued serving after one went down. They share the host, proxy, and database volume. More API processes also do not supply an analysis author while the lab Mac is offline. That requires a separately available worker.

This is an architecture comparison with fixed candidate programs. It assesses where jobs, submissions and result receipts survive and which failure a user can observe. The work does not establish accuracy on real samples or across an instrument’s full operating range.

## What was exercised

| Deployment | Runtime and persistence | Failure that was exercised |
| --- | --- | --- |
| Supervised single host | An independent supervisor, an ASGI process and a local SQLite file holding records and upload bytes | Child termination, automatic process replacement, full stop and restart, and backup restored to a new directory |
| API with networked SQL | The production Turso/HTTP adapter over TLS to the official libSQL server, with separate database and API OS processes on the same Mac | API replacement, database unavailability and recovery, concurrent clients at different API processes |
| Two API replicas | Two ASGI processes behind a round-robin proxy on one Mac and one SQLite WAL database | One node removed, continued work at the same origin, full outage, restart and worker recovery |
| Blob adapter on loopback | The Vercel entry point with HTTP blob transport redirected to a local store implementing conditional object writes | API replacement, backup of SQLite metadata plus separate immutable originals, and restoration to an empty store |
| Vercel Preview | Vercel Python Functions and a dedicated private Vercel Blob store; a private named reviewer and separate MCP tokens | See the [hosted Preview evidence](variants/vercel_preview/README.md) |

Local trials use disposable data, genuine OS processes and loopback networking. The libSQL binary is official upstream software. A managed Turso account, independent physical machines and provider-wide failure recovery require different experiments. The hosted Preview supplements the local Blob adapter trial. No existing production deployment or production credentials were used.

## How to read the evidence

The shared workload contains a failed caffeine analysis, a corrected numbered revision, density through the same API, review decisions, persisted results and a two-agent race for a separate job. The incorrect program passes its own checks and fails the independent control. Its release is refused. The accepted caffeine analysis returns **24 and 45 mg/L**, and density returns **1.08 and 0.8 g/mL**. A retry returns the existing receipt.

Each topology uses authentic HTTP reviewer calls and bearer-authenticated MCP calls. A local client submits prewritten, pinned candidate code to make this workload reproducible. Supplemental worker crash tests use a fixed generator with the author workflow. A passing trial does not show that a model would generate identical source on another attempt.

The [workload contract](WORKLOAD.md) defines the canonicalization. The [initial parity audit](audits/input-parity.md) identified fields omitted by the original result digest. The strengthened observation retains that digest and adds a separate digest for detailed scientific and approval evidence. Timings, physical origins, database-assigned IDs and selected reviewer mode are reported separately as documented in the workload contract.

## Operating tradeoffs

- A single local SQLite backup can contain uploaded originals when they live inline with local rows. The Blob configuration needs the metadata snapshot plus every original file referenced by digest. Restoring only the snapshot loses access to those originals.
- Network SQL lets API instances share one authoritative transaction record. When SQL was unavailable, a session endpoint could still answer while requests that needed work orders failed. A readiness check for lab work must read lab data.
- A proxy and second API process improve availability during node loss but add processes to operate; a shared-volume or host outage can take down both. The replica study does not establish multi-host database failover.
- In the Blob configuration a state-changing transaction conditionally replaces the complete metadata snapshot, and concurrent writers may retry. Original files are independent objects. The 8 MiB limit applies to the snapshot; individual source uploads have their own 128 KiB limit.
- The operational data are per-run elapsed times, process and request counts, database/backup sizes and recovery observations. Machine load, local networking and the remote provider differ. These measurements do not establish a general throughput ranking, a production uptime target or a monthly bill.
