# Lab Factory deployment comparison

This experiment runs the backend at commit `62badef1d608d94903da475bfd2b689cb80f9c49` with four deployment arrangements. All artifacts, protocols and readings in the experiment are disposable fixtures. The production deployment, credentials and lab history are outside this comparison.

## What stays fixed

Each deployment starts with empty lab storage. The acceptance client uses the normal reviewer HTTP and agent MCP interfaces. It submits the same candidate analysis bytes, including an intentionally incorrect caffeine submission and the density example. The independent agent client and the hosted API run in separate processes. Replaying the candidate holds the scientific program fixed across architectures. Live model generation and external instrument performance require separate experiments.

The fixture manifest pins the inputs. The acceptance state records the request sequence and canonical outcomes. The comparator recomputes the SHA-256 of both recorded outcomes, checks that the reopened deployment reported the same digests, and compares the pinned workload, exact request sequence, logical request sequence, original result and detailed scientific evidence across deployments. Per-run URLs, access mode, timings and outage observations are reported separately.

## Reproduce

Run commands from `lab-factory/`. Install the locked environment first.

```sh
uv sync --locked
uv run --locked pytest -q
```

To repeat three local deployments using the installed Python environment, use an unused temporary output directory. The services bind to loopback. The replica trial also uses the two ports following the one supplied.

```sh
trial_dir=$(mktemp -d)
.venv/bin/python benchmarks/deployment_trials/replay.py \
  --output "$trial_dir/results" --variants single_host replicas vercel_blob
```

For all four deployments on Apple Silicon macOS, use the official libSQL server release pinned by the repository. The provisioner verifies the archive and executable hashes. The results directory must be new.

```sh
.venv/bin/python benchmarks/deployment_trials/variants/libsql/provision_engine.py "$trial_dir/engine"
.venv/bin/python benchmarks/deployment_trials/replay.py \
  --sqld "$trial_dir/engine/sqld" --output "$trial_dir/all-results"
```

See [the workload contract](WORKLOAD.md) for credential isolation, API/worker checks and the workload phases. Use a separate temporary directory for every deployment and rerun. Follow each variant's instructions for startup, a confirmed process stop or component failure, and recovery. The state files are the inputs to the cross-deployment comparison.

```sh
uv run --locked python benchmarks/deployment_trials/compare.py \
  single_host=/path/to/single-host-state.json \
  replicas=/path/to/replica-state.json \
  libsql=/path/to/libsql-state.json \
  vercel_blob=/path/to/blob-state.json
```

The comparator exits with status 1 when valid receipts disagree or a restart verification is missing. A malformed receipt fails before comparison. A deployment can stay reachable while one node is stopped; that observation is independent of result parity.

## Evidence

See [the deployment results](RESULTS.md) for the environments actually exercised, measured failure behavior, evidence hashes and integration recommendation.
