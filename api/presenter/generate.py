"""Generate and verify the hosted B12 analysis application from its supported spec."""
import json
import os
from urllib.request import Request, urlopen

from api.instrument import CALIBRATION, handler as InstrumentHandler
from factory.hosted_assay import compile_assay


class handler(InstrumentHandler):
    def do_POST(self):
        try:
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size <= 8192:
                raise ValueError("Insert a specification under 8 KB.")
            spec = json.loads(self.rfile.read(size))
            release = compile_assay(spec, "(signal - intercept) / slope", CALIBRATION)
        except (TypeError, ValueError) as exc:
            return self.reply(400, {"error": str(exc)})
        method = "EVOLVE protocol compiler"
        token = os.getenv("AI_GATEWAY_API_KEY") or os.getenv("VERCEL_OIDC_TOKEN")
        if token:
            model = "openai/gpt-4o-mini"
            prompt = ("Generate the Python arithmetic expression that converts mean absorbance signal "
                      "to concentration using a linear calibration with slope and intercept. "
                      "Return only the expression using signal, slope, intercept, parentheses and arithmetic. "
                      "Experiment: " + json.dumps({k:v for k,v in spec.items() if k != "application_name"}))
            request = Request("https://ai-gateway.vercel.sh/v1/chat/completions",
                              data=json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}],
                                               "max_tokens": 80}).encode(),
                              headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
            try:
                with urlopen(request, timeout=12) as response:
                    expression = json.load(response)["choices"][0]["message"]["content"]
                release = compile_assay(spec, expression, CALIBRATION)
                method = model + " + EVOLVE protocol compiler"
            except (OSError, ValueError, KeyError, IndexError, TypeError, SyntaxError, ArithmeticError):
                pass
        self.reply(200, {**release, "worker": {"model": method}})
