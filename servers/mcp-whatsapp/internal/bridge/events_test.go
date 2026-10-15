package bridge

import (
	"errors"
	"testing"
	"time"

	"go.mau.fi/whatsmeow/proto/waCommon"
	"go.mau.fi/whatsmeow/proto/waE2E"
	"go.mau.fi/whatsmeow/proto/waHistorySync"
	"go.mau.fi/whatsmeow/proto/waWeb"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
	"google.golang.org/protobuf/proto"
)

type fakeNames struct {
	group, contact map[string]string
	calls          int
}

func (f *fakeNames) Group(j types.JID) (string, error) {
	f.calls++
	if n, ok := f.group[j.String()]; ok {
		return n, nil
	}
	return "", errors.New("unknown group")
}

func (f *fakeNames) Contact(j types.JID) (string, error) {
	f.calls++
	if n, ok := f.contact[j.String()]; ok {
		return n, nil
	}
	return "", errors.New("unknown contact")
}

func newRecorder(t *testing.T, n *fakeNames) (*Recorder, *Store) {
	s, _ := openStore(t)
	return &Recorder{Store: s, Names: n, Self: func() string { return "4900" }}, s
}

func msgEvent(chat, sender string, fromMe bool, id string, when time.Time, m *waE2E.Message) *events.Message {
	c, _ := types.ParseJID(chat)
	s, _ := types.ParseJID(sender)
	return &events.Message{
		Info:    types.MessageInfo{MessageSource: types.MessageSource{Chat: c, Sender: s, IsFromMe: fromMe, IsGroup: c.Server == types.GroupServer}, ID: id, Timestamp: when},
		Message: m,
	}
}

func count(t *testing.T, s *Store, q string) int {
	var n int
	if err := s.db.QueryRow(q).Scan(&n); err != nil {
		t.Fatal(err)
	}
	return n
}

func TestOnMessageStoresChatAndMessage(t *testing.T) {
	r, s := newRecorder(t, &fakeNames{contact: map[string]string{"4915@s.whatsapp.net": "Alice"}})
	r.OnMessage(msgEvent("4915@s.whatsapp.net", "4915@s.whatsapp.net", false, "m1", ts("2026-01-01T10:00:00Z"), text("hi")))

	if s.ChatName("4915@s.whatsapp.net") != "Alice" {
		t.Errorf("chat name = %q", s.ChatName("4915@s.whatsapp.net"))
	}
	var sender, content string
	var fromMe int
	s.db.QueryRow("SELECT sender, content, is_from_me FROM messages WHERE id='m1'").Scan(&sender, &content, &fromMe)
	if sender != "4915" || content != "hi" || fromMe != 0 {
		t.Errorf("row = %q %q %d", sender, content, fromMe)
	}
}

func TestOnMessageGroupUsesGroupName(t *testing.T) {
	r, s := newRecorder(t, &fakeNames{group: map[string]string{"1@g.us": "Family"}})
	r.OnMessage(msgEvent("1@g.us", "4915@s.whatsapp.net", false, "m1", ts("2026-01-01T10:00:00Z"), text("hi")))
	if got := s.ChatName("1@g.us"); got != "Family" {
		t.Fatalf("name = %q", got)
	}
}

func TestOnMessageFallsBackWhenNamesAreUnavailable(t *testing.T) {
	r, s := newRecorder(t, &fakeNames{})
	r.OnMessage(msgEvent("1@g.us", "4915@s.whatsapp.net", false, "g", ts("2026-01-01T10:00:00Z"), text("hi")))
	r.OnMessage(msgEvent("4916@s.whatsapp.net", "4916@s.whatsapp.net", false, "d", ts("2026-01-01T10:00:00Z"), text("hi")))
	if got := s.ChatName("1@g.us"); got != "Group 1" {
		t.Errorf("group fallback = %q", got)
	}
	if got := s.ChatName("4916@s.whatsapp.net"); got != "4916" {
		t.Errorf("contact fallback = %q", got)
	}
}

