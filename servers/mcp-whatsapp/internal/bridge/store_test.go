package bridge

import (
	"database/sql"
	"path/filepath"
	"reflect"
	"testing"
	"time"

	_ "modernc.org/sqlite"
)

func openStore(t *testing.T) (*Store, string) {
	t.Helper()
	path := filepath.Join(t.TempDir(), "messages.db")
	s, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { s.Close() })
	return s, path
}

func ts(s string) time.Time {
	t, err := time.Parse(time.RFC3339, s)
	if err != nil {
		panic(err)
	}
	return t
}

func columns(t *testing.T, db *sql.DB, table string) []string {
	t.Helper()
	rows, err := db.Query("SELECT name FROM pragma_table_info(?) ORDER BY cid", table)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	var cols []string
	for rows.Next() {
		var c string
		rows.Scan(&c)
		cols = append(cols, c)
	}
	return cols
}

// The column set is the contract with the Python reader.
func TestSchemaColumns(t *testing.T) {
	s, _ := openStore(t)
	if got, want := columns(t, s.db, "chats"), []string{"jid", "name", "last_message_time"}; !reflect.DeepEqual(got, want) {
		t.Errorf("chats = %v, want %v", got, want)
	}
	want := []string{"id", "chat_jid", "sender", "content", "timestamp", "is_from_me", "media_type"}
	if got := columns(t, s.db, "messages"); !reflect.DeepEqual(got, want) {
		t.Errorf("messages = %v, want %v", got, want)
	}
}

func TestOpenIsIdempotentAndKeepsData(t *testing.T) {
	s, path := openStore(t)
	s.SaveChat(Chat{JID: "a@s.whatsapp.net", Name: "A", LastMessage: ts("2026-01-01T10:00:00Z")})
	s.Close()
	s2, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer s2.Close()
	if got := s2.ChatName("a@s.whatsapp.net"); got != "A" {
		t.Fatalf("name after reopen = %q", got)
	}
}

func TestTimestampsAreStoredAsUTCZ(t *testing.T) {
	s, _ := openStore(t)
	berlin := time.FixedZone("CET", 3600)
	when := time.Date(2026, 1, 2, 11, 30, 5, 999_000_000, berlin) // 10:30:05Z
	s.SaveChat(Chat{JID: "a@s.whatsapp.net", LastMessage: when})
	s.SaveMessage(Message{ID: "m1", ChatJID: "a@s.whatsapp.net", Content: "hi", Time: when})

	var chatTS, msgTS string
	s.db.QueryRow("SELECT last_message_time FROM chats").Scan(&chatTS)
	s.db.QueryRow("SELECT timestamp FROM messages").Scan(&msgTS)
	if chatTS != "2026-01-02T10:30:05Z" || msgTS != "2026-01-02T10:30:05Z" {
		t.Fatalf("got %q / %q", chatTS, msgTS)
	}
}

func TestSaveChatKeepsNewestActivityAndLatestNonEmptyName(t *testing.T) {
	s, _ := openStore(t)
	j := "a@s.whatsapp.net"
	s.SaveChat(Chat{JID: j, Name: "Old", LastMessage: ts("2026-01-02T00:00:00Z")})
	s.SaveChat(Chat{JID: j, Name: "", LastMessage: ts("2026-01-01T00:00:00Z")}) // older, nameless
	if got := s.ChatName(j); got != "Old" {
		t.Errorf("name = %q, an empty name must not erase a known one", got)
	}
	var last string
	s.db.QueryRow("SELECT last_message_time FROM chats WHERE jid = ?", j).Scan(&last)
	if last != "2026-01-02T00:00:00Z" {
		t.Errorf("last activity went backwards: %q", last)
	}
	s.SaveChat(Chat{JID: j, Name: "New", LastMessage: ts("2026-01-03T00:00:00Z")})
	if got := s.ChatName(j); got != "New" {
		t.Errorf("name = %q, want the newer non-empty name", got)
	}
}

func TestSaveMessageStoresEveryField(t *testing.T) {
	s, _ := openStore(t)
	j := "a@s.whatsapp.net"
	s.SaveChat(Chat{JID: j, LastMessage: ts("2026-01-01T10:00:00Z")})
	err := s.SaveMessage(Message{ID: "m1", ChatJID: j, Sender: "49123", Content: "hi", Time: ts("2026-01-01T10:00:00Z"), FromMe: true, MediaType: "image"})
	if err != nil {
		t.Fatal(err)
	}
	var id, chat, sender, content, stamp, media string
	var fromMe int
	s.db.QueryRow("SELECT id, chat_jid, sender, content, timestamp, is_from_me, media_type FROM messages").
		Scan(&id, &chat, &sender, &content, &stamp, &fromMe, &media)
	if id != "m1" || chat != j || sender != "49123" || content != "hi" || stamp != "2026-01-01T10:00:00Z" || fromMe != 1 || media != "image" {
		t.Fatalf("row = %v %v %v %v %v %v %v", id, chat, sender, content, stamp, fromMe, media)
	}
}

