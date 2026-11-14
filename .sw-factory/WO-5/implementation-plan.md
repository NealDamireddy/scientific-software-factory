# Score the released estimator on independent B12 data

Use the verified archived release and frozen calibration. Preregister seeded optical inputs at 8, 12, 18 and 22 mg/L and a 1 mg/L MAE target before evaluation. Write and hash label-free predictions before scoring. Compare the six published Table 1 Com absorbances, explicitly retaining assay review flags and benchmark-only extrapolations. Verify independently through CLI replay, digest checks and source comparison.

Reuse the existing isolated Python runner and Codex CLI transport. Preserve the static EPR workbench. Verify with unit, integration and local presenter checks before release.
