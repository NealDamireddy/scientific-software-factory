import csv
import json
import math
import statistics
import sys


class InputError(ValueError):
    pass


def finite_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise InputError(f'{field}: expected a finite number')
    try:
        result = float(value)
    except (ValueError, OverflowError):
        raise InputError(f'{field}: expected a finite number') from None
    if not math.isfinite(result):
        raise InputError(f'{field}: expected a finite number')
    return result


def reject_constant(value):
    raise InputError(f'metadata: nonfinite JSON constant {value} is invalid')


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f'metadata.{key}: duplicate JSON key')
        result[key] = value
    return result


def read_metadata():
    if len(sys.argv) != 2:
        raise InputError('metadata: supply exactly one acquisition JSON argument in sys.argv[1]')
    try:
        metadata = json.loads(sys.argv[1], parse_constant=reject_constant,
                              object_pairs_hook=unique_object)
    except json.JSONDecodeError as exc:
        raise InputError(f'metadata: invalid JSON at character {exc.pos}') from None
    if not isinstance(metadata, dict):
        raise InputError('metadata: expected a JSON object')
    if metadata.get('instrument') != 'epr-01':
        raise InputError('metadata.instrument: expected epr-01')
    if metadata.get('synthetic') is not True:
        raise InputError('metadata.synthetic: expected JSON true for synthetic provenance')
    for field in ('sample_id', 'acquisition_mode'):
        value = metadata.get(field)
        if not isinstance(value, str) or not value.strip():
            raise InputError(f'metadata.{field}: expected a nonempty string')
    if finite_number(metadata.get('frequency_GHz'), 'metadata.frequency_GHz') <= 0:
        raise InputError('metadata.frequency_GHz: must be positive')
    units = metadata.get('units')
    if not isinstance(units, dict):
        raise InputError('metadata.units: expected an object')
    expected = {'temperature': 'K', 'intensity': 'a.u.'}
    for field, unit in expected.items():
        if units.get(field) != unit:
            raise InputError(f'metadata.units.{field}: expected {unit}')
    if set(units) != set(expected):
        raise InputError('metadata.units: expected only temperature and intensity keys')
    return metadata


def read_data():
    reader = csv.DictReader(sys.stdin, strict=True)
    temperatures = []
    intensities = []
    try:
        headers = reader.fieldnames
        expected = ['temperature_K', 'intensity_au']
        if headers is None or len(headers) != 2 or set(headers) != set(expected):
            raise InputError('CSV.headers: expected temperature_K and intensity_au exactly once')
        for row_number, row in enumerate(reader, start=1):
            if None in row or any(value is None for value in row.values()):
                raise InputError(f'CSV.row[{row_number}]: expected exactly two fields')
            temperature = finite_number(row['temperature_K'], f'temperature_K[{row_number}]')
            intensity = finite_number(row['intensity_au'], f'intensity_au[{row_number}]')
            if temperature <= 0:
                raise InputError(f'temperature_K[{row_number}]: Kelvin temperature must be positive')
            if temperatures and temperature <= temperatures[-1]:
                raise InputError(f'temperature_K[{row_number}]: values must be strictly increasing and distinct')
            temperatures.append(temperature)
            intensities.append(intensity)
    except csv.Error as exc:
        raise InputError(f'CSV.line[{reader.line_num}]: {exc}') from None
    if len(temperatures) < 3:
        raise InputError('temperature_K: require at least three distinct increasing values')
    return temperatures, intensities


def fit_quality(intensities, residual):
    """Return population RMSE and unweighted R squared.

    R squared is undefined for constant measured intensities (TSS = 0),
    so those series return JSON null, including an exact constant fit.
    Scaled sums avoid unnecessary overflow when squaring values.
    """
    residual_scale = max(abs(value) for value in residual)
    residual_sum = (0.0 if residual_scale == 0 else
                    math.fsum((value / residual_scale) ** 2 for value in residual))
    rmse = residual_scale * math.sqrt(residual_sum / len(residual))
    if not math.isfinite(rmse):
        raise InputError('intensity_au: RMSE is outside finite floating-point range')
    if all(value == intensities[0] for value in intensities):
        return rmse, None

    intensity_scale = max(abs(value) for value in intensities)
    normalized = [value / intensity_scale for value in intensities]
    mean = statistics.mean(normalized)
    deviations = [value - mean for value in normalized]
    deviation_scale = max(abs(value) for value in deviations)
    if deviation_scale == 0:
        raise InputError('intensity_au: nonconstant variation is below floating-point precision')
    tss_scaled = math.fsum((value / deviation_scale) ** 2 for value in deviations)
    if residual_scale == 0:
        return rmse, 1.0
    # RSS/TSS, evaluated through its square root to avoid squaring
    # either the original observations or their residuals directly.
    ratio_root = ((residual_scale / intensity_scale) / deviation_scale
                  * math.sqrt(residual_sum / tss_scaled))
    r_squared = 1.0 - ratio_root * ratio_root
    if not math.isfinite(r_squared):
        raise InputError('intensity_au: r_squared is outside finite floating-point range')
    return rmse, r_squared


def fit_curie(temperatures, intensities):
    inverse = []
    for index, temperature in enumerate(temperatures, start=1):
        value = 1.0 / temperature
        if not math.isfinite(value) or value <= 0:
            raise InputError(f'temperature_K[{index}]: reciprocal is outside finite positive floating-point range')
        if inverse and value >= inverse[-1]:
            raise InputError(f'temperature_K[{index}]: reciprocal values are indistinguishable at floating-point precision')
        inverse.append(value)
    try:
        fit = statistics.linear_regression(inverse, intensities)
        coefficient, background = fit.slope, fit.intercept
        if not math.isfinite(coefficient) or not math.isfinite(background):
            raise InputError('intensity_au: regression produced nonfinite coefficients')
        predicted = [coefficient * value + background for value in inverse]
        residual = [measured - estimate for measured, estimate in zip(intensities, predicted)]
        if not all(math.isfinite(value) for value in predicted + residual):
            raise InputError('intensity_au: regression produced nonfinite predictions or residuals')
        rmse, r_squared = fit_quality(intensities, residual)
    except (statistics.StatisticsError, OverflowError, ZeroDivisionError) as exc:
        raise InputError(f'temperature_K/intensity_au: calculation cannot be represented at floating-point precision ({exc})') from None
    return {
        'coefficient_au_K': coefficient,
        'background_au': background,
        'rmse_au': rmse,
        'predicted_au': predicted,
        'residual_au': residual,
        'r_squared': r_squared,
    }


def main():
    try:
        read_metadata()
        temperatures, intensities = read_data()
        result = fit_curie(temperatures, intensities)
        output = json.dumps(result, allow_nan=False, separators=(',', ':'))
        status = 0
    except InputError as exc:
        output = json.dumps({'error': str(exc)}, separators=(',', ':'))
        status = 1
    except (UnicodeError, OSError) as exc:
        output = json.dumps({'error': f'CSV.input: {exc}'}, separators=(',', ':'))
        status = 1
    except (RecursionError, ValueError) as exc:
        output = json.dumps({'error': f'input: {exc}'}, separators=(',', ':'))
        status = 1
    print(output)
    return status


if __name__ == '__main__':
    sys.exit(main())
