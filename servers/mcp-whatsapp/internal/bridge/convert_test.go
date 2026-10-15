package bridge

import (
	"reflect"
	"testing"
	"time"

	"go.mau.fi/whatsmeow/proto/waCommon"
	"go.mau.fi/whatsmeow/proto/waE2E"
	"go.mau.fi/whatsmeow/proto/waHistorySync"
	"go.mau.fi/whatsmeow/proto/waWeb"
	"go.mau.fi/whatsmeow/types"
	"google.golang.org/protobuf/proto"
)

func TestExtract(t *testing.T) {
	cases := []struct {
		name      string
		msg       *waE2E.Message
		text, typ string
	}{
		{"nil", nil, "", ""},
		{"empty", &waE2E.Message{}, "", ""},
		{"plain", &waE2E.Message{Conversation: proto.String("hi")}, "hi", ""},
		{"extended", &waE2E.Message{ExtendedTextMessage: &waE2E.ExtendedTextMessage{Text: proto.String("link")}}, "link", ""},
		{"image caption", &waE2E.Message{ImageMessage: &waE2E.ImageMessage{Caption: proto.String("look")}}, "look", "image"},
		{"image no caption", &waE2E.Message{ImageMessage: &waE2E.ImageMessage{}}, "", "image"},
		{"video caption", &waE2E.Message{VideoMessage: &waE2E.VideoMessage{Caption: proto.String("clip")}}, "clip", "video"},
		{"audio", &waE2E.Message{AudioMessage: &waE2E.AudioMessage{}}, "", "audio"},
		{"document", &waE2E.Message{DocumentMessage: &waE2E.DocumentMessage{FileName: proto.String("a.pdf")}}, "", "document"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			text, typ := Extract(c.msg)
			if text != c.text || typ != c.typ {
				t.Fatalf("got (%q, %q), want (%q, %q)", text, typ, c.text, c.typ)
			}
		})
	}
}

func histMsg(id string, fromMe bool, participant string, ts uint64, m *waE2E.Message) *waHistorySync.HistorySyncMsg {
	key := &waCommon.MessageKey{ID: proto.String(id), FromMe: proto.Bool(fromMe)}
	if participant != "" {
		key.Participant = proto.String(participant)
	}
	return &waHistorySync.HistorySyncMsg{Message: &waWeb.WebMessageInfo{Key: key, Message: m, MessageTimestamp: proto.Uint64(ts)}}
}

func text(s string) *waE2E.Message { return &waE2E.Message{Conversation: proto.String(s)} }

func TestHistoryRecords(t *testing.T) {
	conv := &waHistorySync.Conversation{
		ID:          proto.String("123@g.us"),
		DisplayName: proto.String("Family"),
		Messages: []*waHistorySync.HistorySyncMsg{
			histMsg("m1", false, "4915@s.whatsapp.net", 1767262800, text("hello")),
			histMsg("m2", true, "", 1767262900, text("mine")),
			histMsg("m3", false, "4915@s.whatsapp.net", 1767263000, &waE2E.Message{}), // no content: skipped
			histMsg("m4", false, "4915@s.whatsapp.net", 0, text("no timestamp")),      // skipped
			{Message: nil}, // tolerated
		},
	}
	chat, msgs, ok := HistoryRecords(conv, "4900")
	if !ok {
		t.Fatal("conversation rejected")
	}
	if chat.JID != "123@g.us" || chat.Name != "Family" {
		t.Errorf("chat = %+v", chat)
	}
	if !chat.LastMessage.Equal(time.Unix(1767263000, 0)) && !chat.LastMessage.Equal(time.Unix(1767262900, 0)) {
		t.Errorf("last activity = %v", chat.LastMessage)
	}
	if len(msgs) != 2 {
		t.Fatalf("got %d messages: %+v", len(msgs), msgs)
	}
	if msgs[0].ID != "m1" || msgs[0].Sender != "4915" || msgs[0].FromMe || msgs[0].Content != "hello" || msgs[0].ChatJID != "123@g.us" {
		t.Errorf("m1 = %+v", msgs[0])
	}
	if msgs[1].ID != "m2" || !msgs[1].FromMe || msgs[1].Sender != "4900" {
		t.Errorf("m2 = %+v", msgs[1])
	}
}

func TestHistoryRecordsLastActivityIsNewestMessage(t *testing.T) {
	conv := &waHistorySync.Conversation{
		ID: proto.String("a@s.whatsapp.net"),
		Messages: []*waHistorySync.HistorySyncMsg{
			histMsg("old", false, "", 1000, text("a")),
			histMsg("new", false, "", 3000, text("b")),
			histMsg("mid", false, "", 2000, text("c")),
		},
	}
	chat, _, _ := HistoryRecords(conv, "x")
	if !chat.LastMessage.Equal(time.Unix(3000, 0)) {
		t.Fatalf("last = %v", chat.LastMessage)
	}
}

func TestHistoryRecordsDirectChatSenderIsTheChatUser(t *testing.T) {
	conv := &waHistorySync.Conversation{
		ID:       proto.String("4915@s.whatsapp.net"),
		Messages: []*waHistorySync.HistorySyncMsg{histMsg("m1", false, "", 1000, text("hi"))},
	}
	_, msgs, _ := HistoryRecords(conv, "4900")
	if len(msgs) != 1 || msgs[0].Sender != "4915" {
		t.Fatalf("msgs = %+v", msgs)
	}
}

func TestHistoryRecordsRejectsBadConversations(t *testing.T) {
	for name, conv := range map[string]*waHistorySync.Conversation{
		"no id":       {Messages: []*waHistorySync.HistorySyncMsg{histMsg("m", false, "", 1, text("x"))}},
		"invalid jid": {ID: proto.String("not a jid@@"), Messages: []*waHistorySync.HistorySyncMsg{histMsg("m", false, "", 1, text("x"))}},
		"no messages": {ID: proto.String("a@s.whatsapp.net")},
		"nil":         nil,
	} {
		if _, _, ok := HistoryRecords(conv, "x"); ok {
			t.Errorf("%s: accepted", name)
		}
	}
}

func TestContactNamesPrefersSavedNameAndCoversLID(t *testing.T) {
	pn := func(u string) types.JID { return types.NewJID(u, types.DefaultUserServer) }
	lid := func(u string) types.JID { return types.NewJID(u, types.HiddenUserServer) }
	all := map[types.JID]types.ContactInfo{
		pn("4915111"): {FullName: "Alice Saved", PushName: "Ali"}, // saved beats profile
		lid("9001"):   {PushName: "Ali (lid)"},                    // LID of Alice: saved name wins
		pn("4915222"): {PushName: "Bob"},                          // profile only
		pn("4915333"): {FirstName: "Carol"},                       // first name counts as saved
		pn("4915444"): {BusinessName: "Dave's Shop"},              // business name as profile fallback
		pn("4915555"): {},                                         // nothing known: no row
		lid("9006"):   {PushName: "Eve"},                          // unmapped LID keeps its profile name
	}
	lidOf := map[types.JID]types.JID{pn("4915111"): lid("9001"), pn("4915222"): lid("9002")}

	want := map[string]string{
		"4915111": "Alice Saved", "9001": "Alice Saved",
		"4915222": "Bob", "9002": "Bob",
		"4915333": "Carol", "4915444": "Dave's Shop", "9006": "Eve",
	}
	if got := ContactNames(all, lidOf); !reflect.DeepEqual(got, want) {
		t.Errorf("got %v\nwant %v", got, want)
	}
}