func TestOnMessageDoesNotRequeryKnownChats(t *testing.T) {
	names := &fakeNames{contact: map[string]string{"4915@s.whatsapp.net": "Alice"}}
	r, _ := newRecorder(t, names)
	for i, id := range []string{"a", "b", "c"} {
		r.OnMessage(msgEvent("4915@s.whatsapp.net", "4915@s.whatsapp.net", false, id, ts("2026-01-01T10:00:00Z").Add(time.Duration(i)*time.Minute), text("x")))
	}
	if names.calls != 1 {
		t.Fatalf("name lookups = %d, want 1", names.calls)
	}
}

func TestOnMessageIgnoresMessagesWithoutContent(t *testing.T) {
	r, s := newRecorder(t, &fakeNames{})
	r.OnMessage(msgEvent("4915@s.whatsapp.net", "4915@s.whatsapp.net", false, "m1", ts("2026-01-01T10:00:00Z"), &waE2E.Message{}))
	if n := count(t, s, "SELECT COUNT(*) FROM chats"); n != 0 {
		t.Fatalf("created %d chats for a content-less event", n)
	}
}

func TestOnMessageRecordsMedia(t *testing.T) {
	r, s := newRecorder(t, &fakeNames{})
	r.OnMessage(msgEvent("4915@s.whatsapp.net", "4915@s.whatsapp.net", true, "m1", ts("2026-01-01T10:00:00Z"),
		&waE2E.Message{AudioMessage: &waE2E.AudioMessage{}}))
	var media string
	var fromMe int
	s.db.QueryRow("SELECT media_type, is_from_me FROM messages").Scan(&media, &fromMe)
	if media != "audio" || fromMe != 1 {
		t.Fatalf("media=%q fromMe=%d", media, fromMe)
	}
}

func TestOnHistoryStoresConversations(t *testing.T) {
	r, s := newRecorder(t, &fakeNames{})
	mk := func(id string, ts uint64, body string) *waHistorySync.HistorySyncMsg {
		return &waHistorySync.HistorySyncMsg{Message: &waWeb.WebMessageInfo{
			Key:              &waCommon.MessageKey{ID: proto.String(id), FromMe: proto.Bool(false)},
			Message:          text(body),
			MessageTimestamp: proto.Uint64(ts),
		}}
	}
	r.OnHistory(&waHistorySync.HistorySync{Conversations: []*waHistorySync.Conversation{
		{ID: proto.String("4915@s.whatsapp.net"), Name: proto.String("Alice"), Messages: []*waHistorySync.HistorySyncMsg{mk("h1", 1767262800, "one"), mk("h2", 1767262900, "two")}},
		{ID: proto.String("1@g.us"), DisplayName: proto.String("Family"), Messages: []*waHistorySync.HistorySyncMsg{mk("h3", 1767263000, "three")}},
		{ID: proto.String("empty@s.whatsapp.net")},
	}})
	if n := count(t, s, "SELECT COUNT(*) FROM messages"); n != 3 {
		t.Errorf("messages = %d", n)
	}
	if n := count(t, s, "SELECT COUNT(*) FROM chats"); n != 2 {
		t.Errorf("chats = %d (empty conversations must not create chats)", n)
	}
	if s.ChatName("4915@s.whatsapp.net") != "Alice" || s.ChatName("1@g.us") != "Family" {
		t.Errorf("names = %q / %q", s.ChatName("4915@s.whatsapp.net"), s.ChatName("1@g.us"))
	}
}

func TestOnHistoryIsIdempotent(t *testing.T) {
	r, s := newRecorder(t, &fakeNames{})
	h := &waHistorySync.HistorySync{Conversations: []*waHistorySync.Conversation{{
		ID: proto.String("4915@s.whatsapp.net"),
		Messages: []*waHistorySync.HistorySyncMsg{{Message: &waWeb.WebMessageInfo{
			Key: &waCommon.MessageKey{ID: proto.String("h1")}, Message: text("x"), MessageTimestamp: proto.Uint64(1000),
		}}},
	}}}
	r.OnHistory(h)
	r.OnHistory(h)
	if n := count(t, s, "SELECT COUNT(*) FROM messages"); n != 1 {
		t.Fatalf("messages = %d", n)
	}
}
