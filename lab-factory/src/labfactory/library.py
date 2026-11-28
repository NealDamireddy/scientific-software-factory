"""Reference source text stored once, visible to everyone or to one lab, and pinned to work orders."""
import hashlib

from . import references
from .context import ContextError, Document, canonical_digest
from .store import NotFound

PREFIX = "library:"
SHARED = "shared"
MAX_TEXT_BYTES = 256 * 1024
MAX_TITLE = 250
MAX_PINNED = 8
_COLUMNS = ("e.id, e.source_id, e.scope, e.revision, e.kind, e.title, e.origin, e.text_digest, "
            "e.contributed_by, e.created_at, length(CAST(t.text AS BLOB)) AS size")
_FROM = "FROM library_entries e JOIN library_texts t ON t.digest = e.text_digest"
_NEWEST = ("e.revision = (SELECT MAX(revision) FROM library_entries "
           "WHERE source_id = e.source_id AND scope = e.scope)")


def lab_scope(lab_id: str) -> str:
    return "lab:" + lab_id


def _scope(lab_id) -> str:
    if lab_id is None:
        return SHARED
    if not isinstance(lab_id, str) or not lab_id.strip():
        raise ContextError("Lab id must be non-empty text.")
    return lab_scope(lab_id)


def _entry(row) -> dict:
    return {"id": row["id"], "source_id": row["source_id"], "scope": row["scope"],
            "revision": row["revision"], "kind": row["kind"], "title": row["title"],
            "origin": row["origin"], "digest": row["text_digest"], "bytes": row["size"],
            "contributed_by": row["contributed_by"], "created_at": row["created_at"],
            "document_id": PREFIX + row["source_id"]}


def _newest(store, source_id, scope):
    return store.connection.execute(
        f"SELECT {_COLUMNS} {_FROM} WHERE e.source_id = ? AND e.scope = ? ORDER BY e.revision DESC LIMIT 1",
        (source_id, scope)).fetchone()


def _validate_text(text):
    if not isinstance(text, str) or not text.strip():
        raise ContextError("Library text must be non-empty text.")
    if "\x00" in text:
        raise ContextError("Library text cannot contain NUL characters.")
    try:
        size = len(text.encode("utf-8"))
    except UnicodeEncodeError:
        raise ContextError("Library text must be valid UTF-8.") from None
    if size > MAX_TEXT_BYTES:
        raise ContextError(f"Library text is limited to {MAX_TEXT_BYTES} bytes.")


def _resolve_source(store, actor, source_id, title, lab_id, scopes):
    """Return (source_id, kind, title, origin) for a catalog, existing or newly contributed source."""
    if source_id is not None:
        if not isinstance(source_id, str):
            raise ContextError("Unknown library source.")
        try:
            catalog = references.source(source_id)
        except ContextError:
            catalog = None
        if catalog:
            kind = "note" if catalog["kind"] == "procedure" else catalog["kind"]
            return source_id, kind, catalog["title"], catalog["url"]
        row = store.connection.execute(
            "SELECT kind, title, origin FROM library_entries WHERE source_id = ? "
            f"AND scope IN ({','.join('?' * len(scopes))}) ORDER BY id LIMIT 1",
            (source_id, *scopes)).fetchone()
        if row:
            return source_id, row["kind"], row["title"], row["origin"]
        raise ContextError("Unknown library source.")
    if not isinstance(title, str) or not (1 <= len(title.strip()) <= MAX_TITLE) \
            or not title.strip().isprintable():
        raise ContextError(f"Provide a source id or a title of 1 to {MAX_TITLE} printable characters.")
    title = title.strip()
    source_id = "contributed-" + canonical_digest([lab_id or "", title.casefold()])[:16]
    return source_id, "note", title, "Supplied by " + actor


