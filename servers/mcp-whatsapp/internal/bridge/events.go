package bridge

import (
	"log"

	"go.mau.fi/whatsmeow/proto/waHistorySync"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
)

// Names resolves display names that are not in the event itself.
type Names interface {
	Group(types.JID) (string, error)
	Contact(types.JID) (string, error)
	Contacts() (map[string]string, error) // all sender names, see ContactNames
}

// Recorder turns WhatsApp events into rows.
type Recorder struct {
	Store *Store
	Names Names
	Self  func() string // own user part of the JID, for history messages sent by me
}

func (r *Recorder) name(jid types.JID, hint, sender string) string {
	if n := r.Store.ChatName(jid.String()); n != "" {
		return n
	}
	if hint != "" {
		return hint
	}
	if jid.Server == types.GroupServer {
		if n, err := r.Names.Group(jid); err == nil && n != "" {
			return n
		}
		return "Group " + jid.User
	}
	if n, err := r.Names.Contact(jid); err == nil && n != "" {
		return n
	}
	if sender != "" {
		return sender
	}
	return jid.User
}

// RefreshContacts rewrites the contacts table from the current names.
func (r *Recorder) RefreshContacts() {
	names, err := r.Names.Contacts()
	if err == nil {
		err = r.Store.ReplaceContacts(names)
	}
	if err != nil {
		log.Printf("store contacts: %v", err)
	}
}

func (r *Recorder) OnMessage(e *events.Message) {
	text, media := Extract(e.Message)
	if text == "" && media == "" {
		return
	}
	chat := e.Info.Chat.String()
	err := r.Store.SaveChat(Chat{JID: chat, Name: r.name(e.Info.Chat, "", e.Info.Sender.User), LastMessage: e.Info.Timestamp})
	if err == nil {
		err = r.Store.SaveMessage(Message{ID: e.Info.ID, ChatJID: chat, Sender: e.Info.Sender.User, Content: text,
			Time: e.Info.Timestamp, FromMe: e.Info.IsFromMe, MediaType: media})
	}
	if err != nil {
		log.Printf("store message: %v", err)
	}
}

func (r *Recorder) OnHistory(h *waHistorySync.HistorySync) {
	n := 0
	for _, conv := range h.GetConversations() {
		chat, msgs, ok := HistoryRecords(conv, r.Self())
		if !ok {
			continue
		}
		jid, _ := types.ParseJID(chat.JID)
		chat.Name = r.name(jid, chat.Name, "")
		if err := r.Store.SaveChat(chat); err != nil {
			log.Printf("store chat: %v", err)
			continue
		}
		for _, m := range msgs {
			if err := r.Store.SaveMessage(m); err != nil {
				log.Printf("store message: %v", err)
				continue
			}
			n++
		}
	}
	log.Printf("history sync: stored %d messages", n)
}
