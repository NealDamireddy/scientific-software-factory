"""Score an existing verified B12 release after committing its label-free predictions."""
import argparse
import hashlib
import json
from pathlib import Path
from statistics import mean, stdev
import tempfile

from . import b12_build
from .context import ROOT, read_json
from .followup import _checked_execution
from .optics import acquire, assess, calibration_digest, validate_recipe
from .replay_bundle import replay_package


DATASET = ROOT / "data" / "b12-evaluation.json"
SEED_POLICY = "One preregistered seed per panel vial in the versioned evaluation dataset."


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_new(path, record):
    encoded = json.dumps(record, sort_keys=True, allow_nan=False, indent=2) + "\n"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(encoded)


def _estimate(folder, sample_id, absorbances, calibration):
    bounds = {key: calibration[key] for key in ("id", "slope", "intercept", "low", "high")}
    in_range = all(bounds["low"] <= value <= bounds["high"] for value in absorbances)
    payload = {"sample_id": sample_id, "absorbances": absorbances, "calibration": bounds, "preparation": None}
    output, _ = _checked_execution(folder, payload, {"in_range": in_range})
    return output


def _inverse(value, calibration):
    return (value - calibration["intercept"]) / calibration["slope"]


def _panel_measurements(panel, recipe):
    """The simulator alone consumes blind creation labels and seeds during acquisition."""
    for sample in panel["samples"]:
        raw = acquire(recipe, sample["prepared_mg_l"], sample["seed"],
                      sample_id=sample["id"], noise_counts=panel["noise_sd_counts"])
        yield sample["id"], raw


def _predictions(folder, dataset, calibration, recipe):
    panel = []
    for sample_id, raw in _panel_measurements(dataset["panel"], recipe):
        absorbances = assess(raw, calibration)["absorbances"]
        result = _estimate(folder, sample_id, absorbances, calibration)
        replicates = [_inverse(value, calibration) for value in absorbances]
        panel.append({
            "id": sample_id, "raw": raw, "absorbances": absorbances, "replicate_sd_mg_l": stdev(replicates),
            "released_status": result["status"], "predicted_mg_l": result["concentration_mg_l"],
        })

    published = []
    for sample in dataset["published"]["samples"]:
        sample_id, value = sample["id"], sample["mean_absorbance"]
        # Adapt a single published mean to the triplicate-input app. Never infer
        # replicate observations or a spread for these already aggregated inputs.
        result = _estimate(folder, sample_id, [value] * 3, calibration)
        extrapolated = not calibration["low"] <= value <= calibration["high"]
        predicted = _inverse(value, calibration) if extrapolated else result["concentration_mg_l"]
        published.append({
            "id": sample_id, "mean_absorbance": value, "released_status": result["status"],
            "released_mg_l": result["concentration_mg_l"], "predicted_mg_l": predicted,
            "extrapolated": extrapolated,
            "prediction_method": "benchmark-only linear extrapolation" if extrapolated else "released estimator",
        })
    return {"panel": panel, "published": published}


def _join_labels(predictions, samples, label_key):
    labels = {sample["id"]: sample[label_key] for sample in samples}
    if len(labels) != len(samples) or {row["id"] for row in predictions} != labels.keys() or len(predictions) != len(labels):
        raise ValueError("Predictions must match exactly one preparation label per ID")
    rows = []
    for prediction in predictions:
        row = dict(prediction)
        label = labels[row["id"]]
        row[label_key] = label
        value = row["predicted_mg_l"]
        row["signed_error_mg_l"] = None if value is None else value - label
        rows.append(row)
    # A withheld release output counts as a panel target failure. Never drop it from the denominator.
    errors = [row["signed_error_mg_l"] for row in rows]
    mae = mean(abs(error) for error in errors) if errors and all(e is not None for e in errors) else None
    return rows, mae


