package bridge

import (
	"context"
	"path/filepath"
	"testing"
)

// The WhatsApp session database must come up on the pure-Go SQLite driver: schema
// upgrade needs foreign keys on, and a fresh store must yield an unlinked device.
func TestOpenSessionCreatesAFreshUnlinkedDevice(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "whatsapp.db")

	c, err := OpenSession(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	dev, err := c.GetFirstDevice(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if dev.ID != nil {
		t.Fatalf("fresh store has a device identity: %v", dev.ID)
	}

	// Reopening an upgraded database must work too.
	if _, err := OpenSession(ctx, path); err != nil {
		t.Fatalf("reopen: %v", err)
	}
}
