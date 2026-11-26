from pathlib import Path
import subprocess
import sys

from labfactory.context import experiment_from_dict, lab_from_dict
from labfactory.store import Store
from labfactory.workorders import WorkOrders


CLIENT = Path(__file__).resolve().parents[1] / "examples" / "submit_example.py"


def run_client(db, order_id):
    return subprocess.run(
        [sys.executable, str(CLIENT), str(db), order_id],
        capture_output=True, text=True, timeout=20,
    )


def test_missing_order_reports_concise_error(tmp_path):
    result = run_client(tmp_path / "lf.db", "WO-17")
    assert result.returncode == 1
    assert result.stderr.splitlines()[-1] == "error: WO-17 is not open"
    assert "Traceback" not in result.stderr


def test_failed_checks_print_the_reason(tmp_path, uvvis_lab_dict, b12_experiment_dict):
    db = tmp_path / "lf.db"
    uvvis_lab_dict["instruments"][0]["parameters"][0]["maximum"] = 500
    with Store(db) as store:
        store.put_lab(lab_from_dict(uvvis_lab_dict))
        exp = experiment_from_dict(b12_experiment_dict)
        store.put_experiment(exp)
        order = WorkOrders(store).create(exp.id, "run_plan", "Measure absorbance")

    result = run_client(db, order.id)
    assert result.returncode == 1
    assert "550 nm is outside [400, 500] nm" in result.stderr
    assert "Traceback" not in result.stderr