def _insert(store, actor, source_id, scope, kind, title, origin, digest):
    revision = store.connection.execute(
        "SELECT COALESCE(MAX(revision), 0) + 1 FROM library_entries WHERE source_id = ? AND scope = ?",
        (source_id, scope)).fetchone()[0]
    cursor = store.connection.execute(
        "INSERT INTO library_entries (source_id, scope, revision, kind, title, origin, text_digest, "
        "contributed_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (source_id, scope, revision, kind, title, origin, digest, actor))
    return _entry(_one(store, cursor.lastrowid))


def _one(store, entry_id):
    row = store.connection.execute(f"SELECT {_COLUMNS} {_FROM} WHERE e.id = ?", (entry_id,)).fetchone()
    if row is None:
        raise NotFound("Library entry not found")
    return row


def add(store, actor: str, text: str, *, source_id: str | None = None, title: str | None = None,
        lab_id: str | None = None) -> dict:
    _validate_text(text)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    scope = _scope(lab_id)
    source_id, kind, title, origin = _resolve_source(store, actor, source_id, title, lab_id, {SHARED, scope})
    with store.transaction():
        newest = _newest(store, source_id, scope)
        if newest is not None and newest["text_digest"] == digest:
            return _entry(newest)
        store.connection.execute("INSERT OR IGNORE INTO library_texts (digest, text) VALUES (?, ?)",
                                 (digest, text))
        return _insert(store, actor, source_id, scope, kind, title, origin, digest)


def get(store, entry_id: int) -> dict:
    row = _one(store, entry_id)
    text = store.connection.execute("SELECT text FROM library_texts WHERE digest = ?",
                                    (row["text_digest"],)).fetchone()[0]
    return {**_entry(row), "text": text}


def latest(store, lab_id: str | None = None) -> list[dict]:
    scopes = sorted({SHARED, _scope(lab_id)})
    rows = store.connection.execute(
        f"SELECT {_COLUMNS} {_FROM} WHERE {_NEWEST} AND e.scope IN ({','.join('?' * len(scopes))}) "
        "ORDER BY e.title, e.scope", scopes).fetchall()
    return [_entry(row) for row in rows]


def visible(store, lab_id: str | None, source_ids=None) -> dict[str, dict]:
    wanted = None if source_ids is None else set(source_ids)
    found = {}
    for entry in latest(store, lab_id):
        if wanted is not None and entry["source_id"] not in wanted:
            continue
        if entry["source_id"] not in found or entry["scope"] != SHARED:
            found[entry["source_id"]] = entry
    return found


def share(store, actor: str, entry_id: int) -> dict:
    with store.transaction():
        row = _one(store, entry_id)
        if row["scope"] == SHARED:
            return _entry(row)
        newest = _newest(store, row["source_id"], SHARED)
        if newest is not None and newest["text_digest"] == row["text_digest"]:
            return _entry(newest)
        return _insert(store, actor, row["source_id"], SHARED, row["kind"], row["title"], row["origin"],
                       row["text_digest"])


def pin(store, work_order_id: str, entries: list[dict]) -> list[dict]:
    """Pin entry rows to an order in the given order, skipping document ids already pinned."""
    with store.transaction():
        have = {r["document_id"] for r in store.connection.execute(
            "SELECT document_id FROM work_order_library WHERE work_order_id = ?", (work_order_id,))}
        position = store.connection.execute(
            "SELECT COALESCE(MAX(position), 0) FROM work_order_library WHERE work_order_id = ?",
            (work_order_id,)).fetchone()[0]
        for entry in entries:
            if len(have) >= MAX_PINNED:
                break
            if entry["document_id"] in have:
                continue
            position += 1
            have.add(entry["document_id"])
            store.connection.execute(
                "INSERT INTO work_order_library (work_order_id, document_id, entry_id, position) "
                "VALUES (?, ?, ?, ?)", (work_order_id, entry["document_id"], entry["id"], position))
    return pinned(store, work_order_id)


def pinned(store, work_order_id: str) -> list[dict]:
    rows = store.connection.execute(
        "SELECT w.document_id, w.entry_id, e.source_id, e.title, e.scope, e.revision "
        "FROM work_order_library w JOIN library_entries e ON e.id = w.entry_id "
        "WHERE w.work_order_id = ? ORDER BY w.position", (work_order_id,)).fetchall()
    return [{"document_id": r["document_id"], "source_id": r["source_id"], "title": r["title"],
             "scope": SHARED if r["scope"] == SHARED else "lab", "entry_id": r["entry_id"],
             "revision": r["revision"]} for r in rows]


def copy(store, source_order_id: str, target_order_id: str) -> None:
    store.connection.execute(
        "INSERT OR IGNORE INTO work_order_library (work_order_id, document_id, entry_id, position) "
        "SELECT ?, document_id, entry_id, position FROM work_order_library WHERE work_order_id = ?",
        (target_order_id, source_order_id))


def documents(store, work_order_id: str) -> tuple[Document, ...]:
    rows = store.connection.execute(
        "SELECT w.document_id, e.kind, e.title, e.origin, t.text FROM work_order_library w "
        "JOIN library_entries e ON e.id = w.entry_id JOIN library_texts t ON t.digest = e.text_digest "
        "WHERE w.work_order_id = ? ORDER BY w.position", (work_order_id,)).fetchall()
    return tuple(Document(r["document_id"], r["kind"], r["title"], r["origin"], r["text"]) for r in rows)
