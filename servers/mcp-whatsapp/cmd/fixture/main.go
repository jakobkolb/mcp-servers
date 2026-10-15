// Command fixture seeds a message database through the bridge's real writer. The Python
// integration tests read it back, proving both sides agree on contract/schema.sql.
package main

import (
	"log"
	"os"
	"path/filepath"
	"time"

	"whatsapp-bridge/internal/bridge"
)

func main() {
	s, err := bridge.Open(filepath.Join(os.Args[1], "messages.db"))
	if err != nil {
		log.Fatal(err)
	}
	defer s.Close()

	at := func(h, m int) time.Time { return time.Date(2026, 1, 2, h, m, 0, 0, time.FixedZone("CET", 3600)) }
	alice, bob, family := "4915111@s.whatsapp.net", "4915222@s.whatsapp.net", "120363@g.us"
	chats := []bridge.Chat{
		{JID: alice, Name: "Alice", LastMessage: at(11, 30)},
		{JID: bob, Name: "Bob", LastMessage: at(12, 0)},
		{JID: family, Name: "Family", LastMessage: at(9, 0)},
	}
	msgs := []bridge.Message{
		{ID: "a1", ChatJID: alice, Sender: "4915111", Content: "hello from alice", Time: at(10, 0)},
		{ID: "a2", ChatJID: alice, Sender: "4900", Content: "hi alice", Time: at(10, 5), FromMe: true},
		{ID: "a3", ChatJID: alice, Sender: "4915111", Content: "photo", Time: at(11, 30), MediaType: "image"},
		{ID: "b1", ChatJID: bob, Sender: "4915222", Content: "top secret", Time: at(12, 0)},
		{ID: "f1", ChatJID: family, Sender: "4915111", Content: "family hello", Time: at(9, 0)},
		{ID: "a1", ChatJID: family, Sender: "4915333", Content: "same id, other chat", Time: at(8, 0)},
	}
	for _, c := range chats {
		if err := s.SaveChat(c); err != nil {
			log.Fatal(err)
		}
	}
	for _, m := range msgs {
		if err := s.SaveMessage(m); err != nil {
			log.Fatal(err)
		}
	}
}
