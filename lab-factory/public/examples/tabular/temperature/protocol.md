# Temperature sensor calibration

Each batch contains simulated sensor readings in millivolts and reference temperatures in degrees Celsius. Use the standards measured in that batch. Sort them by voltage. At a standard voltage, report its reference temperature. Between standards, interpolate linearly between the two neighboring reference temperatures. Report the unrounded temperature in degrees Celsius.

Each standard must have a unique voltage. A voltage outside the calibration interval has no reportable temperature. The check sample has a separately assigned temperature.
