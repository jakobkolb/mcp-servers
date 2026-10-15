import json
import sqlite3
from collections.abc import Callable

import pytest
from mcp_whatsapp.config import Config, load_config
from mcp_whatsapp.whatsapp import NOT_FOUND, NotFound, Store, StoreUnavailable

from .conftest import ALICE, BOB, FAMILY, ts


def store(config: Callable[..., Config], *allowed: str) -> Store:
    return Store(config(*allowed))


# ---- config ---------------------------------------------------------------


def test_config_parses_list_and_ignores_blanks(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ALLOWED_CHATS", " a@x , b@y,,  ")
    assert load_config().allowed_chats == {"a@x", "b@y"}


def test_config_defaults_to_nothing_allowed(monkeypatch):
    monkeypatch.delenv("WHATSAPP_ALLOWED_CHATS", raising=False)
    monkeypatch.delenv("WHATSAPP_DB_PATH", raising=False)
    cfg = load_config()
    assert cfg.allowed_chats == frozenset()
    assert cfg.db_path == "/store/messages.db"
    assert cfg.bridge_url == "http://127.0.0.1:8080"


# ---- the allowlist --------------------------------------------------------

SECRETS = {
    BOB: ["top secret", "Bob Secret", "4915222", "b1", "b2"],
    ALICE: ["hello from alice", "Alice", "a3"],
    FAMILY: ["family hello", "Family", "f1"],
}


def everything(s: Store) -> list[object]:
    """Run every read path with queries aimed at every chat; return all results."""
    out: list[object] = []
    out.append(s.list_chats())
    for q in ("", "Bob", "Secret", BOB, "4915222", "alice", "family", "%"):
        out.append(s.list_chats(query=q, limit=100))
        out.append(s.list_messages(query=q, limit=100))
        out.append(s.search_contacts(q))
    for chat in (ALICE, BOB, FAMILY):
        out.append(s.list_messages(chat_jid=chat, limit=100))
        out.append(s.list_messages(sender=chat.split("@")[0], limit=100))
        for fn in (
            lambda: s.get_chat(chat),
            lambda: s.get_message_context("b1", chat),
            lambda: s.get_message_context("a1", chat),
            lambda: s.get_message_context("f1", chat),
        ):
            try:
                out.append(fn())
            except NotFound:
                pass
    out.append(s.list_messages(after=ts(1, 0), before=ts(3, 0), limit=100))
    out.append(s.list_messages(limit=100, page=0))
    return out


@pytest.mark.parametrize(
    "allowed",
    [[], [ALICE], [FAMILY], [ALICE, FAMILY], [BOB], [ALICE, BOB, FAMILY]],
    ids=lambda a: "+".join(x.split("@")[0] for x in a) or "none",
)
def test_no_read_path_leaks_a_disallowed_chat(config, allowed):
    blob = json.dumps(everything(store(config, *allowed)))
    for chat, markers in SECRETS.items():
        for marker in markers:
            if chat in allowed:
                continue
            # "a1" exists in two chats; it is only secret if neither is allowed
            if marker in ("a1",) and any(c in allowed for c in (ALICE, FAMILY)):
                continue
            assert marker not in blob, f"{marker!r} of {chat} leaked with allowlist {allowed}"


def test_empty_allowlist_serves_nothing(config):
    s = store(config)
    assert s.list_chats() == []
    assert s.list_messages() == []
    assert s.search_contacts("") == []
    with pytest.raises(NotFound):
        s.get_chat(ALICE)
    with pytest.raises(NotFound):
        s.get_message_context("a2", ALICE)


def test_disallowed_and_nonexistent_are_indistinguishable(config):
    s = store(config, ALICE)
    seen = set()
    for call in (
        lambda: s.get_chat(BOB),
        lambda: s.get_chat("nobody@s.whatsapp.net"),
        lambda: s.get_message_context("b1", BOB),
        lambda: s.get_message_context("b1", ALICE),  # real id, wrong chat
        lambda: s.get_message_context("zzz", ALICE),
    ):
        with pytest.raises(NotFound) as e:
            call()
        seen.add(str(e.value))
    assert seen == {NOT_FOUND}


def test_list_available_chats_exposes_no_content_and_ignores_the_allowlist(config):
    for allowed in ([], [ALICE]):
        chats = store(config, *allowed).list_available_chats()
        assert [c["jid"] for c in chats] == [BOB, ALICE, FAMILY]  # newest activity first
        assert all(set(c) == {"jid", "name", "last_active"} for c in chats)
    assert chats[0]["last_active"] == ts(2, 11, 5)


# ---- queries --------------------------------------------------------------


def test_list_messages_newest_first_with_all_fields(config):
    msgs = store(config, ALICE).list_messages()
    assert [m["id"] for m in msgs] == ["a3", "a2", "a1"]
    assert msgs[0] == {
        "id": "a3",
        "chat_jid": ALICE,
        "chat_name": "Alice",
        "sender": "4915111",
        "content": "photo",
        "timestamp": ts(2, 10, 30),
        "is_from_me": False,
        "media_type": "image",
    }
    assert msgs[1]["is_from_me"] is True and msgs[1]["media_type"] == ""


def test_filters_combine(config):
    s = store(config, ALICE, BOB, FAMILY)
    assert [m["id"] for m in s.list_messages(chat_jid=BOB)] == ["b2", "b1"]
    assert [m["id"] for m in s.list_messages(sender="4900")] == ["a2"]
    assert [m["id"] for m in s.list_messages(query="HELLO", chat_jid=ALICE)] == ["a1"]
    assert s.list_messages(chat_jid=BOB, sender="4900") == []


def test_query_is_literal_not_a_like_pattern(config):
    s = store(config, BOB, ALICE)
    assert [m["id"] for m in s.list_messages(query="%")] == ["b2"]
    assert [m["id"] for m in s.list_messages(query="_")] == ["b2"]
    assert s.list_messages(query="'; DROP TABLE messages; --") == []
    assert len(s.list_messages()) == 5  # table still there


@pytest.mark.parametrize(
    ("after", "expected"),
    [
        (ts(2, 9, 5), ["a3"]),  # strictly after
        ("2026-01-02T09:05:00", ["a3"]),  # naive means UTC
        ("2026-01-02T10:05:00+01:00", ["a3"]),  # same instant, offset notation
        ("2026-01-02", ["a3", "a2", "a1"]),  # bare date (midnight UTC)
        ("2026-01-02T09:00:00.500Z", ["a3", "a2"]),  # sub-second precision
    ],
)
def test_after_filter_normalises_to_the_stored_format(config, after, expected):
    assert [m["id"] for m in store(config, ALICE).list_messages(after=after)] == expected


def test_before_filter(config):
    got = store(config, ALICE).list_messages(before=ts(2, 9, 5))
    assert [m["id"] for m in got] == ["a1"]


@pytest.mark.parametrize("bad", ["yesterday", "2026-13-01", "01/02/2026"])
def test_invalid_dates_are_rejected(config, bad):
    with pytest.raises(ValueError, match="after"):
        store(config, ALICE).list_messages(after=bad)


def test_empty_date_means_no_filter(config):
    assert len(store(config, ALICE).list_messages(after="", before="")) == 3


def test_pagination_does_not_overlap_or_skip(config):
    s = store(config, ALICE, BOB, FAMILY)
    pages = [s.list_messages(limit=3, page=p) for p in range(3)]
    ids = [(m["chat_jid"], m["id"]) for page in pages for m in page]
    assert len(ids) == len(set(ids)) == 7
    assert [len(p) for p in pages] == [3, 3, 1]


@pytest.mark.parametrize(("limit", "page"), [(0, 0), (-1, 0), (101, 0), (10, -1)])
def test_limit_and_page_bounds(config, limit, page):
    with pytest.raises(ValueError):
        store(config, ALICE).list_messages(limit=limit, page=page)
    with pytest.raises(ValueError):
        store(config, ALICE).list_chats(limit=limit, page=page)


def test_list_chats_sorting(config):
    s = store(config, ALICE, BOB, FAMILY)
    assert [c["jid"] for c in s.list_chats()] == [BOB, ALICE, FAMILY]
    assert [c["name"] for c in s.list_chats(sort_by="name")] == ["Alice", "Bob Secret", "Family"]
    with pytest.raises(ValueError, match="sort_by"):
        s.list_chats(sort_by="name; DROP TABLE chats")


def test_list_chats_query_matches_name_or_jid_case_insensitively(config):
    s = store(config, ALICE, BOB, FAMILY)
    assert [c["jid"] for c in s.list_chats(query="alice")] == [ALICE]
    assert [c["jid"] for c in s.list_chats(query="4915222")] == [BOB]
    assert [c["jid"] for c in s.list_chats(query="@g.us")] == [FAMILY]


def test_get_chat(config):
    assert store(config, ALICE).get_chat(ALICE) == {
        "jid": ALICE,
        "name": "Alice",
        "last_active": ts(2, 10, 30),
    }


def test_search_contacts_returns_allowed_direct_chats_only(config):
    s = store(config, ALICE, FAMILY)
    assert s.search_contacts("ali") == [{"jid": ALICE, "name": "Alice"}]
    assert s.search_contacts("4915111") == [{"jid": ALICE, "name": "Alice"}]
    assert s.search_contacts("family") == []  # groups are not contacts
    assert s.search_contacts("bob") == []  # not allowed


def test_message_context_is_chronological_and_bounded(config):
    ctx = store(config, ALICE).get_message_context("a2", ALICE, before=5, after=5)
    assert [m["id"] for m in ctx["before"]] == ["a1"]
    assert ctx["message"]["id"] == "a2"
    assert [m["id"] for m in ctx["after"]] == ["a3"]
    ctx = store(config, ALICE).get_message_context("a3", ALICE, before=1, after=1)
    assert [m["id"] for m in ctx["before"]] == ["a2"] and ctx["after"] == []


def test_message_context_with_an_id_shared_between_chats(config):
    s = store(config, ALICE, FAMILY)
    assert s.get_message_context("a1", ALICE)["message"]["content"] == "hello from alice"
    assert s.get_message_context("a1", FAMILY)["message"]["content"] == "same id, other chat"
    assert s.get_message_context("a1", FAMILY)["before"] == []  # no bleed from the other chat


# ---- the database ---------------------------------------------------------


def test_the_store_cannot_write(config):
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        store(config, ALICE)._rows("DELETE FROM messages", [])


def test_missing_database_is_reported_not_crashed(tmp_path):
    s = Store(Config(allowed_chats=frozenset({ALICE}), db_path=str(tmp_path / "nope.db")))
    for call in (s.list_chats, s.list_messages, s.list_available_chats):
        with pytest.raises(StoreUnavailable, match="bridge"):
            call()


def test_database_without_tables_is_reported(tmp_path):
    path = tmp_path / "empty.db"
    sqlite3.connect(path).close()
    s = Store(Config(allowed_chats=frozenset({ALICE}), db_path=str(path)))
    with pytest.raises(StoreUnavailable):
        s.list_chats()


def test_a_database_written_while_open_is_seen(config, db_path):
    s = store(config, ALICE)
    before = len(s.list_messages())
    db = sqlite3.connect(db_path)
    db.execute(
        "INSERT INTO messages VALUES ('a9', ?, '4915111', 'new', ?, 0, '')", (ALICE, ts(3, 1))
    )
    db.commit()
    db.close()
    assert len(s.list_messages()) == before + 1
