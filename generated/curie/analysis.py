import csv
import json
import math
import statistics
import sys


class InputError(ValueError):
    pass


def fail(field, message):
    raise InputError(f'{field}: {message}')


def reject_constant(value):
    fail('metadata', f'nonfinite JSON constant {value} is forbidden')


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            fail(f'metadata.{key}', 'duplicate key')
        result[key] = value
    return result


def read_metadata():
    if len(sys.argv) != 2:
        fail('metadata', 'provide exactly one acquisition metadata JSON argument')
    try:
        metadata = json.loads(sys.argv[1], parse_constant=reject_constant,
                              object_pairs_hook=unique_object)
    except (json.JSONDecodeError, RecursionError) as exc:
        fail('metadata', f'invalid JSON ({exc})')
    if not isinstance(metadata, dict):
        fail('metadata', 'must be a JSON object')

    def check_finite(value, path):
        if isinstance(value, float) and not math.isfinite(value):
            fail(path, 'must be finite')
        if isinstance(value, dict):
            for key, item in value.items():
                check_finite(item, f'{path}.{key}')
        elif isinstance(value, list):
            for index, item in enumerate(value):
                check_finite(item, f'{path}[{index}]')

    check_finite(metadata, 'metadata')
    for key in ('sample_id', 'acquisition_mode'):
        value = metadata.get(key)
        if not isinstance(value, str) or not value.strip():
            fail(f'metadata.{key}', 'must be a nonempty string')
    if metadata.get('instrument') != 'epr-01':
        fail('metadata.instrument', 'must equal epr-01')
    if metadata.get('synthetic') is not True:
        fail('metadata.synthetic', 'must be true for simulator provenance')
    frequency = metadata.get('frequency_GHz')
    if isinstance(frequency, bool) or not isinstance(frequency, (int, float)):
        fail('metadata.frequency_GHz', 'must be a positive finite number')
    try:
        valid_frequency = math.isfinite(frequency) and frequency > 0
    except OverflowError:
        valid_frequency = False
    if not valid_frequency:
        fail('metadata.frequency_GHz', 'must be a positive finite number')
    expected_units = {'temperature': 'K', 'intensity': 'a.u.'}
    units = metadata.get('units')
    if not isinstance(units, dict):
        fail('metadata.units', 'must contain temperature=K and intensity=a.u.')
    for key, expected in expected_units.items():
        if units.get(key) != expected:
            fail(f'metadata.units.{key}', f'must equal {expected}')
    if units != expected_units:
        fail('metadata.units', 'only temperature and intensity units are supported')
    return metadata


def read_series():
    reader = csv.DictReader(sys.stdin, strict=True)
    expected = ['temperature_K', 'intensity_au']
    try:
        headers = reader.fieldnames
        if headers is None or len(headers) != 2 or set(headers) != set(expected):
            fail('CSV.headers', 'must contain exactly temperature_K and intensity_au')
        temperatures = []
        intensities = []
        for row_number, row in enumerate(reader, start=1):
            if None in row or any(row.get(key) is None for key in expected):
                fail(f'CSV.row[{row_number}]', 'must contain exactly two values')
            values = {}
            for key in expected:
                raw = row[key]
                try:
                    value = float(raw)
                except (ValueError, OverflowError):
                    fail(f'{key}[{row_number}]', 'must be a finite number')
                if not math.isfinite(value):
                    fail(f'{key}[{row_number}]', 'must be finite')
                values[key] = value
            temperature = values['temperature_K']
            if temperature <= 0:
                fail(f'temperature_K[{row_number}]', 'must be positive Kelvin')
            if temperatures and temperature <= temperatures[-1]:
                fail(f'temperature_K[{row_number}]', 'must be strictly increasing')
            temperatures.append(temperature)
            intensities.append(values['intensity_au'])
    except csv.Error as exc:
        fail(f'CSV.line[{reader.line_num}]', str(exc))
    if len(temperatures) < 3:
        fail('temperature_K', 'require at least three distinct increasing values')
    return temperatures, intensities


def fit_curie(temperatures, intensities):
    inverse = []
    for index, temperature in enumerate(temperatures, start=1):
        value = 1.0 / temperature
        if not math.isfinite(value):
            fail(f'temperature_K[{index}]', 'inverse temperature exceeds numeric range')
        inverse.append(value)
    try:
        fit = statistics.linear_regression(inverse, intensities)
    except (statistics.StatisticsError, OverflowError, ValueError, ZeroDivisionError) as exc:
        fail('fit_curie', f'cannot resolve regression in floating-point arithmetic ({exc})')
    coefficient = fit.slope
    background = fit.intercept
    if not math.isfinite(coefficient):
        fail('coefficient_au_K', 'regression result exceeds numeric range')
    if not math.isfinite(background):
        fail('background_au', 'regression result exceeds numeric range')
    predicted = []
    residuals = []
    for index, (x, measured) in enumerate(zip(inverse, intensities), start=1):
        prediction = coefficient * x + background
        residual = measured - prediction
        if not math.isfinite(prediction):
            fail(f'predicted_au[{index}]', 'result exceeds numeric range')
        if not math.isfinite(residual):
            fail(f'residual_au[{index}]', 'result exceeds numeric range')
        predicted.append(prediction)
        residuals.append(residual)
    scale = max(abs(value) for value in residuals)
    rmse = (scale * math.sqrt(math.fsum((value / scale) ** 2
                                       for value in residuals) / len(residuals))
            if scale else 0.0)
    if not math.isfinite(rmse):
        fail('rmse_au', 'result exceeds numeric range')
    return {'coefficient_au_K': coefficient,
            'background_au': background,
            'rmse_au': rmse,
            'predicted_au': predicted,
            'residual_au': residuals}


def main():
    try:
        read_metadata()
        temperatures, intensities = read_series()
        result = fit_curie(temperatures, intensities)
        output = json.dumps(result, allow_nan=False)
    except (InputError, UnicodeError) as exc:
        print(json.dumps({'error': str(exc)}, allow_nan=False))
        return 1
    print(output)
    return 0


if __name__ == '__main__':
    sys.exit(main())
