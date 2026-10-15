package bridge

import (
	"context"
	"database/sql"

	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/store/sqlstore"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
	waLog "go.mau.fi/whatsmeow/util/log"
)

// OpenSession opens (and upgrades) the WhatsApp session database on the pure-Go driver.
func OpenSession(ctx context.Context, path string) (*sqlstore.Container, error) {
	db, err := sql.Open("sqlite", "file:"+path+"?_pragma=foreign_keys(1)&_pragma=journal_mode(WAL)&_pragma=busy_timeout(5000)")
	if err != nil {
		return nil, err
	}
	c := sqlstore.NewWithDB(db, "sqlite3", nil)
	if err := c.Upgrade(ctx); err != nil {
		db.Close()
		return nil, err
	}
	return c, nil
}

// Client adapts a whatsmeow client to Linker and Names. This is deliberately glue only;
// the behaviour worth testing lives behind those two interfaces.
type Client struct{ wm *whatsmeow.Client }

func (c *Client) Linked() bool   { return c.wm.Store.ID != nil }
func (c *Client) Connect() error { return c.wm.Connect() }
func (c *Client) Disconnect()    { c.wm.Disconnect() }

func (c *Client) QRChannel(ctx context.Context) (<-chan QREvent, error) {
	in, err := c.wm.GetQRChannel(ctx)
	if err != nil {
		return nil, err
	}
	out := make(chan QREvent)
	go func() {
		defer close(out)
		for it := range in {
			ev := QREvent{Kind: KindError}
			switch it.Event {
			case whatsmeow.QRChannelEventCode:
				ev = QREvent{Kind: KindCode, Code: it.Code}
			case whatsmeow.QRChannelSuccess.Event:
				ev = QREvent{Kind: KindSuccess}
			case whatsmeow.QRChannelTimeout.Event:
				ev = QREvent{Kind: KindTimeout}
			}
			out <- ev
		}
	}()
	return out, nil
}

func (c *Client) Group(j types.JID) (string, error) {
	info, err := c.wm.GetGroupInfo(context.Background(), j)
	if err != nil {
		return "", err
	}
	return info.Name, nil
}

func (c *Client) Contact(j types.JID) (string, error) {
	info, err := c.wm.Store.Contacts.GetContact(context.Background(), j)
	return info.FullName, err
}

// Factory builds a Client on the first stored device (or a fresh one) and wires its
// events into the recorder. loggedOut is signalled, never blocked on.
func Factory(ctx context.Context, container *sqlstore.Container, st *Store, log waLog.Logger, loggedOut chan<- struct{}) func() (Linker, error) {
	return func() (Linker, error) {
		dev, err := container.GetFirstDevice(ctx)
		if err != nil {
			return nil, err
		}
		c := &Client{wm: whatsmeow.NewClient(dev, log)}
		rec := &Recorder{Store: st, Names: c, Self: func() string {
			if id := c.wm.Store.ID; id != nil {
				return id.User
			}
			return ""
		}}
		c.wm.AddEventHandler(func(evt any) {
			switch v := evt.(type) {
			case *events.Message:
				rec.OnMessage(v)
			case *events.HistorySync:
				rec.OnHistory(v.Data)
			case *events.LoggedOut:
				select {
				case loggedOut <- struct{}{}:
				default:
				}
			}
		})
		return c, nil
	}
}
