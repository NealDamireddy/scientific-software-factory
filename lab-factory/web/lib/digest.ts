// Canonical JSON and digests that match Lab Factory's Python side:
// json.dumps(value, sort_keys=True, separators=(",", ":")) with the default
// ensure_ascii=True, hashed as UTF-8 with SHA-256.

const SHORT_ESCAPES: Record<string, string> = {
  '"': '\\"',
  "\\": "\\\\",
  "\n": "\\n",
  "\r": "\\r",
  "\t": "\\t",
  "\b": "\\b",
  "\f": "\\f",
};

// Python escapes the quote, the backslash and everything outside space..tilde.
// Working per UTF-16 code unit yields surrogate pairs for astral characters,
// which is what Python emits too.
function quote(text: string): string {
  let out = '"';
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    const code = text.charCodeAt(i);
    const short = SHORT_ESCAPES[ch];
    if (short !== undefined) out += short;
    else if (code >= 0x20 && code <= 0x7e) out += ch;
    else out += "\\u" + code.toString(16).padStart(4, "0");
  }
  return out + '"';
}

// Python's float repr: shortest round-trip digits, fixed notation while the
// decimal exponent is in [-4, 16), otherwise d.ddde±XX. JavaScript picks the
// same digits but switches notation at different exponents.
function pythonFloat(value: number): string {
  const [mantissa, exponentText] = value.toExponential().split("e");
  const exponent = Number(exponentText);
  const negative = mantissa.startsWith("-");
  const digits = mantissa.replace("-", "").replace(".", "");
  let body: string;
  if (exponent >= -4 && exponent < 16) {
    if (exponent < 0) body = "0." + "0".repeat(-exponent - 1) + digits;
    else if (digits.length <= exponent + 1) body = digits.padEnd(exponent + 1, "0") + ".0";
    else body = digits.slice(0, exponent + 1) + "." + digits.slice(exponent + 1);
  } else {
    const head = digits.length > 1 ? digits[0] + "." + digits.slice(1) : digits;
    const sign = exponent < 0 ? "-" : "+";
    body = head + "e" + sign + String(Math.abs(exponent)).padStart(2, "0");
  }
  return (negative ? "-" : "") + body;
}

// JSON.parse cannot tell 1 from 1.0, so whole numbers in the safe range are
// written the way Python writes an int. Everything else is written as a float.
function formatNumber(value: number): string {
  if (!Number.isFinite(value)) throw new TypeError("canonicalJson cannot encode a non-finite number");
  if (Object.is(value, -0)) return "-0.0";
  if (Number.isSafeInteger(value)) return String(value);
  return pythonFloat(value);
}

// Python sorts keys by code point; JavaScript's default sort is by UTF-16
// code unit, which orders astral characters differently.
function byCodePoint(a: string, b: string): number {
  const left = Array.from(a);
  const right = Array.from(b);
  const shared = Math.min(left.length, right.length);
  for (let i = 0; i < shared; i += 1) {
    const delta = (left[i].codePointAt(0) as number) - (right[i].codePointAt(0) as number);
    if (delta !== 0) return delta;
  }
  return left.length - right.length;
}

export function canonicalJson(value: unknown): string {
  if (value === null) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return formatNumber(value);
  if (typeof value === "string") return quote(value);
  if (Array.isArray(value)) {
    return "[" + value.map((item) => (item === undefined ? "null" : canonicalJson(item))).join(",") + "]";
  }
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    const parts: string[] = [];
    for (const key of Object.keys(record).sort(byCodePoint)) {
      if (record[key] === undefined) continue;
      parts.push(quote(key) + ":" + canonicalJson(record[key]));
    }
    return "{" + parts.join(",") + "}";
  }
  throw new TypeError(`canonicalJson cannot encode a value of type ${typeof value}`);
}

export async function sha256Hex(text: string): Promise<string> {
  const bytes = new TextEncoder().encode(text);
  const hash = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(hash), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function canonicalDigest(value: unknown): Promise<string> {
  return sha256Hex(canonicalJson(value));
}
