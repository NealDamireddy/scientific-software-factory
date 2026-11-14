"""Analytic reference inputs. Constants are held outside the generated applications."""
import csv
import io
import math

from .context import ROOT


def specimen(project, variant=0):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    if project == "linewidth":
        center, sigma = [(339.0, 0.4), (345.5, 0.7), (331.2, 0.23)][variant]
        writer.writerow(["field_mT", "signal_au"])
        for i in range(-240, 241):
            t = i / 40
            writer.writerow([f"{center + sigma * t:.8f}", f"{-t * math.exp(-0.5*t*t):.12g}"])
        expected = {"center_mT": center, "linewidth_mT": 2*sigma}
    elif project == "curie":
        coefficient, background = [(120.0, 0.25), (125.0, -0.12), (705.0, 1.2)][variant]
        writer.writerow(["temperature_K", "intensity_au"])
        for temperature in (50, 100, 150, 200, 250, 300):
            writer.writerow([temperature, f"{coefficient / temperature + background:.14g}"])
        expected = {"coefficient_au_K": coefficient, "background_au": background, "rmse_au": 0.0}
    else:
        raise ValueError("Unknown reference suite")
    return stream.getvalue().encode(), expected


if __name__ == "__main__":
    for project, dataset in (("linewidth","gaussian"), ("curie","temperature")):
        (ROOT / "fixtures" / dataset / "input.csv").write_bytes(specimen(project)[0])
