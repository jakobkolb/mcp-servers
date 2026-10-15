-- Contract between the Go bridge (sole writer) and the Python MCP server (read-only).
-- Both sides load this file: the bridge applies it on startup, the tests build their
-- databases from it. Change it here or not at all.
--
-- Timestamps are TEXT in UTC, formatted 'YYYY-MM-DDTHH:MM:SSZ'. At that fixed width,
-- lexicographic order is chronological order, so SQL comparisons on them are correct.
-- Booleans are INTEGER 0/1. Text columns are never NULL ('' means unknown).

CREATE TABLE IF NOT EXISTS chats (
    jid               TEXT PRIMARY KEY,
    name              TEXT NOT NULL DEFAULT '',
    last_message_time TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id         TEXT NOT NULL,
    chat_jid   TEXT NOT NULL REFERENCES chats(jid),
    sender     TEXT NOT NULL DEFAULT '',  -- JID user part only, e.g. '4915111'
    content    TEXT NOT NULL DEFAULT '',
    timestamp  TEXT NOT NULL,
    is_from_me INTEGER NOT NULL DEFAULT 0 CHECK (is_from_me IN (0, 1)),
    media_type TEXT NOT NULL DEFAULT '' CHECK (media_type IN ('', 'image', 'video', 'audio', 'document')),
    PRIMARY KEY (id, chat_jid)
);

CREATE INDEX IF NOT EXISTS messages_chat_time ON messages (chat_jid, timestamp);

-- Display names by JID user part (= messages.sender): the name saved in the phone's
-- address book, else the name the person set on their profile. Rewritten whenever
-- names change, so it is joined at read time rather than copied into messages.
CREATE TABLE IF NOT EXISTS contacts (
    user TEXT PRIMARY KEY,
    name TEXT NOT NULL
);
