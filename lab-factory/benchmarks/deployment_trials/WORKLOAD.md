# Deployment acceptance workload

Every target receives the same simulated HPLC caffeine and liquid-density files and the same three submitted programs. This comparison exercises the deployed reviewer HTTP API and the agent's Streamable HTTP MCP endpoint. Programs are deterministic fixtures. Model capability, fresh model generation, real instrument measurements and scientific method validation require separate experiments.

## Inputs and expected outcomes

The frozen source is commit `62badef1d608d94903da475bfd2b689cb80f9c49`. The manifest covers the raw bytes of the example index, both sets of protocol/CSV/control files, and the committed Python acceptance test from which the three artifacts and fresh caffeine control were taken. The protocol and CSV strings inside the workload recover the original UTF-8 bytes, including line endings. The workload and expected artifact SHA-256 hashes are in [the manifest](fixtures/manifest.json). All replay data is in [the workload](fixtures/workload.json).

| Exercise | What a passing server demonstrates |
| --- | --- |
| Caffeine | The wrong program passes its own tests and predicts 3,280 against the 16 mg/L control. It cannot be approved or run. Resubmission needs a fresh control. Revision 2 passes the 14.382 mg/L replacement control. A stale approval of revision 1 fails. Approving revision 2 yields 24 and 45 mg/L for Coffee A and Coffee B. |
| Density | The same routes accept a different protocol, mappings and readings. Revision 1 passes its independent control, receives approval and returns 1.08 and 0.8 g/mL for Liquid A and Liquid B. |
| Concurrent claims | In a third order two separate MCP bearer identities synchronize immediately before claiming the same order. Exactly one wins. The saved owner matches the single claim event. |
| Recovery | The runner verifies stored inputs, submissions, controls, checks, approvals, runs and history before interruption, observes service unavailability, then reads the same records from the replacement process or deployment at the same origin. Repeating each original run must return its saved receipt, with the original ID and timestamp. |

The reviewer writes JSON at the deployment origin. Both disposable workers initialize MCP and must receive exactly the four documented tools. A request without an agent bearer must receive 401. Scientific result receipts include the unit, sample ID, signal, factor, batch standards and control. A fresh run requires an empty disposable database and a new state file.

## Run the harness

Run from `lab-factory/` after `uv sync --locked`. Set `BASE_URL` to the trial origin. Each topology's launcher is responsible for provisioning isolated storage, starting the API, stopping it, and restarting it against that same storage.

```sh
trial_dir=$(mktemp -d)
export BASE_URL=http://127.0.0.1:8765
runner=benchmarks/deployment_trials/acceptance.py
uv run --locked python "$runner" credentials --credentials "$trial_dir/access.json"
uv run --locked python "$runner" env --private --credentials "$trial_dir/access.json" > "$trial_dir/server-env.json"
```

Pass the JSON object's entries into the backend process environment along with the topology's storage configuration. Treat that temporary file as a secret. It contains the synthetic session signing key. The credentials generator writes a new mode-0600 file and refuses to overwrite it. Omitting `--private` selects public reviewer access on loopback. Remote trials always use newly generated disposable credentials and HTTPS. Pass `--allow-isolated-remote` to each command that accepts a remote origin. The existing shared Lab Factory project is excluded. `LAB_TRIAL_PROTECTION_BYPASS` supplies an optional Vercel preview-protection header for that trial origin only. Credentials and headers stay outside the persisted evidence.

```sh
uv run --locked python "$runner" run --credentials "$trial_dir/access.json" --state "$trial_dir/receipt.json"
# Stop the disposable API process or retire its disposable serving deployment here.
uv run --locked python "$runner" offline --credentials "$trial_dir/access.json" --state "$trial_dir/receipt.json"
# Restart the API on the same origin against the same isolated, retained storage.
uv run --locked python "$runner" verify --credentials "$trial_dir/access.json" --state "$trial_dir/receipt.json"
uv run --locked python benchmarks/deployment_trials/fixtures/test_evidence.py
```

Remapping a remote deployment requires a stable *trial-specific* alias. A gateway 502/503/504 or a failed connection counts as an observed service interruption. For an explicitly isolated remote, HTTP 404 together with the exact Vercel header `DEPLOYMENT_NOT_FOUND` or `DEPLOYMENT_DELETED` also counts. A generic 404, authentication error, or retired URL protected by another responder cannot establish unavailability. Individual topology evidence should independently identify the stopped process or retired deployment. `verify` can also be run after a rolling replacement. Its `downtime_observed` field distinguishes a successful readback from a measured outage.

An existing v1 pilot may run `observe` with the same arguments as `verify` *before* stopping the service to add the full pre-interruption evidence. It reconstructs and validates the original request-sequence hash, fetches the records and repeats each idempotent original run. It creates no new orders or revisions.

## Comparison rules

- `workload_sha256` hashes the actual frozen workload file. Its value is `22adbb480970b1b8e0c11b0c4ff1681e6b085bf27a9f6b38ce20d16986b07282`.
- `request_sequence_sha256` hashes 26 actual application request descriptors from the run. Each contains the HTTP method and path or the MCP worker identity, plus SHA-256 of the sent canonical JSON body (empty bytes for GET). Session negotiation with the reviewer, credential headers, the anonymous MCP denial probe, and subsequent receipt inspections are outside this sequence. MCP initialization and four-tool discovery are included. Both racing request descriptors are recorded in fixed worker order. Network arrival order intentionally varies.
- `logical_request_sequence_sha256` first reconstructs and checks the actual sequence against the recorded raw digest, then substitutes deterministic role aliases for generated work-order IDs. It is `2fff2a02b9d5998848e53e14a6ebf155588b6dede6043bc7f14d8ebf516af942`. With a fresh store assigning WO-1 through WO-3 the raw sequence digest is `aab0510e295999dd4baed668d379bbe3ab29ee241c5c86b5cddfeed5f32acae6`.
- `outcome_sha256` retains the original projection of file digests, submission/control summaries, numbered approvals, event types and notes, results, units and claim count. The independently checked value is `fbcbe5d9a473506b746e2de497749faf587d7c32100721994e8502370fce8b67`.
- `outcome_v2_sha256` hashes the complete normalized detail JSON returned through the API for all three orders. It includes rendered source, submitted artifact bodies, all numbered check details and control reports, complete run receipts, all sample IDs/units/raw signals/factors, batch calibrants, approval actors and history. The independent private-server stop/restart run produced `1f9c329696cbd96b9d55e7252617def798d1322d2559d2774c755f969abbc5e8`. Full normalized records accompany this digest in `outcome_v2`.
- V2 substitutes role aliases for validated generated work-order and experiment IDs and the positive original run ID. It removes only nonempty event, submission and run timestamps. Reviewer actors must match the actual named or public reviewer before receiving a common alias. The concurrent race owner and its claim event must agree before the winner receives an alias. Because those names and times can legitimately vary, the separate topology receipts carry the origin, access mode and assigned order IDs. All other returned scientific and decision fields remain in the comparison, including the actual worker identity in the two analysis orders. Equal cross-deployment fingerprints establish equality of that projection.
- Hashes of structured evidence use UTF-8 JSON sorted by key with comma/colon separators, literal Unicode and no NaN. The direct mutation checks exercise the distinction between scientific values, technical identifiers and timestamps.

A matching result across topologies establishes parity on the specified requests and data. The deterministic test cannot estimate data loss rates, general availability, capacity, limits under sustained concurrent writes, or the correctness of unrelated analytical methods.
