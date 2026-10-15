# mcp-whatsapp

Read-only WhatsApp over MCP. A Go [whatsmeow](https://github.com/tulir/whatsmeow) **bridge** keeps a
linked-device session and stores message text in SQLite; the Python **MCP server** reads that
database. Inspired by [lharries/whatsapp-mcp](https://github.com/lharries/whatsapp-mcp) (MIT), rebuilt
around an explicit contract.

- **Cannot send.** The bridge has no send, upload or download code (a test fails the build if one
  appears), its REST API only reports pairing state and listens on `127.0.0.1`, and the MCP server
  opens the database read-only.
- **Allowlist.** Only chats in `WHATSAPP_ALLOWED_CHATS` are readable.
- **Pairing through MCP.** No terminal needed to scan the QR code.

Media is not downloaded; messages show their `media_type` only.

## Tools

| Tool | Description |
|------|-------------|
| `get_auth_status` | `paired`, `unpaired` or `logged_out` |
| `get_pairing_qr` | Raw QR payload while a code is available (codes rotate ~every 20 s; re-fetch if a scan fails) |
| `list_available_chats` | JID, name and last activity of **all** chats, no content. For filling in `WHATSAPP_ALLOWED_CHATS` |
| `list_chats`, `get_chat` | Allowed chats |
| `list_messages`, `get_message_context` | Messages of allowed chats (filter by chat, sender, date, text) |
| `search_contacts` | Allowed direct chats by name or number |

Anything outside the allowlist gives the same `Chat or message not found` error as something that
does not exist. Dates are ISO-8601; a value without a timezone is UTC.

## Setup

1. Deploy with the example values (`chart/values/mcp-whatsapp.yaml`). The pod runs the MCP server
   plus a `whatsapp-bridge` sidecar from the same image, sharing a volume at `/store`.
2. **Pair:** ask the agent to call `get_pairing_qr` and render the payload as a QR code. Scan it in
   WhatsApp → Linked devices → Link a device. `get_auth_status` turns `paired`. If the phone later
   unlinks the device the status becomes `logged_out` and a fresh code is offered automatically.
3. **Allow chats:** ask the agent to call `list_available_chats`, set `WHATSAPP_ALLOWED_CHATS` to the
   JIDs you want (comma-separated) and redeploy. Copy JIDs exactly as listed: WhatsApp may identify
   a contact by phone number (`…@s.whatsapp.net`) or by an opaque id (`…@lid`).

## Configuration

| Variable | Default | Container | Description |
|----------|---------|-----------|-------------|
| `WHATSAPP_ALLOWED_CHATS` | *(empty)* | server | Comma-separated chat JIDs. Empty = no chat content is served. |
| `WHATSAPP_DB_PATH` | `/store/messages.db` | server | Bridge message database |
| `WHATSAPP_BRIDGE_URL` | `http://127.0.0.1:8080` | server | Bridge REST API |
| `WHATSAPP_STORE_DIR` | `/store` | bridge | Session + message databases. **Back with a volume**, or you re-pair on every restart. |
| `WHATSAPP_BRIDGE_PORT` | `8080` | bridge | Loopback port of the REST API |
| `PORT` | `8000` | server | MCP HTTP port |

## The contract between Go and Python

Two files in [`contract/`](contract/) are the only interface. Both sides load them; neither
side restates them.

- [`schema.sql`](contract/schema.sql): the SQLite schema. The bridge applies it on startup and is the
  only writer; the server reads it (`mode=ro`). Timestamps are UTC `YYYY-MM-DDTHH:MM:SSZ`.
- [`api.json`](contract/api.json): the bridge's REST API as *(state → response)* cases:
  `GET /api/auth/status` and `GET /api/auth/qr`, nothing else.

## Tests

```bash
make test SERVER=mcp-whatsapp   # Python, incl. the integration tests below
make go-test                    # Go bridge (race detector on)
```

| Layer | What it proves |
|-------|----------------|
| Go: handler | every case in `api.json` is produced by the real handler; no other route, no non-GET |
| Go: store | schema columns, UTC timestamps, upsert rules, foreign keys, media-type check |
| Go: convert / events | message and history conversion; name resolution with fakes |
| Go: pairing | rotating codes, timeout retry, errors never exit, logout → re-pair (fake linker) |
| Go: guard | static check that no send/upload/download call exists in the bridge |
| Python: store | allowlist leak matrix over every read path, indistinguishable errors, date handling, literal search, bounds, read-only |
| Python: tools | strict schemas, argument validation, mock bridge generated from `api.json` |
| Python: server | MCP over HTTP end to end, failures as tool errors |
| Integration | the Go code writes a database the Python code reads; the built bridge binary answers the Python client and stays up unpaired |

Not covered by automated tests: the live connection to WhatsApp (pairing with a real phone).
