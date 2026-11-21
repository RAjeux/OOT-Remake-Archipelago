package main

import (
	"encoding/json"
	"io"
	"log"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gorilla/websocket"
)

func deathClient(t *testing.T, enabled bool) *Client {
	t.Helper()
	s, err := newClient(Config{Room: "room", Slot: "Zelda", Game: "Ocarina of Time Remake", Token: "token", Server: "ws://localhost:1", Player: 1, Protocol: 1, CursorHash: 17, DeathLink: enabled, Items: map[int]string{10: "Shield", 11: "Rupee"}, Checks: map[int]Location{20: {Flags: []uint32{30}}}}, t.TempDir(), log.New(io.Discard, "", 0))
	if err != nil {
		t.Fatal(err)
	}
	return s
}

func bounced(source string, when float64) wire {
	data, _ := json.Marshal(deathData{Time: when, Source: source})
	return wire{Cmd: "Bounced", Tags: []string{"DeathLink"}, Data: data}
}

func TestDeathLinkLifeBoundariesAndEcho(t *testing.T) {
	s := deathClient(t, true)
	s.ready = true
	now := time.Now()
	s.receiveDeath(bounced("Ami", 1), now) // title: ignored, including later duplicates
	if s.deathState(0, now) {
		t.Fatal("a title-screen DeathLink killed the next life")
	}
	s.receiveDeath(bounced("Ami", 1), now)
	if s.deathState(0, now) {
		t.Fatal("a duplicate title-screen event was replayed")
	}
	s.receiveDeath(bounced("Zelda", 2), now)
	if s.deathState(0, now) {
		t.Fatal("self bounce was accepted")
	}
	s.receiveDeath(bounced("Ami", 3), now)
	if !s.deathState(0, now) || s.deathState(0, now) {
		t.Fatal("remote death was not consumed exactly once")
	}
	s.deathState(1, now)
	if s.death.outgoing != nil {
		t.Fatal("remote death echoed as a local DeathLink")
	}
	s.receiveDeath(bounced("Ami", 4), now) // already dead
	s.deathState(0, now)
	if s.deathState(0, now) {
		t.Fatal("dead-screen DeathLink killed the respawn")
	}
	s.deathState(1, now)
	if s.death.outgoing == nil || s.death.outgoing.Source != "Zelda" {
		t.Fatal("local alive-to-dead transition was not sent")
	}
	s.death.outgoing = nil
	s.deathState(1, now)
	if s.death.outgoing != nil {
		t.Fatal("one local death was sent twice")
	}
	s.deathState(0, now)
	s.receiveDeath(bounced("Ami", 5), now)
	s.deathState(-1, now)
	if s.deathState(0, now) {
		t.Fatal("loading preserved a pending DeathLink")
	}
	s.receiveDeath(bounced("Ami", 6), now.Add(3*time.Second))
	if s.deathState(0, now.Add(3*time.Second)) {
		t.Fatal("stale gameplay state accepted a DeathLink")
	}
	s.receiveDeath(bounced("Ami", 7), now.Add(3*time.Second))
	if s.deathState(0, now.Add(8*time.Second)) {
		t.Fatal("a callback gap preserved a DeathLink for the next life")
	}
	s.deathState(1, now.Add(8*time.Second))
	if s.death.outgoing == nil {
		t.Fatal("local death missing")
	}
	s.deathState(-1, now.Add(8*time.Second))
	if s.death.outgoing == nil {
		t.Fatal("loading dropped a local death before the socket could send it")
	}
}

func TestDeathLinkRejectsMalformedEvents(t *testing.T) {
	s := deathClient(t, true)
	s.ready = true
	now := time.Now()
	s.deathState(0, now)
	for _, m := range []wire{
		{Data: json.RawMessage(`{"time":1,"source":"Ami"}`)},
		{Tags: []string{"DeathLink"}, Data: json.RawMessage(`{"time":0,"source":"Ami"}`)},
		{Tags: []string{"DeathLink"}, Data: json.RawMessage(`{"time":1,"source":""}`)},
		{Tags: []string{"DeathLink"}, Data: json.RawMessage(`{"time":"invalid","source":"Ami"}`)},
		{Tags: []string{"DeathLink"}, Data: json.RawMessage(`"invalid"`)},
		bounced(strings.Repeat("x", 257), 1),
	} {
		s.receiveDeath(m, now)
		if s.deathState(0, now) {
			t.Fatal("invalid DeathLink was accepted")
		}
	}
}

