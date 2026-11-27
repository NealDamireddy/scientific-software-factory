# Combining repeat spectra with a generated app

Open `app.html` locally and select `scan-A.csv` and `scan-B.csv` together. The app plots intensity against corrected energy and exports the result. The checked-in HTML is the exact worker download. Its SHA-256, the synthetic saved project, the real question, and the simulated researcher answer are in `trial.json`.

The workflow is inspired by ESRF ID28, where scientists determine the elastic line, center selected scans and combine them. The S1 instrument, CSVs, monitor pooling rule and exact-grid requirement are specific to this synthetic trial. [ESRF ID28 analysis manual](https://www.esrf.fr/UsersAndScience/Experiments/DynExtrCond/ID28/UserManual/DataAnalysis)

The worker received the pinned project goal, the assigned instrument and the export guide. It asked about the energy reference, matching tolerance or interpolation, and pooled versus equal-weight intensity. After the answer it authored the UI, numerical logic, plot and export. The two CSVs and their expected results were withheld during both turns. No spectroscopy renderer or calculation lives in the backend.

| Corrected energy (eV) | Detector sum | Monitor sum | Exported intensity (rounded) |
| ---: | ---: | ---: | ---: |
| −1 | 55 | 40 | 1.375 |
| 0 | 50 | 15 | 3.333333333333 |
| 1 | 30 | 20 | 1.5 |

The second scan is shifted by 0.5 eV and has shuffled rows and unequal monitor exposure. The check reads the exported CSV, changes an unseen detector count and verifies the resulting bin. It also exercises a mismatched grid, zero monitor, negative detector count, inconsistent marker, duplicate energy and nonfinite input. It runs offline in Chrome.

From the repository root with the JavaScript dependencies installed and Chrome available, run:

```sh
node lab-factory/benchmarks/repeated_spectra/check.cjs
```

To generate a fresh app from the same saved project and simulated answer, use a signed-in Codex CLI. From `lab-factory`, run:

```sh
uv run --locked python benchmarks/repeated_spectra/run_worker.py /tmp/new-spectroscopy-trial
```

The output directory must be new. The replay creates a local database, registers the instrument and experiment, submits only the project ID and objective, runs both worker turns over authenticated MCP, and saves the transcript and download. A fresh generation may have different questions and controls. The browser replay targets the checked-in artifact.
