# EVOLVE | A software factory for one research lab

A PI asks, “How much vitamin B12 is in this vial?” EVOLVE uses the lab’s inventory and protocol to build an app for the experiment. The first measurement falls above the app’s calibration range. The PI approves a diluted follow-up. While the researcher prepares it, EVOLVE adds the ability to trace a prepared sample back to its original vial. The audience sees the new requirement, the code change, a test that v1 fails, and the verified v2 release.

[Try the interactive design walkthrough](lab-factory-plan.html#experiment)

## 1. Who builds what

| Owner | Work it owns | Artifact to inspect |
|---|---|---|
| Our team, using 8090 | Spend development credits on EVOLVE’s requirements, architecture, **Build Work Orders for developing EVOLVE**, and engineering review. Codex orchestrates implementation in this repository. | A development order linked to a code revision and acceptance evidence. [Existing 8090 project](8090.md) |
| EVOLVE, running in the lab | Receive PI requests, resolve the project context, create **scientific software tasks inside EVOLVE**, record approvals, dispatch a coding worker, verify candidates and release project apps. | An EVOLVE task ID linked to a request, source revision and verification report. |
| Generated B12 app | Guide acquisition using a declarative recipe, analyze the measurements, collect the project’s inputs and display the result. | The recipe, analysis module and app controls produced for that project and revision. |

**Runtime requirement.** EVOLVE has no runtime dependency on 8090. From a clean EVOLVE session with 8090 credentials absent and traffic to 8090 blocked, submit a PI request, build v1, approve a follow-up, generate and verify v2, and run the released app. The local coding worker can use its own model connection. The acceptance evidence includes the two EVOLVE task receipts and their source revisions.

### What remains under factory control

EVOLVE owns the instrument registry and simulator, recipe executor, approvals, frozen calibration records, independent validator and tests, release decisions and evidence store. Each app manifest pins its lab and project IDs, instrument-profile revision, approved protocol revision and verification-profile revision. For the walkthrough, both app versions use `northfield`, `b12-assay`, `osms-sim@1`, `b12-optical@1` and `optical-checks@1`. Each run also records its actual settings and calibration reference. These five references demonstrate shared lab context within one project.

The coding worker receives a filtered task, input and output schemas, the permitted operations, public examples and, for a revision, the verified parent source. It returns candidate `analysis.py`, `recipe.json` and `views.json` files. The trusted host stages only those paths. Run the worker with an isolated workspace and no tools or credentials for lab storage. Execute candidate analysis in a separate offline sandbox with only the measurement inputs and read-only calibration values it needs. The factory alone writes verification results, frozen calibrations and releases.

Keep blind preparations and any seed that could reconstruct their labels in a private simulator/scoring service. Acquisition returns counts and opaque sample IDs. The evaluation agent and coding worker receive neither the labels nor access to their store. The scorer joins a label only after EVOLVE saves a valid estimate. Test both agents’ access to the private labels. Submit a worker response targeting a validator file, then try overwriting a calibration from the candidate sandbox. Each attempt must fail, and the trusted file digests must match their originals.

### How a PI request becomes new code

1. **Submit.** The presenter opens EVOLVE on the laptop. The UI sends the PI’s brief to a local EVOLVE service. The service snapshots the versioned project context, compares the requested capability with the released app and returns a task ID. A sample rename or a supported factor is an input change and reuses the released source.
2. **Generate.** A new capability queues a local coding job. Extend the existing `factory.agent.generate` path to invoke a real `codex exec` worker with the B12 contract and persist the returned files. For v2, give it v1 and the approved capability change. The UI follows this same task through generation, verification and release. [Current generator](../factory/agent.py) · [Current pipeline](../factory/pipeline.py)
3. **Verify and release.** The host validates the recipe, hashes the candidate file paths and content digests in a stable order to identify the source revision, shows the diff from the parent, and runs the independent checks. Release only a passing candidate. Return the task ID, worker invocation record, parent and candidate revisions, test results and result artifacts to the requesting UI. A failed job shows its actual failure and leaves the last verified app available.
4. **Prove fresh generation.** Submit from the EVOLVE UI with an empty build store and exercise the full path without a manual CLI handoff. Inspect new source on disk, verify its digest against the returned revision, and rerun the trusted suite on that source. A second submission requesting prepared-sample support must produce a changed revision. Label this path **Fresh generation**. A public browser can separately open a **Previous completed run** with its original run ID and archived Python.

**Starting evidence.** The repository already has local generation from structured orders and browser replay of saved Python. Its EPR fixtures show a verified 0.800 mT linewidth and a temperature-fit revision that adds a fit-quality check. The optical worker bridge and releases described here are planned. The HTML uses fixed example readings and inspectable example code. [Linewidth report](../public/evidence/linewidth/20261114T041110Z-b188b519/report.json) · [Temperature revision](../public/evidence/curie/20261114T042106Z-5a33014b/report.json)

## 2. The experiment and the software change

| Experiment progress | Software progress |
|---|---|
| **Collect the first measurements.** Read a dark reference, solvent blank, known B12 standards and three replicates of the mystery vial. The researcher can use the trusted simulator’s approved acquisition protocol while v1 builds. | **Build v1 for direct samples.** Generate its recipe, analysis and views. Fit the calibration from the known vials. The factory verifies and freezes the fit, checks detector quality and compares each mystery reading with the observed calibration range before reporting a concentration. |
| **Review the finding.** All three readings exceed the strongest standard in the staged example. The evaluation agent cites the readings and protocol, explains the uncertainty and recommends one volume of sample plus one volume of matching solvent. Keep the 550 nm channel, 10 mm cuvette and detector settings fixed. | **Identify the missing capability.** v1 handles a vial measured directly. A prepared follow-up needs a preparation record, a link to its parent vial and a correction using actual volumes. The agent’s recommendation is a proposal. Invalid blanks or saturated readings produce acquisition-quality findings instead. |
| **PI approves.** Save the approved preparation, the reference to the initial run and the PI decision. The researcher can immediately start preparing the sample. | **Open an EVOLVE task.** Approval authorizes this follow-up and development of the missing capability. A duplicate approval resolves to the same task. The factory applies its independent release checks to the candidate. |
| **Record the preparation.** Give the diluted vial its own ID, link the original and record sample and final volumes with units. A mismatch with the approved preparation goes back for review. | **Build v2 in parallel.** Generate preparation inputs, validate measured volumes, calculate final volume divided by sample volume, and report both concentrations with their vial, preparation and calibration references. A later protocol-permitted factor uses these inputs on the same v2 revision. |
| **Rerun once the sample and v2 are ready.** Take three fresh readings. If any is still out of range, retain them, show the finding to the PI and withhold the original-vial estimate. An in-range rerun yields a saved estimate followed by label reveal. | **Preserve both releases.** A build failure can be retried against the saved task and preparation. Replay the initial flag with v1 and the linked follow-up with v2 using the same frozen calibration. |

**Instrument contract.** Label the acquisition source **Simulated instrument**. The published OSMS describes a 450–750 nm range at about 15 nm resolution. EVOLVE implements the 550 nm channel. The resolver, recipe compiler and acquisition executor use the same pinned capability profile. Exercise 550 nm successfully. Reject 361 nm and an unimplemented in-band value such as 600 nm at construction and again on direct submission of a modified recipe. A rejected command produces zero readings. Store the executed operation, profile revision, wavelength, path length, detector settings, units, sample ID, timestamps and simulation provenance for each acquisition. [OSMS paper](https://doi.org/10.1016/j.ohx.2020.e00108)

**Rehearsal numbers.** A fixed example calibration maps 24 mg/L to 0.1536 absorbance. The original vial averages 0.2048 and is above range. After twofold dilution, an in-range mean of 0.1024 gives 16 mg/L in the diluted vial and 32 mg/L in its parent. The live app must use its own fitted calibration and saved readings.

### The new requirement test

“Given an in-range reading from a prepared vial, return the diluted concentration and the original concentration with their sample lineage.” Run the same factory-owned fixtures against v1 and the v2 candidate. v1 must decline the unsupported prepared input. v2 must pass the new contract and the direct-sample regression. A numerical answer with a missing parent or preparation reference fails.

| Independent fixture | Expected result |
|---|---|
| Direct vial, 12 mg/L, no preparation | Both versions report 12 mg/L for that vial. |
| 1 mL reference sample brought to 2 mL total, diluted reading 9 mg/L | v2 reports factor 2 and 18 mg/L for this reference parent, linked to the child and preparation. |
| 1 mL sample brought to 4 mL total, different parent, diluted reading 7 mg/L | The same v2 source reports factor 4 and 28 mg/L for that parent. |
| Missing parent, invalid units, nonfinite or nonpositive volumes, or final volume no greater than sample volume | Reject the invalid preparation and identify the field. |
| Rerun still outside calibration | Preserve readings and return for scientific review with the concentration withheld. |

### Reproducibility evidence package

Use a small versioned research-reproducibility profile. Each check records its status and an artifact reference. Show missing or outstanding items in the report.

| Named check | Evidence |
|---|---|
| Raw measurements retained | Original dark, blank, standards and sample counts, plus the follow-up counts with timestamps and units. |
| Acquisition settings recorded | Instrument-profile revision, settings, protocol revision and simulator provenance for each run. |
| Calibration unchanged | One frozen fit, residuals, bounds and matching digest before and after the follow-up. |
| Preparation documented | Parent and child vial IDs, actual volumes and units, factor, originating run and PI approval. |
| Software and dependencies identified | Request and task IDs, generator record, v1 and v2 source digests and diff, interpreter and dependency lock. |
| Numerical tests passed | Versioned trusted suite with expected and observed values, the v1 failure on the new requirement and the v2 pass. |
| Outstanding scientific review shown | Whether the rerun was in range, the PI’s interpretation and open questions about simulation assumptions or transfer to physical instruments. |

## 3. Development work in 8090

These proposed Build Work Orders deliver the factory. The lab’s requests and software tasks are created within EVOLVE.

| Sequence | Acceptance milestone |
|---|---|
| 1. Deliver real generation | A PI submits the B12 request to EVOLVE. The local coding worker returns new app files, the UI returns the source revision and results, and independent reference checks pass at 550 nm with 8090 disconnected. |
| 2. Demonstrate the capability change | From a valid above-range run, show the agent’s evidence and PI approval. The new prepared-sample contract fails on v1. While preparation proceeds, a real worker modifies v1 and returns the candidate diff. |
| 3. Verify independently and release | Exercise the multiple factors, regressions, failure paths, access boundaries and recipe restrictions above. Release verified v2, perform the rerun and reproduce both results from the evidence package. |
| 4. Rehearse delivery | Show the simulator identity, actual generation status and package in a fresh session. Rehearse both a timely generation and explicitly opening a previous completed run during a delay. |
| 5. Extend evaluation | Run the preregistered seeded panel and published six-row comparison as supporting evidence after the core demonstration works. |

## 4. Five minutes on stage

| Time | Experiment track | Software track the judges see |
|---|---|---|
| 0:00–0:30 | Show the vial and the PI’s question. | Open EVOLVE and submit the request. Credit 8090 for developing the factory in one sentence. Keep its blueprint available for Q&A. |
| 0:30–1:25 | Acquire the standards and original vial on the simulated detector. | Follow the fresh task to the local worker, open the generated v1 source and show one numerical test and the revision. |
| 1:25–2:00 | Point to the vial’s reading above the highest standard and the proposed dilution. | Open the linked finding, then show the new requirement to track prepared samples. The PI approves the follow-up and its task. |
| 2:00–3:35 | The researcher prepares and labels the second vial. | Keep this track visible while showing v1 failing the added test, the generated source diff and the candidate’s independent results for 2× and 4×. |
| 3:35–4:25 | Record actual volumes and remeasure when ready. | Show v2 release, open the linked preparation in the app and calculate the original concentration. |
| 4:25–5:00 | Reveal the label after the estimate is saved. | Trace the answer to its reading, frozen calibration, preparation and source. Close on the reusable feature and the outstanding scientific review. |

## 5. Science reference and supporting evaluation

**Core assay.** Use aqueous cyanocobalamin, a 10 mm path and the simulator’s 550 nm channel. Keep chemistry and detector settings fixed. Take three readings per sample. For standards at 3, 5, 10, 15, 20 and 24 mg/L, compute absorbance per reading as `−log10((sample − dark)/(blank − dark))`. Fit mean absorbance against known concentration by ordinary least squares with intercept, retain residuals and freeze the calibration. A noiseless in-range fixture must recover the hidden concentration to rounding precision. Test 50% dark-corrected transmission against absorbance 0.30103.

Model the simulator independently using the Beer–Lambert response. Document the 550 nm cyanocobalamin coefficient of 8,700 M⁻¹ cm⁻¹ reported under Ahmad et al.’s assay conditions, chemistry, finite-bandwidth approximation, dark offset and seeded noise as assumptions. The OSMS is a proposed addition to the Warncke-inspired demo lab. [Independent assay](https://pmc.ncbi.nlm.nih.gov/articles/PMC4179674/) · [Open instrument designs](https://doi.org/10.17605/OSF.IO/RBFSE) · [Lab instrumentation](https://faculty.college.emory.edu/sites/warncke/instrumentation.html)

**Optional blind panel.** Fix noise settings and seeds before evaluating 8, 12, 18 and 22 mg/L. The simulator engineering target is a mean absolute error of at most 1 mg/L. Report the observed score and replicate spread separately.

**Optional external comparison.** Laganovska et al. published six commercial Shimadzu UVMini1240 mean absorbances at 550 nm. Use the “Com” column in Table 1 at its published precision. The dilute aqueous comparison uses mg/L for the estimate and retains the paper’s ppm labels. [Paper and Table 1](https://pmc.ncbi.nlm.nih.gov/articles/PMC9041175/)

| Prepared concentration (ppm) | 3 | 5 | 10 | 15 | 20 | 24 |
|---|---:|---:|---:|---:|---:|---:|
| Published mean absorbance | 0.033 | 0.062 | 0.089 | 0.119 | 0.173 | 0.200 |

Keep these data out of generation prompts, tuning and calibration. For benchmark scoring, pass the published absorbances directly through the frozen estimator, commit predictions before joining labels, and display all six signed errors, mean absolute error and any extrapolation. Link each finding to its row. The comparison measures transfer across instruments and conditions. Six published means cannot establish the cause of a discrepancy.