func TestDeathLinkHeldUntilNativeTransactionFinishes(t *testing.T) {
	s := deathClient(t, true)
	s.ready = true
	now := time.Now()
	if s.deathState(2, now) {
		t.Fatal("an event state consumed a death before receiving one")
	}
	s.receiveDeath(bounced("Ami", 100), now)
	for second := 1; second <= 8; second++ {
		if s.deathState(2, now.Add(time.Duration(second)*time.Second)) {
			t.Fatal("remote death interrupted a native purchase/get scene")
		}
		if s.death.pending == nil {
			t.Fatal("fresh event callbacks lost the pending DeathLink")
		}
	}
	if !s.deathState(0, now.Add(8500*time.Millisecond)) || s.deathState(0, now.Add(8600*time.Millisecond)) {
		t.Fatal("finishing the transaction did not consume exactly one death")
	}
	s.deathState(1, now.Add(8700*time.Millisecond))
	if s.death.outgoing != nil {
		t.Fatal("held remote death echoed after the transaction")
	}
	// An actual local death still propagates even when an event was active.
	s.deathState(2, now.Add(9*time.Second))
	s.deathState(1, now.Add(9500*time.Millisecond))
	if s.death.outgoing == nil {
		t.Fatal("a real local death during an event was suppressed")
	}
	// Loading and callback gaps still invalidate old deaths; hold is not a
	// longer lifetime for an event received at a title or a replaced save.
	s.death.outgoing = nil
	s.deathState(2, now.Add(10*time.Second))
	s.receiveDeath(bounced("Ami", 101), now.Add(10*time.Second))
	s.deathState(-1, now.Add(10500*time.Millisecond))
	if s.deathState(0, now.Add(11*time.Second)) {
		t.Fatal("loading carried a held death into a new life")
	}
	s.deathState(2, now.Add(12*time.Second))
	s.receiveDeath(bounced("Ami", 102), now.Add(12*time.Second))
	if s.deathState(0, now.Add(15*time.Second)) {
		t.Fatal("a stale event callback carried a death across a menu/title gap")
	}
}

// A protocol peer exercises the real WebSocket session, including its Sync/Get
// fence. It needs no game resources, Archipelago executable, or shipped DLL.
func nativePeer(t *testing.T, s *Client, history []networkItem) (*websocket.Conn, []string) {
	return nativePeerHandling(t, s, history, nil)
}

func nativePeerHandling(t *testing.T, s *Client, history []networkItem, handling *int) (*websocket.Conn, []string) {
	t.Helper()
	accepted := make(chan *websocket.Conn, 1)
	release := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := (&websocket.Upgrader{}).Upgrade(w, r, nil)
		if err != nil {
			return
		}
		accepted <- conn
		<-release
		conn.Close()
	}))
	client, _, err := websocket.DefaultDialer.Dial("ws"+strings.TrimPrefix(server.URL, "http"), nil)
	if err != nil {
		t.Fatal(err)
	}
	finished := make(chan error, 1)
	go func() { finished <- s.session(client, "") }()
	peer := <-accepted
	peer.SetReadDeadline(time.Now().Add(4 * time.Second))
	t.Cleanup(func() {
		peer.Close()
		select {
		case <-finished:
		case <-time.After(3 * time.Second):
			t.Error("native session did not stop")
		}
		close(release)
		server.Close()
	})
	write := func(p ...packet) {
		if err := peer.WriteJSON(p); err != nil {
			t.Fatal(err)
		}
	}
	read := func() []packet {
		var packets []packet
		if err := peer.ReadJSON(&packets); err != nil {
			t.Fatal(err)
		}
		return packets
	}
	write(packet{"cmd": "RoomInfo", "seed_name": s.cfg.Room})
	connect := read()
	if len(connect) != 1 || connect[0]["cmd"] != "Connect" {
		t.Fatalf("expected Connect, received %v", connect)
	}
	if handling != nil {
		*handling = int(connect[0]["items_handling"].(float64))
	}
	var tags []string
	for _, tag := range connect[0]["tags"].([]any) {
		tags = append(tags, tag.(string))
	}
	var checkIDs []int
	for id := range s.cfg.Checks {
		checkIDs = append(checkIDs, id)
	}
	write(packet{"cmd": "Connected", "slot": 1, "slot_data": packet{"token": "token", "protocol": 1, "checks": checkIDs, "reward_mode": s.cfg.RewardMode, "local_items": s.cfg.LocalItems}}, packet{"cmd": "ReceivedItems", "index": 0, "items": history})
	sync := read()
	if len(sync) != 2 || sync[0]["cmd"] != "Sync" || sync[1]["cmd"] != "Get" {
		t.Fatalf("expected Sync/Get fence, received %v", sync)
	}
	fence := sync[1]["keys"].([]any)[0].(string)
	write(packet{"cmd": "ReceivedItems", "index": 0, "items": history}, packet{"cmd": "Retrieved", "keys": packet{fence: nil}})
	deadline := time.Now().Add(3 * time.Second)
	for {
		s.mu.Lock()
		ready := s.ready
		s.mu.Unlock()
		if ready {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("session did not finish synchronization")
		}
		time.Sleep(time.Millisecond)
	}
	return peer, tags
}

