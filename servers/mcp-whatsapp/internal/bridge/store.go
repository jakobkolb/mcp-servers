package bridge

import (
	"database/sql"
	"time"

	_ "modernc.org/sqlite"

	"whatsapp-bridge/contract"
)

const timeFormat = "2006-01-02T15:04:05Z" // contract: UTC, fixed width

type Chat struct {
	JID, Name   string
	LastMessage time.Time
}

type Message struct {
	ID, ChatJID, Sender, Content string
	Time                         time.Time
	FromMe                       bool
	MediaType                    string
}

type Store struct{ db *sql.DB }

// Open creates or upgrades the database at path. WAL lets the Python server read
// while the bridge writes.
func Open(path string) (*Store, error) {
	db, err := sql.Open("sqlite", "file:"+path+"?_pragma=foreign_keys(1)&_pragma=journal_mode(WAL)&_pragma=busy_timeout(5000)")
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(1)
	if _, err := db.Exec(contract.Schema); err != nil {
		db.Close()
		return nil, err
	}
	// History messages used to store the full participant JID as sender; keep only the user part.
	if _, err := db.Exec(`UPDATE messages SET sender = substr(sender, 1, instr(sender, '@') - 1) WHERE instr(sender, '@') > 0`); err != nil {
		db.Close()
		return nil, err
	}
	return &Store{db: db}, nil
}

func (s *Store) Close() error { return s.db.Close() }

// SaveChat keeps the newest activity time and never replaces a name with an empty one.
func (s *Store) SaveChat(c Chat) error {
	_, err := s.db.Exec(`INSERT INTO chats (jid, name, last_message_time) VALUES (?, ?, ?)
		ON CONFLICT(jid) DO UPDATE SET
			name = COALESCE(NULLIF(excluded.name, ''), chats.name),
			last_message_time = MAX(chats.last_message_time, excluded.last_message_time)`,
		c.JID, c.Name, c.LastMessage.UTC().Format(timeFormat))
	return err
}

// SaveMessage upserts by (id, chat); messages with neither text nor media are dropped.
func (s *Store) SaveMessage(m Message) error {
	if m.Content == "" && m.MediaType == "" {
		return nil
	}
	_, err := s.db.Exec(`INSERT OR REPLACE INTO messages
		(id, chat_jid, sender, content, timestamp, is_from_me, media_type) VALUES (?, ?, ?, ?, ?, ?, ?)`,
		m.ID, m.ChatJID, m.Sender, m.Content, m.Time.UTC().Format(timeFormat), m.FromMe, m.MediaType)
	return err
}

// ReplaceContacts swaps the whole contacts table for names (user part -> name) in one transaction.
func (s *Store) ReplaceContacts(names map[string]string) error {
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	if _, err := tx.Exec("DELETE FROM contacts"); err != nil {
		return err
	}
	for user, name := range names {
		if _, err := tx.Exec("INSERT INTO contacts (user, name) VALUES (?, ?)", user, name); err != nil {
			return err
		}
	}
	return tx.Commit()
}

// ChatName returns the stored name, or "" for an unknown chat.
func (s *Store) ChatName(jid string) string {
	var name string
	if s.db.QueryRow("SELECT name FROM chats WHERE jid = ?", jid).Scan(&name) != nil {
		return ""
	}
	return name
}
