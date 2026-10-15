package bridge

import (
	"context"
	"log"
	"time"
)

const (
	KindCode    = "code"
	KindSuccess = "success"
	KindTimeout = "timeout"
	KindError   = "error"
)

// QREvent is a pairing progress event (a rotating code, success, or a failed attempt).
type QREvent struct{ Kind, Code string }

// Linker is the part of a WhatsApp client the pairing logic needs.
type Linker interface {
	Linked() bool // a device identity is stored
	QRChannel(ctx context.Context) (<-chan QREvent, error)
	Connect() error
	Disconnect()
}

func sleep(ctx context.Context, d time.Duration) bool {
	select {
	case <-time.After(d):
		return true
	case <-ctx.Done():
		return false
	}
}

// Pair publishes rotating codes into a until the device is linked. It never gives
// up on failures (the bridge must stay up for the scan), only on ctx.
func Pair(ctx context.Context, l Linker, a *AuthState, retry time.Duration) {
	for !l.Linked() && ctx.Err() == nil {
		qrs, err := l.QRChannel(ctx)
		if err == nil {
			err = l.Connect()
		}
		if err != nil {
			log.Printf("pairing: %v; retrying", err)
			l.Disconnect()
			if !sleep(ctx, retry) {
				return
			}
			continue
		}
		for ev := range qrs {
			switch ev.Kind {
			case KindCode:
				a.SetQR(ev.Code)
			case KindSuccess:
				a.Set(StatusPaired, "")
			default:
				a.SetQR("")
			}
		}
		if !l.Linked() {
			a.SetQR("")
			l.Disconnect()
			sleep(ctx, retry)
		}
	}
}

// Run keeps one client alive: it pairs when there is no identity, connects when
// there is, and starts over with a fresh client after loggedOut fires.
func Run(ctx context.Context, a *AuthState, newLinker func() (Linker, error), loggedOut <-chan struct{}, retry time.Duration) {
	for ctx.Err() == nil {
		l, err := newLinker()
		if err != nil {
			log.Printf("load device: %v; retrying", err)
			sleep(ctx, retry)
			continue
		}
		if !l.Linked() {
			pairCtx, stop := context.WithCancel(ctx)
			done := make(chan struct{})
			go func() { Pair(pairCtx, l, a, retry); close(done) }()
			select {
			case <-done:
			case <-loggedOut:
			}
			stop()
			<-done
		} else {
			for {
				if err := l.Connect(); err == nil {
					a.Set(StatusPaired, "")
					break
				}
				l.Disconnect()
				if !sleep(ctx, retry) {
					return
				}
			}
		}
		select {
		case <-loggedOut:
			log.Printf("logged out; waiting for a new pairing")
			a.Set(StatusLoggedOut, "")
			l.Disconnect()
		case <-ctx.Done():
			l.Disconnect()
			return
		}
	}
}