func TestDeathLinkWireAndReconnect(t *testing.T) {
	s := deathClient(t, true)
	peer, tags := nativePeer(t, s, nil)
	if strings.Join(tags, ",") != "AP,DeathLink" {
		t.Fatalf("DeathLink not announced: %v", tags)
	}
	now := time.Now()
	s.deathState(0, now)
	s.deathState(1, now)
	var outbound []wire
	if err := peer.ReadJSON(&outbound); err != nil {
		t.Fatal(err)
	}
	if len(outbound) != 1 || outbound[0].Cmd != "Bounce" || len(outbound[0].Tags) != 1 || outbound[0].Tags[0] != "DeathLink" {
		t.Fatalf("incorrect DeathLink packet: %v", outbound)
	}
	var data deathData
	if err := json.Unmarshal(outbound[0].Data, &data); err != nil || data.Time <= 0 || data.Source != "Zelda" || !strings.Contains(data.Cause, "Zelda") {
		t.Fatalf("incorrect DeathLink data: %s", outbound[0].Data)
	}
	s.deathState(0, time.Now())
	if err := peer.WriteJSON([]wire{bounced("Ami", 73)}); err != nil {
		t.Fatal(err)
	}
	deadline := time.Now().Add(time.Second)
	for {
		s.mu.Lock()
		pending := s.death.pending != nil
		s.mu.Unlock()
		if pending {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("Bounced did not reach the gameplay queue")
		}
		time.Sleep(time.Millisecond)
	}
	peer.Close()
	deadline = time.Now().Add(time.Second)
	for {
		s.mu.Lock()
		ready := s.ready
		s.mu.Unlock()
		if !ready {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("session did not disconnect")
		}
		time.Sleep(time.Millisecond)
	}
	_, _ = nativePeer(t, s, nil)
	if s.deathState(0, time.Now()) {
		t.Fatal("reconnection replayed the pending death")
	}
	disabled := deathClient(t, false)
	_, tags = nativePeer(t, disabled, nil)
	if strings.Join(tags, ",") != "AP" {
		t.Fatalf("disabled DeathLink announced: %v", tags)
	}
	disabled.deathState(0, now)
	disabled.receiveDeath(bounced("Ami", 79), now)
	if disabled.deathState(0, now) || disabled.death.outgoing != nil {
		t.Fatal("disabled DeathLink has an effect")
	}
}

func TestReceivedItemsFreshClientReplay(t *testing.T) {
	before := []networkItem{{Item: 10, Player: 2, Location: 21}}
	first := deathClient(t, false)
	peer, _ := nativePeer(t, first, before)
	peer.Close() // the entire client is discarded; no in-memory history carries over
	after := append(append([]networkItem(nil), before...), networkItem{Item: 11, Player: 2, Location: 22})
	restarted := deathClient(t, false)
	_, _ = nativePeer(t, restarted, after)
	restarted.mu.Lock()
	defer restarted.mu.Unlock()
	if len(restarted.history) != 2 || restarted.history[0] != before[0] || restarted.history[1] != after[1] {
		t.Fatalf("historical items were lost or duplicated after a fresh client: %v", restarted.history)
	}
	// The game owns the saved cursor: index 1 delivers exactly the item sent while
	// closed, and index 2 is already caught up after saving and a second restart.
	if restarted.history[1].Item != 11 {
		t.Fatal("the saved game cursor would not select the offline delivery")
	}
}
