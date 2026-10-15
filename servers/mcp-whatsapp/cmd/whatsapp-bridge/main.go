// Command whatsapp-bridge records WhatsApp messages read-only; see internal/bridge.
package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"

	waLog "go.mau.fi/whatsmeow/util/log"

	"whatsapp-bridge/internal/bridge"
)

func env(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	dir := env("WHATSAPP_STORE_DIR", "store")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		log.Fatal(err)
	}
	logger := waLog.Stdout("bridge", env("LOG_LEVEL", "INFO"), false)

	container, err := bridge.OpenSession(ctx, filepath.Join(dir, "whatsapp.db"))
	if err != nil {
		log.Fatal(err)
	}
	messages, err := bridge.Open(filepath.Join(dir, "messages.db"))
	if err != nil {
		log.Fatal(err)
	}
	defer messages.Close()

	auth := bridge.NewAuthState()
	srv := &http.Server{Addr: bridge.ListenAddr(env("WHATSAPP_BRIDGE_PORT", "8080")), Handler: auth.Handler(), ReadHeaderTimeout: 5 * time.Second}
	go func() {
		if err := srv.ListenAndServe(); err != http.ErrServerClosed {
			log.Fatal(err)
		}
	}()

	loggedOut := make(chan struct{}, 1)
	bridge.Run(ctx, auth, bridge.Factory(ctx, container, messages, logger, loggedOut), loggedOut, 5*time.Second)
	srv.Shutdown(context.Background())
}
