package bridge

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"whatsapp-bridge/contract"
)

type apiCase struct {
	Name  string `json:"name"`
	State struct {
		Status string `json:"status"`
		QR     string `json:"qr"`
	} `json:"state"`
	HTTP int             `json:"http"`
	Body json.RawMessage `json:"body"`
}

type apiEndpoint struct {
	Method string    `json:"method"`
	Path   string    `json:"path"`
	Cases  []apiCase `json:"cases"`
}

func loadAPI(t *testing.T) map[string]apiEndpoint {
	t.Helper()
	var doc struct {
		Endpoints map[string]apiEndpoint `json:"endpoints"`
	}
	if err := json.Unmarshal(contract.API, &doc); err != nil {
		t.Fatal(err)
	}
	return doc.Endpoints
}

// Every case in contract/api.json must be produced by the real handler: the Python
// mock bridge is generated from the same file, so the two sides cannot drift.
func TestHandlerMatchesContract(t *testing.T) {
	for name, ep := range loadAPI(t) {
		for _, c := range ep.Cases {
			t.Run(name+"/"+c.Name, func(t *testing.T) {
				a := NewAuthState()
				a.Set(Status(c.State.Status), c.State.QR)
				rec := httptest.NewRecorder()
				a.Handler().ServeHTTP(rec, httptest.NewRequest(ep.Method, ep.Path, nil))

				if rec.Code != c.HTTP {
					t.Fatalf("status = %d, want %d (body %s)", rec.Code, c.HTTP, rec.Body)
				}
				if ct := rec.Header().Get("Content-Type"); !strings.HasPrefix(ct, "application/json") {
					t.Errorf("content-type = %q", ct)
				}
				var got, want any
				if err := json.Unmarshal(rec.Body.Bytes(), &got); err != nil {
					t.Fatalf("body is not JSON: %v: %s", err, rec.Body)
				}
				_ = json.Unmarshal(c.Body, &want)
				gb, _ := json.Marshal(got)
				wb, _ := json.Marshal(want)
				if string(gb) != string(wb) {
					t.Errorf("body = %s, want %s", gb, wb)
				}
			})
		}
	}
}

func TestFreshStateIsUnpairedWithoutCode(t *testing.T) {
	a := NewAuthState()
	if a.Status() != StatusUnpaired || a.QR() != "" {
		t.Fatalf("got %q / %q", a.Status(), a.QR())
	}
}

func TestSetQRKeepsStatus(t *testing.T) {
	a := NewAuthState()
	a.Set(StatusLoggedOut, "")
	a.SetQR("code")
	if a.Status() != StatusLoggedOut || a.QR() != "code" {
		t.Fatalf("got %q / %q", a.Status(), a.QR())
	}
}

func TestPairedClearsQR(t *testing.T) {
	a := NewAuthState()
	a.SetQR("code")
	a.Set(StatusPaired, "stale")
	if a.QR() != "" {
		t.Fatalf("paired state must not expose a QR, got %q", a.QR())
	}
}

// The API must expose nothing but the contract: no sending, no downloads, no writes.
func TestNoRoutesBeyondContract(t *testing.T) {
	h := NewAuthState().Handler()
	for _, p := range []string{"/", "/api", "/api/send", "/api/download", "/api/auth", "/api/auth/qr/extra", "/health"} {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, p, nil))
		if rec.Code != http.StatusNotFound {
			t.Errorf("GET %s = %d, want 404", p, rec.Code)
		}
	}
	for _, ep := range loadAPI(t) {
		for _, m := range []string{http.MethodPost, http.MethodPut, http.MethodDelete, http.MethodPatch} {
			rec := httptest.NewRecorder()
			h.ServeHTTP(rec, httptest.NewRequest(m, ep.Path, strings.NewReader("{}")))
			if rec.Code != http.StatusMethodNotAllowed {
				t.Errorf("%s %s = %d, want 405", m, ep.Path, rec.Code)
			}
		}
	}
}

func TestListenAddrIsLoopbackOnly(t *testing.T) {
	if got := ListenAddr("8080"); got != "127.0.0.1:8080" {
		t.Fatalf("got %q", got)
	}
}