func TestSaveMessageIgnoresEmptyMessages(t *testing.T) {
	s, _ := openStore(t)
	j := "a@s.whatsapp.net"
	s.SaveChat(Chat{JID: j, LastMessage: ts("2026-01-01T10:00:00Z")})
	if err := s.SaveMessage(Message{ID: "m1", ChatJID: j, Time: ts("2026-01-01T10:00:00Z")}); err != nil {
		t.Fatal(err)
	}
	var n int
	s.db.QueryRow("SELECT COUNT(*) FROM messages").Scan(&n)
	if n != 0 {
		t.Fatalf("stored %d empty messages", n)
	}
}

func TestSaveMessageIsIdempotent(t *testing.T) {
	s, _ := openStore(t)
	j := "a@s.whatsapp.net"
	s.SaveChat(Chat{JID: j, LastMessage: ts("2026-01-01T10:00:00Z")})
	m := Message{ID: "m1", ChatJID: j, Content: "hi", Time: ts("2026-01-01T10:00:00Z")}
	s.SaveMessage(m)
	m.Content = "hi (edited)"
	s.SaveMessage(m)
	var n int
	var content string
	s.db.QueryRow("SELECT COUNT(*), MAX(content) FROM messages").Scan(&n, &content)
	if n != 1 || content != "hi (edited)" {
		t.Fatalf("n=%d content=%q", n, content)
	}
}

func TestSameMessageIDInTwoChatsKeepsBoth(t *testing.T) {
	s, _ := openStore(t)
	for _, j := range []string{"a@s.whatsapp.net", "b@s.whatsapp.net"} {
		s.SaveChat(Chat{JID: j, LastMessage: ts("2026-01-01T10:00:00Z")})
		s.SaveMessage(Message{ID: "same", ChatJID: j, Content: j, Time: ts("2026-01-01T10:00:00Z")})
	}
	var n int
	s.db.QueryRow("SELECT COUNT(*) FROM messages WHERE id = 'same'").Scan(&n)
	if n != 2 {
		t.Fatalf("n = %d", n)
	}
}

func TestMessageWithoutChatIsRejected(t *testing.T) {
	s, _ := openStore(t)
	err := s.SaveMessage(Message{ID: "m1", ChatJID: "ghost@s.whatsapp.net", Content: "x", Time: ts("2026-01-01T10:00:00Z")})
	if err == nil {
		t.Fatal("foreign keys must be enforced")
	}
}

func TestUnknownMediaTypeIsRejected(t *testing.T) {
	s, _ := openStore(t)
	j := "a@s.whatsapp.net"
	s.SaveChat(Chat{JID: j, LastMessage: ts("2026-01-01T10:00:00Z")})
	if err := s.SaveMessage(Message{ID: "m1", ChatJID: j, MediaType: "sticker", Time: ts("2026-01-01T10:00:00Z")}); err == nil {
		t.Fatal("media_type outside the contract must fail")
	}
}

func TestChatNameOfUnknownChatIsEmpty(t *testing.T) {
	s, _ := openStore(t)
	if got := s.ChatName("nope@s.whatsapp.net"); got != "" {
		t.Fatalf("got %q", got)
	}
}

func TestReaderCanReadWhileWriterIsOpen(t *testing.T) {
	s, path := openStore(t)
	j := "a@s.whatsapp.net"
	s.SaveChat(Chat{JID: j, Name: "A", LastMessage: ts("2026-01-01T10:00:00Z")})
	ro, err := sql.Open("sqlite", "file:"+path+"?mode=ro")
	if err != nil {
		t.Fatal(err)
	}
	defer ro.Close()
	var name string
	if err := ro.QueryRow("SELECT name FROM chats").Scan(&name); err != nil || name != "A" {
		t.Fatalf("name=%q err=%v", name, err)
	}
}

func TestReplaceContactsSwapsTheWholeTable(t *testing.T) {
	s, _ := openStore(t)
	if err := s.ReplaceContacts(map[string]string{"4915111": "Alice", "4915222": "Bob"}); err != nil {
		t.Fatal(err)
	}
	if err := s.ReplaceContacts(map[string]string{"4915111": "Alice Renamed"}); err != nil {
		t.Fatal(err)
	}
	var names []string
	rows, _ := s.db.Query("SELECT user || '=' || name FROM contacts ORDER BY user")
	for rows.Next() {
		var n string
		rows.Scan(&n)
		names = append(names, n)
	}
	rows.Close()
	if !reflect.DeepEqual(names, []string{"4915111=Alice Renamed"}) {
		t.Errorf("contacts = %v", names)
	}
}

func TestOpenStripsServerFromOldSenders(t *testing.T) {
	s, path := openStore(t)
	s.SaveChat(Chat{JID: "1@g.us", LastMessage: ts("2026-01-01T10:00:00Z")})
	s.db.Exec(`INSERT INTO messages (id, chat_jid, sender, content, timestamp) VALUES ('m1', '1@g.us', '4915111@s.whatsapp.net', 'hi', '2026-01-01T10:00:00Z')`)
	s.Close()

	s, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	var sender string
	s.db.QueryRow("SELECT sender FROM messages WHERE id = 'm1'").Scan(&sender)
	if sender != "4915111" {
		t.Errorf("sender = %q", sender)
	}
}
