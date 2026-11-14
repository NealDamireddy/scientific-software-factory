# B12 presenter runbook

## Before going on stage

1. Use the reviewed `codex/evolve-b12-factory` branch and keep a note of `git rev-parse HEAD`.
2. Install uv and authenticate your local Codex CLI (`codex login`). On Linux,
   install bubblewrap (Debian/Ubuntu: `sudo apt-get install bubblewrap`) and use a
   host that allows its namespaces. Do not disable sandboxing to make it run.
3. From the repository root, run:

   ```sh
   uv sync --frozen
   uv run --frozen python -m factory.demo --check
   uv run --frozen python -m unittest discover -s tests -v
   ```

   Require all live readiness checks and tests to pass on the presenter laptop.
   The readiness check executes harmless sandbox probes and replays the saved
   analyses. It checks CLI login, **not** the model connection or a new build.
4. Start `uv run --frozen python -m factory.demo` and open the URL printed by it.
   Leave the terminal running. A second server cannot use the same store/port.
5. In a clean browser session, rehearse the full request-to-reveal sequence below.
   Record elapsed time and the **new** direct/follow-up task IDs and revisions.
   Do not cite the original archive's timing or test counts as a fresh result.
6. Rehearse opening the previous completed run during generation and returning
   with **View fresh task**. Confirm both the original archived ID and the
   currently running task ID remain unchanged.

To keep a rehearsal separate without destroying retained evidence:

```sh
uv run --frozen python -m factory.demo --store runs/b12-rehearsal-02
```

A new store still shows the bundled read-only archive; it does not preload live
builds or pretend their source was generated in that store.

## Five minutes on stage

| Time | Action | Evidence to show |
| --- | --- | --- |
| 0:00–0:30 | Submit the default PI brief. | Fresh task ID; simulated instrument label. Credit 8090 for developing the factory, not running the lab task. |
| 0:30–1:25 | Follow the worker and independent verification. | Worker receipt, generated analysis/recipe/views, v1 revision and one numerical check. |
| 1:25–2:00 | Explain the above-range finding and approve the follow-up. | Three readings, frozen upper standard, protocol and new prepared-sample requirement. No original-vial estimate yet. |
| 2:00–3:35 | Record 1 mL sample and 2 mL final volume while v2 builds. | Persisted preparation; v1 failing the 2×/4× cases; source diff and v2 checks. |
| 3:35–4:25 | Measure the prepared vial once both prerequisites are ready. | Three new readings, unchanged calibration digest, diluted and original concentrations with lineage. |
| 4:25–5:00 | Reveal the label, replay both acquisitions, download evidence. | Estimate saved before reveal; reproduced results; source revisions and outstanding simulation/transfer review. |

Live concentrations differ with the random simulated vial/noise. Do not expect
exactly the archived 32.00683 mg/L. An unexpected out-of-range or failed candidate
is a real finding: retain it and use the labeled archive, not a forced estimate.

## Delayed build or unavailable worker

- During a live build, select **B12 Sample Concentration** under **Previous
  completed runs**. The committed fallback has child ID
  `7b92c13361464fdea79aa5cffcab0f7d` and direct ID
  `a921d6aadbcd41beb3b442a65182988f`. Its source is the original source.
- Say explicitly: “This is a previous completed run, not this live build.”
- Inspect the checks, source diff, readings and downloadable package. **Replay
  both acquisitions** re-executes the archived Python in the same offline sandbox;
  it never changes the committed package or creates a fresh scientific task.
- Use **View fresh task** to return to the live job. A worker can take up to
  180 seconds per build; a prior rehearsal is not a latency guarantee.
- If Codex cannot start at all, stop the server with Ctrl+C and run:

  ```sh
  uv run --frozen python -m factory.demo --archive-only
  ```

  This mode is read-only for the previous run and rejects fresh-generation
  requests. It is not evidence of fresh generation. Without a working sandbox,
  inspection/download still work, but replay does not; the old recorded replay
  result is historical evidence only.

## Recovery without losing evidence

| Symptom | Recovery |
| --- | --- |
| Missing Python dependency | Run `uv sync --frozen`; use `uv run --frozen`, not an unrelated system interpreter. |
| Codex/login fails | Check `codex --version` and `codex login` on the laptop. Do not put credentials in source or paste them into chat. Use the archive if the model service is unavailable. |
| Sandbox missing or blocked | On macOS check `command -v sandbox-exec`; on Linux check `command -v bwrap`. Use a compatible host. Never bypass isolation. |
| Port occupied | Stop the old presenter with Ctrl+C, or choose `--port 8766` and use the newly printed URL. |
| Store already locked | Keep the existing service, or use a deliberately separate `--store`. Do not delete its `.lock` or live task folders. |
| Generation/verification fails | Inspect the actual error and use the previous run. An approved child can be retried with its saved preparation; a failed initial request can be submitted again as a new task. |
| Presenter restarted during a build | Interrupted tasks are marked failed. Do not relabel them successful. Retry the approved child or submit a new initial request. |
| Package/source/calibration fails validation | Do not promote or replay altered evidence as verified. Restore the reviewed files from version control after checking local changes. |

## Verification of this delivery-hardening change

The implementation workspace ran **50/50 Python tests** under Linux bubblewrap,
including private-file/network denial and exact archived replay. Browser smoke
checks covered an empty store, original archived IDs, replay, source diff,
archive-only generation rejection and mobile-width layout. Readiness correctly
blocks fresh startup because this workspace has no authenticated Codex worker.

On November 14, 2026, the presenter laptop passed all seven live readiness checks
and 52 tests under macOS Seatbelt. A clean Chrome session completed two real
Codex builds, approval, preparation during generation, measurement, label
reveal, replay and evidence export in 38.075 seconds. The saved estimate was
35.03519 mg/L and the revealed preparation was 35 mg/L. Opening the archive
during generation preserved the active task. The downloaded fresh package
reproduced both results from disk. Task IDs and revisions are in the
[WO-4 review log](../.sw-factory/WO-4/review-log.md).

For a fallback tab alongside a running live presenter, start
`uv run --frozen python -m factory.demo --archive-only --port 8768`.
The tab reads the bundled run without opening the live task store.
