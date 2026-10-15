// Package contract embeds the files shared between the Go bridge and the Python server.
package contract

import _ "embed"

// Schema is the SQLite schema of the message store (see schema.sql).
//
//go:embed schema.sql
var Schema string

// API describes the bridge's REST API as (state -> response) cases (see api.json).
//
//go:embed api.json
var API []byte
