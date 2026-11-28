"""Read the scalar analyze.m profile into the shared bounded arithmetic evaluator."""

import re


INSTRUCTIONS = (
    "Submit MATLAB source for analyze.m with exactly three statements on separate lines: "
    "function result = analyze(standards, signal, factor), then result = <expression>;, then end. "
    "Use scalar inputs signal and factor, finite numeric literals, parentheses, +, -, *, /, "
    "and abs, sqrt, exp, log or log10 of one scalar. For a piecewise linear calibration table "
    "use interp1(standards(:,1), standards(:,2), signal, 'linear'). Standards are an N-by-2 "
    "numeric matrix of [signal, known] rows. The batch requires unique standard signals for interpolation. "
    "The host withholds out-of-range interpolation and nonfinite results. No additional functions, "
    "assignments or toolboxes are supported by this profile."
)

_HEADER = re.compile(r"function\s+result\s*=\s*analyze\s*\(\s*standards\s*,\s*signal\s*,\s*factor\s*\)")
_INTERPOLATION = (
    r"interp1\s*\(\s*standards\s*\(\s*:\s*,\s*1\s*\)\s*,\s*"
    r"standards\s*\(\s*:\s*,\s*2\s*\)\s*,\s*signal\s*(?:,\s*'linear'\s*)?\)"
)
_TOKEN = re.compile(
    rf"(?P<table>{_INTERPOLATION})|(?P<number>(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)"
    r"|(?P<name>signal|factor|abs|sqrt|exp|log10|log)\b|(?P<operator>[()+*/-])|(?P<space>[ \t]+)",
    re.ASCII,
)


def numeric_source(source):
    """Lower only complete tokens in a single MATLAB scalar assignment."""
    if (not isinstance(source, str) or not source.isascii() or "%{" in source or "%}" in source
            or any(not ch.isprintable() and ch not in "\t\r\n" for ch in source)):
        raise ValueError("Supply an ASCII scalar MATLAB function.")
    lines = [line.partition("%")[0].strip(" \t") for line in source.splitlines()]
    lines = [line for line in lines if line]
    if len(lines) != 3 or not _HEADER.fullmatch(lines[0]) or lines[2] != "end":
        raise ValueError("Use function result = analyze(standards, signal, factor), one assignment, and end.")
    assignment = re.fullmatch(r"result\s*=\s*(.+?)\s*;?", lines[1], flags=re.ASCII)
    if not assignment:
        raise ValueError("Assign the scalar output to result.")
    expression = assignment[1]
    tokens = []
    offset = 0
    while offset < len(expression):
        token = _TOKEN.match(expression, offset)
        if token is None:
            raise ValueError("Unsupported expression in the MATLAB scalar profile.")
        if token.lastgroup == "table":
            tokens.append("interpolate(standards, signal)")
        elif token.lastgroup != "space":
            tokens.append(token[0])
        offset = token.end()
    return "def analyze(standards, signal, factor):\n    return " + " ".join(tokens)
