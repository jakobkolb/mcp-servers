package bridge

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"
)

const fast = time.Millisecond

// fakeLinker plays one scripted pairing attempt per QRChannel call.
type fakeLinker struct {
	mu          sync.Mutex
	linked      bool
	attempts    [][]QREvent // events per attempt; a trailing KindSuccess links the device
	qrErr       error       // returned by QRChannel on the first call only
	connectErrs int         // number of Connect calls that fail first
	connects    int
	disconnects int
	qrCalls     int
	pending     chan QREvent
}

func (f *fakeLinker) Linked() bool { f.mu.Lock(); defer f.mu.Unlock(); return f.linked }

func (f *fakeLinker) QRChannel(ctx context.Context) (<-chan QREvent, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.qrCalls++
	if f.qrErr != nil && f.qrCalls == 1 {
		return nil, f.qrErr
	}
	f.pending = make(chan QREvent, 16)
	return f.pending, nil
}

// Connect plays the scripted events once the connection succeeds, like whatsmeow does:
// nothing is delivered (and nothing can be linked) before a successful connect.
func (f *fakeLinker) Connect() error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.connects++
	if f.connectErrs > 0 {
		f.connectErrs--
		return errors.New("dial failed")
	}
	if f.pending != nil {
		var evs []QREvent
		if len(f.attempts) > 0 {
			evs, f.attempts = f.attempts[0], f.attempts[1:]
		}
		for _, e := range evs {
			if e.Kind == KindSuccess {
				f.linked = true
			}
			f.pending <- e
		}
		close(f.pending)
		f.pending = nil
	}
	return nil
}

func (f *fakeLinker) Disconnect() { f.mu.Lock(); f.disconnects++; f.mu.Unlock() }

func TestPairPublishesRotatingCodesThenPaired(t *testing.T) {
	a := NewAuthState()
	l := &fakeLinker{attempts: [][]QREvent{{{Kind: KindCode, Code: "c1"}, {Kind: KindCode, Code: "c2"}, {Kind: KindSuccess}}}}
	Pair(context.Background(), l, a, fast)
	if a.Status() != StatusPaired || a.QR() != "" {
		t.Fatalf("status=%q qr=%q", a.Status(), a.QR())
	}
	if l.connects != 1 {
		t.Errorf("connects = %d", l.connects)
	}
}

func TestPairExposesCurrentCodeWhileWaiting(t *testing.T) {
	a := NewAuthState()
	gate := make(chan struct{})
	l := &gatedLinker{fakeLinker: &fakeLinker{}, gate: gate, events: []QREvent{{Kind: KindCode, Code: "c1"}, {Kind: KindCode, Code: "c2"}}}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() { Pair(ctx, l, a, fast); close(done) }()

	waitFor(t, func() bool { return a.QR() == "c2" })
	if a.Status() != StatusUnpaired {
		t.Errorf("status = %q while waiting for the scan", a.Status())
	}
	cancel()
	close(gate)
	<-done
}

// gatedLinker emits its events and then blocks (the user has not scanned yet).
type gatedLinker struct {
	*fakeLinker
	gate   chan struct{}
	events []QREvent
}

func (g *gatedLinker) QRChannel(ctx context.Context) (<-chan QREvent, error) {
	ch := make(chan QREvent)
	go func() {
		defer close(ch)
		for _, e := range g.events {
			ch <- e
		}
		select {
		case <-g.gate:
		case <-ctx.Done():
		}
	}()
	return ch, nil
}

func TestPairRetriesAfterTimeoutWithFreshChannel(t *testing.T) {
	a := NewAuthState()
	l := &fakeLinker{attempts: [][]QREvent{
		{{Kind: KindCode, Code: "c1"}, {Kind: KindTimeout}},
		{{Kind: KindCode, Code: "c2"}, {Kind: KindSuccess}},
	}}
	Pair(context.Background(), l, a, fast)
	if a.Status() != StatusPaired {
		t.Fatalf("status = %q", a.Status())
	}
	if l.qrCalls != 2 || l.disconnects < 1 {
		t.Errorf("qrCalls=%d disconnects=%d: a timed-out attempt must disconnect and start over", l.qrCalls, l.disconnects)
	}
}

func TestPairTimeoutClearsStaleCode(t *testing.T) {
	a := NewAuthState()
	l := &fakeLinker{attempts: [][]QREvent{{{Kind: KindCode, Code: "stale"}, {Kind: KindTimeout}}}}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	Pair(ctx, l, a, fast)
	if a.QR() != "" {
		t.Fatalf("expired code still served: %q", a.QR())
	}
}

