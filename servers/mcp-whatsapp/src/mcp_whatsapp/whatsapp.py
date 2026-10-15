"""Query layer over the bridge's SQLite store (contract/schema.sql).

Every content query goes through `_scope`, which restricts it to the allowlist, so no
tool can return data from a chat that is not allowed. The only unfiltered query is
`list_available_chats`, and it selects no message content.
"""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from typing import Any

from .config import Config

NOT_FOUND = "Chat or message not found"
# Messages with their sender's display name (NULL when the bridge knows none).
_MESSAGES = "messages m LEFT JOIN contacts ct ON ct.user = m.sender"
_MESSAGE_COLS = (
    "m.id, m.chat_jid, m.sender, ct.name AS sender_name, m.content, m.timestamp,"
    " m.is_from_me, m.media_type"
)
MAX_LIMIT = 100
_STORED_FORMAT = "%Y-%m-%dT%H:%M:%SZ"  # contract: UTC, fixed width


class NotFound(Exception):
    """Raised for missing and disallowed chats alike, so the two cannot be told apart."""

    def __init__(self) -> None:
        super().__init__(NOT_FOUND)


class StoreUnavailable(RuntimeError):
    pass


def _utc(value: str | None, name: str) -> str | None:
    """Normalise an ISO-8601 input to the stored format. Naive values are UTC."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"Invalid date for '{name}': {value!r}. Use ISO-8601.") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).strftime(_STORED_FORMAT)


def _page(limit: int, page: int) -> int:
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
    if page < 0:
        raise ValueError("page must be >= 0")
    return limit * page


def _chat(row: sqlite3.Row) -> dict[str, Any]:
    return {"jid": row["jid"], "name": row["name"], "last_active": row["last_message_time"]}


class Store:
    def __init__(self, config: Config) -> None:
        self._db_path = config.db_path
        self._allowed = sorted(config.allowed_chats)

    def _rows(self, sql: str, params: list[Any]) -> list[sqlite3.Row]:
        # Read-only: the bridge is the only writer.
        with closing(sqlite3.connect(f"file:{self._db_path}?mode=ro", uri=True, timeout=5)) as db:
            db.row_factory = sqlite3.Row
            db.create_function("fold", 1, lambda s: s.casefold(), deterministic=True)
            return db.execute(sql, params).fetchall()

    def _select(self, sql: str, params: list[Any]) -> list[sqlite3.Row]:
        try:
            return self._rows(sql, params)
        except sqlite3.OperationalError as e:
            if "unable to open" in str(e) or "no such table" in str(e):
                raise StoreUnavailable(
                    "Message database not available yet; is the WhatsApp bridge running and paired?"
                ) from e
            raise

    def _scope(self, column: str) -> tuple[str, list[Any]]:
        if not self._allowed:
            return "0", []
        return f"{column} IN ({','.join('?' * len(self._allowed))})", list(self._allowed)

    def list_available_chats(self) -> list[dict[str, Any]]:
        rows = self._select(
            "SELECT jid, name, last_message_time FROM chats ORDER BY last_message_time DESC, jid",
            [],
        )
        return [_chat(r) for r in rows]

    def list_chats(
        self, query: str | None = None, limit: int = 20, page: int = 0, sort_by: str = "last_active"
    ) -> list[dict[str, Any]]:
        offset = _page(limit, page)
        if sort_by not in ("last_active", "name"):
            raise ValueError("sort_by must be 'last_active' or 'name'")
        scope, params = self._scope("jid")
        sql = f"SELECT jid, name, last_message_time FROM chats WHERE {scope}"
        if query:
            sql += " AND (instr(fold(name), ?) > 0 OR instr(fold(jid), ?) > 0)"
            params += [query.casefold()] * 2
        sql += " ORDER BY " + (
            "fold(name), jid" if sort_by == "name" else "last_message_time DESC, jid"
        )
        sql += " LIMIT ? OFFSET ?"
        return [_chat(r) for r in self._select(sql, [*params, limit, offset])]

    def get_chat(self, chat_jid: str) -> dict[str, Any]:
        scope, params = self._scope("jid")
        rows = self._select(
            f"SELECT jid, name, last_message_time FROM chats WHERE jid = ? AND {scope}",
            [chat_jid, *params],
        )
        if not rows:
            raise NotFound
        return _chat(rows[0])

    def list_messages(
        self,
        after: str | None = None,
        before: str | None = None,
        sender: str | None = None,
        chat_jid: str | None = None,
        query: str | None = None,
        limit: int = 20,
        page: int = 0,
    ) -> list[dict[str, Any]]:
        offset = _page(limit, page)
        scope, params = self._scope("m.chat_jid")
        sql = (
            f"SELECT {_MESSAGE_COLS}, c.name AS chat_name"
            f" FROM {_MESSAGES} JOIN chats c ON c.jid = m.chat_jid"
            f" WHERE {scope}"
        )
        for clause, value in (
            ("m.timestamp > ?", _utc(after, "after")),
            ("m.timestamp < ?", _utc(before, "before")),
            ("m.sender = ?", sender),
            ("m.chat_jid = ?", chat_jid),
            ("instr(fold(m.content), ?) > 0", query.casefold() if query else None),
        ):
            if value:
                sql += f" AND {clause}"
                params.append(value)
        sql += " ORDER BY m.timestamp DESC, m.rowid DESC LIMIT ? OFFSET ?"
        rows = self._select(sql, [*params, limit, offset])
        return [{**dict(r), "is_from_me": bool(r["is_from_me"])} for r in rows]

    def get_message_context(
        self, message_id: str, chat_jid: str, before: int = 5, after: int = 5
    ) -> dict[str, Any]:
        scope, params = self._scope("m.chat_jid")
        cols = f"m.rowid AS rid, {_MESSAGE_COLS} FROM {_MESSAGES}"
        target = self._select(
            f"SELECT {cols} WHERE m.id = ? AND m.chat_jid = ? AND {scope}",
            [message_id, chat_jid, *params],
        )
        if not target:
            raise NotFound
        rid = target[0]["rid"]

        def fmt(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
            return [
                {k: (bool(r[k]) if k == "is_from_me" else r[k]) for k in r.keys() if k != "rid"}  # noqa: SIM118
                for r in rows
            ]

        # rowid breaks timestamp ties, so neighbours are well-defined within one chat.
        order = "ORDER BY m.timestamp {d}, m.rowid {d} LIMIT ?"
        older = self._select(
            f"SELECT {cols} WHERE m.chat_jid = ?"
            f" AND (m.timestamp, m.rowid) < (?, ?) {order.format(d='DESC')}",
            [chat_jid, target[0]["timestamp"], rid, before],
        )
        newer = self._select(
            f"SELECT {cols} WHERE m.chat_jid = ?"
            f" AND (m.timestamp, m.rowid) > (?, ?) {order.format(d='ASC')}",
            [chat_jid, target[0]["timestamp"], rid, after],
        )
        return {"before": fmt(older[::-1]), "message": fmt(target)[0], "after": fmt(newer)}

    def search_contacts(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Allowed direct chats by name or number; groups are not contacts."""
        scope, params = self._scope("jid")
        rows = self._select(
            f"SELECT jid, name FROM chats WHERE {scope} AND jid NOT LIKE '%@g.us'"
            " AND (instr(fold(name), ?) > 0 OR instr(jid, ?) > 0) ORDER BY fold(name), jid LIMIT ?",
            [*params, query.casefold(), query, limit],
        )
        return [{"jid": r["jid"], "name": r["name"]} for r in rows]
