// Package bridge is a read-only WhatsApp recorder: it pairs a linked device, stores
// message text in SQLite (contract/schema.sql) and serves the pairing state over the
// loopback REST API described in contract/api.json. Nothing here sends anything.
package bridge

import (
	"encoding/json"
	"net/http"
	"sync"
)

type Status string

const (
	StatusPaired    Status = "paired"
	StatusUnpaired  Status = "unpaired"
	StatusLoggedOut Status = "logged_out"
)

// AuthState is the pairing state shared between the pairing loop and the REST API.
type AuthState struct {
	mu     sync.Mutex
	status Status
	qr     string
}

func NewAuthState() *AuthState { return &AuthState{status: StatusUnpaired} }

// Set replaces status and code. A paired device has no code.
func (a *AuthState) Set(s Status, qr string) {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.status, a.qr = s, qr
	if s == StatusPaired {
		a.qr = ""
	}
}

// SetQR publishes a code without touching the status (so logged_out survives until re-paired).
func (a *AuthState) SetQR(qr string) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.status != StatusPaired {
		a.qr = qr
	}
}

func (a *AuthState) Status() Status { a.mu.Lock(); defer a.mu.Unlock(); return a.status }
func (a *AuthState) QR() string     { a.mu.Lock(); defer a.mu.Unlock(); return a.qr }

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(v)
}

// Handler serves exactly the routes in contract/api.json.
func (a *AuthState) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /api/auth/status", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]Status{"status": a.Status()})
	})
	mux.HandleFunc("GET /api/auth/qr", func(w http.ResponseWriter, _ *http.Request) {
		if qr := a.QR(); qr != "" {
			writeJSON(w, http.StatusOK, map[string]string{"qr": qr})
			return
		}
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "no pairing code available"})
	})
	return mux
}

// ListenAddr binds to loopback only; the sidecar shares the pod network namespace.
func ListenAddr(port string) string { return "127.0.0.1:" + port }