def evaluate(package, out, *, dataset_path=DATASET):
    package_bytes = package.read_bytes()
    dataset_bytes = dataset_path.read_bytes()
    bundle = json.loads(package_bytes)
    dataset = json.loads(dataset_bytes)
    input_hashes = {"package_sha256": hashlib.sha256(package_bytes).hexdigest(),
                    "dataset_sha256": hashlib.sha256(dataset_bytes).hexdigest()}
    replay_package(bundle)
    child = bundle["followup"]
    calibration = bundle["initial"]["calibration"]
    cal_id = calibration_digest(calibration)
    metadata = {"source_revision": child["revision"], "calibration_id": cal_id, "task_id": child["id"]}
    panel, published = dataset["panel"], dataset["published"]
    if len(panel["samples"]) != 4 or len(published["samples"]) != 6:
        raise ValueError("Evaluation requires four panel samples and six published mean readings")
    # The exclusive directory reserves this evaluation. An interrupted run keeps
    # its completed stages; running again requires a new output location.
    out.mkdir(parents=True, exist_ok=False)
    registration = out / "registration.json"
    predictions_path = out / "predictions.json"
    _write_new(registration, {
        **metadata, "profile": dataset["profile"], **input_hashes, "seed_policy": SEED_POLICY,
        "noise_sd_counts": panel["noise_sd_counts"], "target_mae_mg_l": panel["target_mae_mg_l"],
        "panel_ids": [sample["id"] for sample in panel["samples"]],
        "published_ids": [sample["id"] for sample in published["samples"]],
    })
    with tempfile.TemporaryDirectory() as work:
        folder = Path(work)
        files = bundle["sources"][child["id"]]["files"]
        for name in b12_build.FILES:
            (folder / name).write_text(files[name])
        revision = b12_build.revision(folder)
        if revision != child["revision"] or cal_id != calibration["id"]:
            raise ValueError("Source revision or calibration digest mismatch before scoring")
        recipe = validate_recipe(read_json(folder / "recipe.json"))
        predictions = _predictions(folder, dataset, calibration, recipe)
        if b12_build.revision(folder) != revision or calibration_digest(calibration) != cal_id:
            raise ValueError("Release or calibration changed during evaluation")
        registration_digest = _digest(registration)
        _write_new(predictions_path, {**metadata, "registration_sha256": registration_digest, **predictions})
        predictions_digest = _digest(predictions_path)

    # Reopen the committed predictions before the scoring step obtains any labels.
    saved_bytes = predictions_path.read_bytes()
    if hashlib.sha256(saved_bytes).hexdigest() != predictions_digest:
        raise ValueError("Predictions changed after commitment")
    committed = json.loads(saved_bytes)
    panel_rows, panel_mae = _join_labels(committed["panel"], panel["samples"], "prepared_mg_l")
    published_rows, published_mae = _join_labels(committed["published"], published["samples"], "prepared_ppm")
    limit = panel["target_mae_mg_l"]
    report = {
        **metadata, "profile": dataset["profile"],
        "hashes": {"registration_sha256": registration_digest, "predictions_sha256": predictions_digest,
                   **input_hashes},
        "panel": {"rows": panel_rows, "mae_mg_l": panel_mae, "target_mae_mg_l": limit,
                  "target_met": panel_mae is not None and panel_mae <= limit,
                  "seed_policy": SEED_POLICY, "noise_sd_counts": panel["noise_sd_counts"]},
        "published": {**{k: v for k, v in published.items() if k != "samples"},
                      "rows": published_rows, "mae_mg_l": published_mae,
                      "mean_input_adapter": "One published mean per vial. Repeated identically for the released triplicate input contract. No raw replicates or spread inferred."},
        "scientific_review": "Comparison assumes dilute aqueous ppm corresponds numerically to mg/L. Six published means cannot establish the cause of transfer error.",
    }
    _write_new(out / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--out", type=Path, required=True, help="New output directory")
    args = parser.parse_args()
    try:
        report = evaluate(args.package, args.out)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"Benchmark failed: {error}\n")
    print(json.dumps({"release": report["source_revision"], "panel_mae_mg_l": report["panel"]["mae_mg_l"],
                      "published_mae_mg_l": report["published"]["mae_mg_l"], "report": str(args.out / "report.json")}))


if __name__ == "__main__":
    main()
