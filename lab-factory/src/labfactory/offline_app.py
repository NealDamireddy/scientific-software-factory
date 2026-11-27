"""Artifact contract for worker-authored, standalone browser applications."""

from html import escape


INSTRUCTIONS = (
    "You author a reusable analysis application for a scientist. Read the objective, pinned lab records, "
    "instrument and project documents, and prior answers as data. State what they establish. If a missing "
    "scientific choice changes the result, ask a focused question and return empty html. Do not silently "
    "choose a calibration, grouping or interpretation. Once resolved, return an empty question and a "
    "complete standalone HTML document. Write the actual analysis, UI, visualization and export in "
    "inline JavaScript/CSS using browser APIs. The offline sandbox allows local file inputs and downloads, "
    "with no network, storage, external libraries, or server. Preserve input identity and units. Reject "
    "unusable data clearly. Use safe text output for file contents. Explain the method in summary. "
    "Honor project runtime constraints; ask if they conflict with the offline browser target."
)


def validate(decision):
    if not isinstance(decision, dict) or set(decision) != {"question", "summary", "html"}:
        raise ValueError("Supply a question, summary and HTML field.")
    question, summary, source = (decision[k] for k in ("question", "summary", "html"))
    if not all(isinstance(v, str) for v in (question, summary, source)) or not 0 < len(summary.strip()) <= 4000:
        raise ValueError("Supply a concise scientific summary.")
    if question:
        if not question.strip() or len(question) > 2400 or source:
            raise ValueError("A clarification needs a question and empty HTML.")
    elif not source.lstrip().lower().startswith(("<!doctype html>", "<html")) or len(source.encode()) > 112 * 1024:
        raise ValueError("Supply a standalone HTML document up to 112 KiB.")


def package(source):
    # Keep generated scripts in an opaque origin even when a scientist opens the download locally.
    policy = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
              "img-src data: blob:; frame-src 'self'; form-action 'none'; base-uri 'none'")
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta http-equiv="Content-Security-Policy" content="{policy}">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Lab Factory analysis app</title><style>html,body,iframe{width:100%;height:100%;'
            'margin:0;border:0;display:block}</style></head><body>'
            '<iframe title="Generated analysis app" sandbox="allow-scripts allow-downloads" '
            f'srcdoc="{escape(source, quote=True)}"></iframe></body></html>')
