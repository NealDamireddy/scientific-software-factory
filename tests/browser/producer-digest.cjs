const { execFileSync } = require("node:child_process");

// Give the producer the original JSON bytes. Re-encoding via JS could change numeric tokens.
function producerDigest(json, ...keys) {
  const script = `import json, sys
from factory.context import digest
from factory.lab_context.context_repository import canonical_json
payload = json.load(sys.stdin.buffer)
for key in sys.argv[1:]:
    payload = payload[key]
print(digest(canonical_json(payload).encode("utf-8")))`;
  return execFileSync("python3", ["-c", script, ...keys], { input: json, encoding: "utf8" }).trim();
}
module.exports = { producerDigest };
