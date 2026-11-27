"""One bounded noninteractive Codex request, authenticated by the user's CLI."""
import json

from lab_codex_worker import run_worker

from .context import dump


def generate(order, context, destination, base=None):
    prompt = (
        "Write the complete standalone scientific Python application described below. "
        "Return source and a concise implementation summary using the supplied response schema. "
        "Do not call tools. Use Python 3.11+ standard library only. Read CSV from sys.stdin "
        "with csv.DictReader; print exactly one JSON object to stdout. sys.argv[1] is mandatory acquisition metadata JSON; validate instrument, synthetic provenance, units matching CSV headers and finite input values. Require at least three distinct increasing field/temperature values; reject nonpositive Kelvin. Reject invalid inputs with a field-specific message and nonzero exit. Numeric scalars and project-specific arrays are allowed. "
        "Implement a general calculation for arbitrary valid input, never special-case a fixture. "
        "No hardware, filesystem, network, subprocess, argparse or external imports. "
        "Use a main function and a standard __main__ guard. Return source without markdown. "
        "Use the given project column names and contract. Field indices for extrema must be "
        "determined from the data. For the temperature project use statistics.linear_regression.\n"
        + json.dumps({"order": order, "context": context, "previous_source": base}, ensure_ascii=False)
    )
    (destination / "agent-prompt.txt").write_text(prompt)
    schema = {"type":"object","properties":{"source":{"type":"string"},"summary":{"type":"string"}},
              "required":["source","summary"],"additionalProperties":False}
    message, receipt = invoke_worker(prompt, schema)
    if not (0 < len(message["source"].encode()) <= 65536):
        raise ValueError("Generated source exceeds size contract")
    (destination / "analysis.py").write_text(message["source"].rstrip() + "\n")
    dump(destination / "generation.json", {**receipt, "summary": message["summary"]})


def _failure_message(result):
    errors = [line for line in result.stderr.splitlines() if "error" in line.lower()]
    return "Codex failed: " + (errors[-1][:350] if errors else f"exit {result.returncode}")


def invoke_worker(prompt, schema):
    """Run a tool-free local coding worker and return its response and provenance."""
    timeout = 180
    response = run_worker(
        prompt, json.dumps(schema, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        timeout=timeout, failure_message=_failure_message, include_version=True,
    )
    model = next((line.partition(":")[2].strip() for line in response.stderr.splitlines() if line.startswith("model:")),
                 "CLI default (identifier unavailable)")
    return response.answer, {"method": "codex exec", "cli": response.cli_version, "model": model,
                             "attempts": 1, "timeout_s": timeout, "tool_mode": "read-only, tool-free request"}