func TestPairSurvivesConnectAndChannelErrors(t *testing.T) {
	a := NewAuthState()
	l := &fakeLinker{
		qrErr:       errors.New("no channel"),
		connectErrs: 2,
		attempts:    [][]QREvent{{{Kind: KindSuccess}}},
	}
	done := make(chan struct{})
	go func() { Pair(context.Background(), l, a, fast); close(done) }()
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("Pair gave up instead of retrying")
	}
	if a.Status() != StatusPaired {
		t.Fatalf("status = %q", a.Status())
	}
}

func TestPairStopsWhenContextIsCancelled(t *testing.T) {
	a := NewAuthState()
	l := &fakeLinker{connectErrs: 1 << 30}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() { Pair(ctx, l, a, 50*time.Millisecond); close(done) }()
	cancel()
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("Pair ignored cancellation")
	}
}

func TestPairReturnsImmediatelyWhenAlreadyLinked(t *testing.T) {
	a := NewAuthState()
	l := &fakeLinker{linked: true}
	Pair(context.Background(), l, a, fast)
	if l.qrCalls != 0 || l.connects != 0 {
		t.Fatalf("touched a linked device: qr=%d connect=%d", l.qrCalls, l.connects)
	}
}

func waitFor(t *testing.T, cond func() bool) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if cond() {
			return
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatal("condition not reached")
}

func TestRunConnectsAnAlreadyLinkedDevice(t *testing.T) {
	a := NewAuthState()
	l := &fakeLinker{linked: true}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() { Run(ctx, a, func() (Linker, error) { return l, nil }, make(chan struct{}), fast); close(done) }()

	waitFor(t, func() bool { return a.Status() == StatusPaired })
	cancel()
	<-done
	if l.connects != 1 || l.qrCalls != 0 || l.disconnects != 1 {
		t.Errorf("connects=%d qr=%d disconnects=%d", l.connects, l.qrCalls, l.disconnects)
	}
}

func TestRunRetriesConnectFailureWithoutDeclaringPaired(t *testing.T) {
	a := NewAuthState()
	l := &fakeLinker{linked: true, connectErrs: 2}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() { Run(ctx, a, func() (Linker, error) { return l, nil }, make(chan struct{}), fast); close(done) }()

	waitFor(t, func() bool { return a.Status() == StatusPaired })
	if l.connects != 3 {
		t.Errorf("connects = %d, want 3 (2 failures + success)", l.connects)
	}
	cancel()
	<-done
}

func TestRunPairsAFreshDevice(t *testing.T) {
	a := NewAuthState()
	l := &fakeLinker{attempts: [][]QREvent{{{Kind: KindCode, Code: "c1"}, {Kind: KindSuccess}}}}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() { Run(ctx, a, func() (Linker, error) { return l, nil }, make(chan struct{}), fast); close(done) }()
	waitFor(t, func() bool { return a.Status() == StatusPaired })
	cancel()
	<-done
}

// After the phone unlinks the device the bridge must report logged_out, keep serving a
// code for the new pairing, and recover on its own once it is scanned.
func TestRunRepairsAfterLogout(t *testing.T) {
	a := NewAuthState()
	first := &fakeLinker{linked: true}
	second := &gatedLinker{fakeLinker: &fakeLinker{}, gate: make(chan struct{}), events: []QREvent{{Kind: KindCode, Code: "fresh"}}}
	var mu sync.Mutex
	linkers := []Linker{first, second}
	newLinker := func() (Linker, error) {
		mu.Lock()
		defer mu.Unlock()
		l := linkers[0]
		if len(linkers) > 1 {
			linkers = linkers[1:]
		}
		return l, nil
	}
	loggedOut := make(chan struct{}, 1)
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() { Run(ctx, a, newLinker, loggedOut, fast); close(done) }()

	waitFor(t, func() bool { return a.Status() == StatusPaired })
	loggedOut <- struct{}{}

	waitFor(t, func() bool { return a.QR() == "fresh" })
	if a.Status() != StatusLoggedOut {
		t.Errorf("status = %q, want logged_out until the new scan succeeds", a.Status())
	}
	if first.disconnects < 1 {
		t.Error("old client was not disconnected")
	}
	cancel()
	close(second.gate)
	<-done
}

func TestRunRetriesWhenDeviceCannotBeLoaded(t *testing.T) {
	a := NewAuthState()
	l := &fakeLinker{linked: true}
	calls := 0
	newLinker := func() (Linker, error) {
		calls++
		if calls < 3 {
			return nil, errors.New("db locked")
		}
		return l, nil
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() { Run(ctx, a, newLinker, make(chan struct{}), fast); close(done) }()
	waitFor(t, func() bool { return a.Status() == StatusPaired })
	cancel()
	<-done
}
