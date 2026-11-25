"""Compile the bounded hosted assay specification to a portable Python application."""
import ast
import hashlib
import json
from statistics import mean

from factory.assays.b12.optics import matches_expected, validate_preparation, verification_cases


def _calculation(spec, expression):
    return f"""def analyze(data):
    calibration = data["calibration"]
    readings = data["absorbances"]
    valid = (data["preparation"] is None and len(readings) == {spec["readings"]}
             and all(calibration["low"] <= reading <= calibration["high"] for reading in readings))
    signal = mean(readings)
    slope, intercept = calibration["slope"], calibration["intercept"]
    return {{"status": "ok" if valid else "review", "sample_id": data["sample_id"],
            "calibration_id": calibration["id"], "concentration_mg_l": ({expression}) if valid else None}}
"""


def evaluate(compiled, analysis_input):
    """Run a compiled release's restricted arithmetic on the trusted host."""
    namespace = {"mean": mean}
    exec(_calculation(compiled["spec"], compiled["expression"]), namespace)
    return namespace["analyze"](analysis_input)


def compile_assay(spec, expression, calibration):
    expected = {"sample": "Vial A", "analyte": "vitamin B12", "wavelength_nm": 550,
                "readings": 3, "light_path_mm": 10,
                "standards_mg_l": [row["concentration_mg_l"] for row in calibration["standards"]],
                "output": "concentration in mg/L; withhold outside calibration"}
    if not isinstance(spec, dict) or {k: v for k, v in spec.items() if k != "application_name"} != expected:
        raise ValueError("Use the instrument specifications shown on this page.")
    title = spec.get("application_name")
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 100:
        raise ValueError("Enter an application name of 1 to 100 characters.")
    if not isinstance(expression, str) or len(expression) > 160:
        raise ValueError("Invalid calibration expression.")
    tree = ast.parse(expression.strip(), mode="eval")
    for node in ast.walk(tree):
        if type(node) not in (ast.Expression, ast.BinOp, ast.Sub, ast.Add, ast.Mult, ast.Div, ast.Name, ast.Load):
            raise ValueError("Expected a linear calibration expression.")
        if isinstance(node, ast.Name) and node.id not in ("signal", "slope", "intercept"):
            raise ValueError("Invalid calibration variable.")
    expression = ast.unparse(tree)
    calculation = _calculation(spec, expression)
    namespace = {"mean": mean}
    exec(calculation, namespace)
    checks = []
    # The optical-checks@2 direct cases use several calibrations with unrelated
    # slope and intercept, so an expression that only fits one calibration fails.
    for label, sample, expected in verification_cases(prepared=False):
        try:
            result = namespace["analyze"](sample)
        except ArithmeticError:
            result = {}
        if not matches_expected(result, expected):
            raise ValueError("Generated calculation failed the calibration checks.")
        checks.append(label)
    files = {"analysis.py": "import json, sys\nfrom statistics import mean\n\n" + calculation + "\njson.dump(analyze(json.load(sys.stdin)), sys.stdout)\n",
             "recipe.json": json.dumps({"operation": "measure-absorbance", "wavelength_nm": spec["wavelength_nm"], "replicates": spec["readings"]}, indent=2),
             "views.json": json.dumps({"title": title}, indent=2)}
    revision = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return {"revision": revision, "files": files, "checks": checks, "spec": spec, "expression": expression}


def reference_result(analysis_input):
    """Compute the expected B12 result on the trusted host, independent of the app."""
    cal = analysis_input["calibration"]
    readings = analysis_input["absorbances"]
    preparation = analysis_input["preparation"]
    result = {"sample_id": analysis_input["sample_id"], "calibration_id": cal["id"],
              "status": "review", "concentration_mg_l": None}
    if len(readings) != 3 or not all(cal["low"] <= reading <= cal["high"] for reading in readings):
        return result
    diluted = (mean(readings) - cal["intercept"]) / cal["slope"]
    if preparation is None:
        return {**result, "status": "ok", "concentration_mg_l": diluted}
    factor = validate_preparation(analysis_input["sample_id"], preparation)
    return {**result, "status": "ok", "concentration_mg_l": diluted * factor, "diluted_mg_l": diluted,
            "factor": factor, "parent_id": preparation["parent_id"], "preparation_id": preparation["id"]}


def check_against_reference(output, reference):
    """Refuse an application output that disagrees with the host's own calculation."""
    if not isinstance(output, dict) or not matches_expected(output, reference):
        raise ValueError("The application result disagrees with the instrument's own calculation.")
    return output
