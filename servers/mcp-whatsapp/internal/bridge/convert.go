package bridge

import (
	"time"

	"go.mau.fi/whatsmeow/proto/waE2E"
	"go.mau.fi/whatsmeow/proto/waHistorySync"
	"go.mau.fi/whatsmeow/types"
)

// Extract returns a message's text (or caption) and its media kind ("" for none).
func Extract(m *waE2E.Message) (text, mediaType string) {
	switch {
	case m == nil:
	case m.GetConversation() != "":
		text = m.GetConversation()
	case m.GetExtendedTextMessage() != nil:
		text = m.GetExtendedTextMessage().GetText()
	case m.GetImageMessage() != nil:
		text, mediaType = m.GetImageMessage().GetCaption(), "image"
	case m.GetVideoMessage() != nil:
		text, mediaType = m.GetVideoMessage().GetCaption(), "video"
	case m.GetAudioMessage() != nil:
		mediaType = "audio"
	case m.GetDocumentMessage() != nil:
		mediaType = "document"
	}
	return
}

// HistoryRecords converts a history-sync conversation. ok is false when the
// conversation has no usable id or no storable messages. Chat.Name is only the
// name hint carried by the conversation; the caller resolves a fallback.
func HistoryRecords(conv *waHistorySync.Conversation, selfUser string) (chat Chat, msgs []Message, ok bool) {
	jid, err := types.ParseJID(conv.GetID())
	if conv == nil || conv.GetID() == "" || err != nil || jid.IsEmpty() {
		return Chat{}, nil, false
	}
	chat = Chat{JID: jid.String(), Name: conv.GetDisplayName()}
	if chat.Name == "" {
		chat.Name = conv.GetName()
	}
	for _, hm := range conv.GetMessages() {
		wm := hm.GetMessage()
		ts := wm.GetMessageTimestamp()
		text, media := Extract(wm.GetMessage())
		if ts == 0 || (text == "" && media == "") {
			continue
		}
		key := wm.GetKey()
		sender := jid.User
		switch {
		case key.GetFromMe():
			sender = selfUser
		case key.GetParticipant() != "":
			sender = key.GetParticipant()
		}
		t := time.Unix(int64(ts), 0)
		if t.After(chat.LastMessage) {
			chat.LastMessage = t
		}
		msgs = append(msgs, Message{ID: key.GetID(), ChatJID: chat.JID, Sender: sender, Content: text, Time: t, FromMe: key.GetFromMe(), MediaType: media})
	}
	return chat, msgs, len(msgs) > 0
}
