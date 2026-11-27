// A deliberately small Python tokenizer for tinting code: keywords, strings and comments only.
// Everything else is plain text, and joining the tokens' text gives back the code exactly.

export type PythonToken = { kind: "keyword" | "string" | "comment" | "text"; text: string };

const KEYWORDS = new Set([
  "False", "None", "True", "and", "as", "assert", "async", "await", "break", "class", "continue", "def", "del",
  "elif", "else", "except", "finally", "for", "from", "global", "if", "import", "in", "is", "lambda", "nonlocal",
  "not", "or", "pass", "raise", "return", "try", "while", "with", "yield",
]);

const STRING_PREFIX = /^(?:[rRuUbBfF]|[rR][bBfF]|[bBfF][rR])$/;
const WORD = /[A-Za-z_0-9]/;

/** Where the string starting at `start` (on its opening quote) ends, exclusive. */
function stringEnd(code: string, start: number): number {
  const quote = code[start];
  const triple = code.startsWith(quote.repeat(3), start);
  const close = triple ? quote.repeat(3) : quote;
  let i = start + close.length;
  while (i < code.length) {
    const c = code[i];
    if (c === "\\") { i += 2; continue; }
    if (!triple && c === "\n") return i;
    if (code.startsWith(close, i)) return i + close.length;
    i += 1;
  }
  return code.length;
}

export function tokenizePython(code: string): PythonToken[] {
  const tokens: PythonToken[] = [];
  let text = "";
  const push = (kind: PythonToken["kind"], value: string) => {
    if (text !== "") { tokens.push({ kind: "text", text }); text = ""; }
    tokens.push({ kind, text: value });
  };
  let i = 0;
  while (i < code.length) {
    const c = code[i];
    if (c === "#") {
      const newline = code.indexOf("\n", i);
      const end = newline === -1 ? code.length : newline;
      push("comment", code.slice(i, end));
      i = end;
    } else if (c === '"' || c === "'") {
      const end = stringEnd(code, i);
      push("string", code.slice(i, end));
      i = end;
    } else if (WORD.test(c) && (i === 0 || !WORD.test(code[i - 1]))) {
      let end = i;
      while (end < code.length && WORD.test(code[end])) end += 1;
      const word = code.slice(i, end);
      const next = code[end];
      if ((next === '"' || next === "'") && STRING_PREFIX.test(word)) {
        const close = stringEnd(code, end);
        push("string", code.slice(i, close));
        i = close;
      } else if (KEYWORDS.has(word)) {
        push("keyword", word);
        i = end;
      } else {
        text += word;
        i = end;
      }
    } else {
      text += c;
      i += 1;
    }
  }
  if (text !== "") tokens.push({ kind: "text", text });
  return tokens;
}
