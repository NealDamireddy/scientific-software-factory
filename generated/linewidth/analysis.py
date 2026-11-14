import csv
import json
import math
import sys


def fail(field, message):
    raise ValueError(f"{field}: {message}")


def finite_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        fail(field, "must be a finite number")
    try:
        number = float(value)
    except (ValueError, OverflowError):
        fail(field, "must be a finite number")
    if not math.isfinite(number):
        fail(field, "must be a finite number")
    return number


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            fail(f"metadata.{key}", "duplicate JSON key")
        result[key] = value
    return result


def reject_constant(value):
    fail("metadata", f"nonfinite JSON constant {value} is forbidden")


def read_metadata():
    if len(sys.argv) != 2:
        fail("metadata", "provide exactly one acquisition metadata JSON argument")
    try:
        metadata = json.loads(
            sys.argv[1], object_pairs_hook=unique_object,
            parse_constant=reject_constant
        )
    except json.JSONDecodeError as exc:
        fail("metadata", f"invalid JSON: {exc.msg}")
    if not isinstance(metadata, dict):
        fail("metadata", "must be a JSON object")
    for key in ("sample_id", "acquisition_mode"):
        value = metadata.get(key)
        if not isinstance(value, str) or not value.strip():
            fail(f"metadata.{key}", "must be a nonempty string")
    if metadata.get("instrument") != "epr-01":
        fail("metadata.instrument", "must be epr-01")
    if metadata.get("synthetic") is not True:
        fail("metadata.synthetic", "must be the JSON boolean true")
    frequency = finite_number(metadata.get("frequency_GHz"), "metadata.frequency_GHz")
    if frequency <= 0:
        fail("metadata.frequency_GHz", "must be positive")
    units = metadata.get("units")
    if not isinstance(units, dict):
        fail("metadata.units", "must be an object with field and signal units")
    return units


def calculate(units):
    reader = csv.DictReader(sys.stdin, strict=True)
    headers = reader.fieldnames
    if headers is None:
        fail("CSV.headers", "missing header row")
    if len(headers) != len(set(headers)):
        fail("CSV.headers", "duplicate column names")
    choices = [name for name in ("field_mT", "field_G") if name in headers]
    if len(choices) != 1:
        fail("CSV.headers", "require exactly one of field_mT or field_G")
    field_name = choices[0]
    if len(headers) != 2 or set(headers) != {field_name, "signal_au"}:
        fail("CSV.headers", f"expected exactly {field_name} and signal_au")
    expected_unit = "mT" if field_name == "field_mT" else "G"
    if units.get("field") != expected_unit:
        fail("metadata.units.field", f"must be {expected_unit} for {field_name}")
    if units.get("signal") != "a.u.":
        fail("metadata.units.signal", "must be a.u. for signal_au")

    fields = []
    signals = []
    for row_number, row in enumerate(reader, start=2):
        if None in row:
            fail(f"CSV.row[{row_number}]", "too many cells")
        for column in headers:
            if row.get(column) is None or not row[column].strip():
                fail(f"CSV.row[{row_number}].{column}", "missing value")
        field = finite_number(row[field_name], f"CSV.row[{row_number}].{field_name}")
        signal = finite_number(row["signal_au"], f"CSV.row[{row_number}].signal_au")
        if fields and field <= fields[-1]:
            fail(f"CSV.row[{row_number}].{field_name}", "must be strictly increasing")
        fields.append(field)
        signals.append(signal)
    if len(fields) < 3:
        fail(field_name, "require at least three distinct increasing field values")

    peak_index = max(range(len(signals)), key=signals.__getitem__)
    trough_index = min(range(len(signals)), key=signals.__getitem__)
    scale = 1.0 if expected_unit == "mT" else 0.1
    peak = fields[peak_index] * scale
    trough = fields[trough_index] * scale
    center = peak / 2.0 + trough / 2.0
    width = abs(peak - trough)
    result = {
        "center_mT": center,
        "linewidth_mT": width,
        "peak_mT": peak,
        "trough_mT": trough,
    }
    for name, value in result.items():
        if not math.isfinite(value):
            fail(name, "calculated result exceeds finite numeric range")
    return result


def main():
    try:
        units = read_metadata()
        result = calculate(units)
        output = json.dumps(result, allow_nan=False, separators=(",", ":"))
    except (ValueError, csv.Error, OverflowError, RecursionError) as exc:
        prefix = "CSV: " if isinstance(exc, csv.Error) else ""
        if isinstance(exc, RecursionError):
            message = "metadata: JSON nesting exceeds supported depth"
        else:
            message = prefix + str(exc)
        print(message, file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
