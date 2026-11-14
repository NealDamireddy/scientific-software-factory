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


def metadata_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            fail(f"metadata.{key}", "duplicate key")
        result[key] = value
    return result


def reject_constant(value):
    fail("metadata", f"nonfinite JSON constant {value} is forbidden")


def validate_numbers(value, path):
    if isinstance(value, float) and not math.isfinite(value):
        fail(path, "must be finite")
    if isinstance(value, dict):
        for key, item in value.items():
            validate_numbers(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            validate_numbers(item, f"{path}[{index}]")


def read_metadata():
    if len(sys.argv) != 2:
        fail("sys.argv[1]", "exactly one acquisition metadata JSON argument is required")
    try:
        metadata = json.loads(
            sys.argv[1], object_pairs_hook=metadata_object,
            parse_constant=reject_constant
        )
    except json.JSONDecodeError as exc:
        fail("metadata", f"invalid JSON: {exc.msg}")
    if not isinstance(metadata, dict):
        fail("metadata", "must be a JSON object")
    validate_numbers(metadata, "metadata")
    if metadata.get("instrument") != "epr-01":
        fail("metadata.instrument", "must be 'epr-01'")
    if metadata.get("synthetic") is not True:
        fail("metadata.synthetic", "must be the JSON boolean true")
    for key in ("sample_id", "acquisition_mode"):
        value = metadata.get(key)
        if not isinstance(value, str) or not value.strip():
            fail(f"metadata.{key}", "must be a nonempty string")
    frequency = metadata.get("frequency_GHz")
    if isinstance(frequency, bool) or not isinstance(frequency, (int, float)):
        fail("metadata.frequency_GHz", "must be a positive finite JSON number")
    if finite_number(frequency, "metadata.frequency_GHz") <= 0:
        fail("metadata.frequency_GHz", "must be positive")
    if not isinstance(metadata.get("units"), dict):
        fail("metadata.units", "must be an object with field and signal units")
    return metadata


def calculate(metadata):
    reader = csv.DictReader(sys.stdin, strict=True)
    headers = reader.fieldnames
    if headers is None:
        fail("CSV.headers", "missing header row")
    if len(headers) != 2 or len(set(headers)) != 2:
        fail("CSV.headers", "require exactly one field column and signal_au")
    if set(headers) == {"field_mT", "signal_au"}:
        field_column, field_unit, scale = "field_mT", "mT", 1.0
    elif set(headers) == {"field_G", "signal_au"}:
        field_column, field_unit, scale = "field_G", "G", 0.1
    else:
        fail("CSV.headers", "expected field_mT or field_G, together with signal_au")
    units = metadata["units"]
    if units.get("field") != field_unit:
        fail("metadata.units.field", f"must be '{field_unit}' for {field_column}")
    if units.get("signal") != "a.u.":
        fail("metadata.units.signal", "must be 'a.u.' for signal_au")

    fields = []
    signals = []
    previous = None
    for row in reader:
        location = f"CSV line {reader.line_num}"
        if None in row or any(value is None for value in row.values()):
            fail(location, "row must contain exactly two values")
        field = finite_number(row[field_column], f"{location}.{field_column}")
        signal = finite_number(row["signal_au"], f"{location}.signal_au")
        if previous is not None and field <= previous:
            fail(f"{location}.{field_column}", "values must be distinct and strictly increasing")
        previous = field
        fields.append(field * scale)
        signals.append(signal)
    if len(fields) < 3:
        fail(field_column, "at least three distinct increasing field values are required")

    peak_index = max(range(len(signals)), key=signals.__getitem__)
    trough_index = min(range(len(signals)), key=signals.__getitem__)
    peak = fields[peak_index]
    trough = fields[trough_index]
    result = {
        "center_mT": peak / 2.0 + trough / 2.0,
        "linewidth_mT": abs(peak - trough),
        "peak_mT": peak,
        "trough_mT": trough,
    }
    for key, value in result.items():
        if not math.isfinite(value):
            fail(key, "calculated value exceeds finite numeric range")
    return result


def main():
    try:
        result = calculate(read_metadata())
        output = json.dumps(result, allow_nan=False, separators=(",", ":"))
    except (ValueError, csv.Error, UnicodeError, OSError, RecursionError) as exc:
        message = str(exc)
        if isinstance(exc, csv.Error):
            message = f"CSV: {message}"
        elif isinstance(exc, (UnicodeError, OSError)):
            message = f"stdin: {message}"
        elif isinstance(exc, RecursionError):
            message = "metadata: JSON nesting exceeds supported depth"
        print(json.dumps({"error": message}, separators=(",", ":")))
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
