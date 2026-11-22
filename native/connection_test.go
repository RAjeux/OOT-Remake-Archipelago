package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/gorilla/websocket"
)

type connectionLog struct {
	mu   sync.Mutex
	data bytes.Buffer
}

func (b *connectionLog) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.data.Write(p)
}
func (b *connectionLog) String() string { b.mu.Lock(); defer b.mu.Unlock(); return b.data.String() }

func connectionFixture(t *testing.T) *Client {
	t.Helper()
	s := deathClient(t, true)
	raw, err := json.Marshal(s.cfg)
	if err != nil {
		t.Fatal(err)
	}
	var fields map[string]json.RawMessage
	json.Unmarshal(raw, &fields)
	fields["Baseline"] = json.RawMessage(`13`)
	fields["FutureMetadata"] = json.RawMessage(`{"retain":"yes"}`)
	raw, _ = json.Marshal(fields)
	if err := os.WriteFile(filepath.Join(s.root, "native-session.json"), raw, 0600); err != nil {
		t.Fatal(err)
	}
	return s
}

func waitConnection(t *testing.T, s *Client, state string) connectionInfo {
	t.Helper()
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		info := s.connectionInfo()
		if info.State == state {
			return info
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatalf("connection never reached %q: %+v", state, s.connectionInfo())
	return connectionInfo{}
}

func startConnectionManager(t *testing.T, s *Client) {
	t.Helper()
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() { s.runConnections(ctx); close(done) }()
	t.Cleanup(func() {
		cancel()
		select {
		case <-done:
		case <-time.After(3 * time.Second):
			t.Error("connection manager did not stop")
		}
	})
}

func TestConnectionEndpointNormalization(t *testing.T) {
	for input, expected := range map[string]string{
		"127.0.0.1:38281": "ws://127.0.0.1:38281", "archipelago.gg:12345": "wss://archipelago.gg:12345",
		" [::1]:38281 ": "ws://[::1]:38281", "ws://localhost:1/": "ws://localhost:1/",
		"wss://archipelago.gg:12345": "wss://archipelago.gg:12345", "example.com": "ws://example.com",
		"ws://archipelago.gg:12345":       "wss://archipelago.gg:12345",
		"Archipelago.GG.:12345":           "wss://Archipelago.GG.:12345",
		"ws://room.archipelago.gg:12345/": "wss://room.archipelago.gg:12345/",
		"archipelago.gg.example:12345":    "ws://archipelago.gg.example:12345",
		"fakearchipelago.gg:12345":        "ws://fakearchipelago.gg:12345",
		"ws://192.168.1.2:38281":          "ws://192.168.1.2:38281",
	} {
		got, ok := normalizeServer(input)
		if !ok || got != expected {
			t.Errorf("normalize %q: %q,%v; want %q", input, got, ok, expected)
		}
	}
	for _, input := range []string{"", "http://example.com", "ws://", "ws://a:0", "ws://a:65536", "ws://a:abc",
		"ws://a:", "::1:38281", "ws://a/private", "ws://a/?password=secret", "ws://a/?", "ws://a/#secret",
		"ws://user:secret@a", "server name:3", "ws://a\n", strings.Repeat("a", 2049)} {
		if _, ok := normalizeServer(input); ok {
			t.Errorf("accepted invalid endpoint %q", input)
		}
	}
}

func TestHostedLegacyEndpointUsesTLSWithoutPlaintextFallback(t *testing.T) {
	s := connectionFixture(t)
	s.cfg.Server = "ws://archipelago.gg:12345"
	s.connection = newConnectionControl(s.cfg)
	attempts := make(chan string, 4)
	s.connection.dial = func(_ context.Context, endpoint string) (*websocket.Conn, *http.Response, error) {
		attempts <- endpoint
		return nil, nil, errors.New("TLS certificate failure")
	}
	startConnectionManager(t, s)
	for attempt := 0; attempt < 2; attempt++ {
		select {
		case endpoint := <-attempts:
			if endpoint != "wss://archipelago.gg:12345" {
				t.Fatalf("hosted room dialed without TLS: %s", endpoint)
			}
		case <-time.After(2 * time.Second):
			t.Fatal("hosted connection was not attempted")
		}
		if attempt == 0 {
			waitConnection(t, s, "retrying")
			if got := s.connect("archipelago.gg:12345", "", 0, 1); got != 1 {
				t.Fatalf("retry setting: %d", got)
			}
		}
	}
}

func TestConnectionSettingsPreserveSeedAndCredentialSemantics(t *testing.T) {
	s := connectionFixture(t)
	before := s.cfg
	s.connection.protect = func(string) (string, error) { return "test-protected-value", nil }
	secret := "unit-test-password-é"
	if got := s.connect("127.0.0.1:38281", secret, 1, 0); got != 1 {
		t.Fatalf("save connection: %d", got)
	}
	info := s.connectionInfo()
	if info.Server != "ws://127.0.0.1:38281" || !info.HasPassword || info.AutoConnect || info.State != "connecting" {
		t.Fatalf("unexpected connection snapshot: %+v", info)
	}
	file := filepath.Join(s.root, "native-session.json")
	raw, _ := os.ReadFile(file)
	var fields map[string]json.RawMessage
	var future map[string]string
	json.Unmarshal(raw, &fields)
	json.Unmarshal(fields["FutureMetadata"], &future)
	if string(fields["Baseline"]) != "13" || future["retain"] != "yes" {
		t.Fatalf("connection edit lost unrelated profile fields: %s", raw)
	}
	snapshot, _ := json.Marshal(info)
	if bytes.Contains(raw, []byte(secret)) || bytes.Contains(snapshot, []byte(secret)) || bytes.Contains(snapshot, []byte("test-protected-value")) {
		t.Fatal("credentials leaked into settings or UI snapshot")
	}
	if s.cfg.Server != before.Server || s.cfg.Token != before.Token || s.cfg.Slot != before.Slot ||
		s.cfg.Room != before.Room || s.cfg.UUID != before.UUID || s.cfg.CursorHash != before.CursorHash {
		t.Fatal("connection edit mutated the generated seed configuration")
	}
	if got := s.connect("localhost:3", "ignored-field", 0, 1); got != 1 || !s.connectionInfo().HasPassword {
		t.Fatal("keep-password mode erased the saved credential")
	}
	s.mu.Lock()
	kept := s.connection.password == secret && s.connection.protected == "test-protected-value"
	s.mu.Unlock()
	if !kept {
		t.Fatal("keep-password mode replaced the current credential")
	}
	if got := s.connect("localhost:4", "", 2, 1); got != 1 || s.connectionInfo().HasPassword {
		t.Fatal("clear-password mode did not clear the saved credential")
	}
	raw, _ = os.ReadFile(file)
	var persisted Config
	json.Unmarshal(raw, &persisted)
	if persisted.ProtectedPassword != "" || persisted.AutoConnect == nil || !*persisted.AutoConnect {
		t.Fatal("clear-password/automatic setting did not persist")
	}
	if legacy := newConnectionControl(Config{}); !legacy.autoConnect || !legacy.desired {
		t.Fatal("old profiles no longer connect automatically")
	}
}

func TestConnectionSettingsFailureDoesNotReplaceLiveSettings(t *testing.T) {
	s := connectionFixture(t)
	before := s.connectionInfo()
	s.connection.protect = func(string) (string, error) { return "", errors.New("sensitive error text") }
	if got := s.connect("localhost:2", "secret", 1, 1); got != -3 || s.connectionInfo().Server != before.Server {
		t.Fatal("credential protection failure changed connection settings")
	}
	if got := s.connect("ws://user:secret@localhost", "", 0, 1); got != -1 {
		t.Fatal("credential-bearing endpoint was accepted")
	}
	if got := s.connect("localhost:2", "", 9, 1); got != -2 {
		t.Fatal("invalid password mode was accepted")
	}
	file := filepath.Join(s.root, "native-session.json")
	raw, _ := os.ReadFile(file)
	var fields map[string]json.RawMessage
	json.Unmarshal(raw, &fields)
	fields["Token"] = json.RawMessage(`"wrong-room"`)
	raw, _ = json.Marshal(fields)
	os.WriteFile(file, raw, 0600)
	if got := s.connect("localhost:2", "", 0, 1); got != -4 || s.connectionInfo().Server != before.Server {
		t.Fatal("binding/persistence failure changed connection settings")
	}
}

func TestUnreadableCredentialCanBeRepairedInMenu(t *testing.T) {
	s := connectionFixture(t)
	s.connection.protected = "unreadable-protected-password"
	s.initializePassword("", errors.New("DPAPI test failure"))
	info := s.connectionInfo()
	if info.ErrorCode != "credential_error" || !info.HasPassword || !info.AutoConnect || info.State != "disconnected" {
		t.Fatalf("unreadable password did not leave the menu available: %+v", info)
	}
	s.mu.Lock()
	desired := s.connection.desired
	s.mu.Unlock()
	if desired {
		t.Fatal("unreadable credentials were treated as an empty password")
	}
	if result := s.connect("localhost:38281", "", 0, 1); result != -3 {
		t.Fatal("keep mode accepted an unreadable saved password")
	}
	if result := s.connect("localhost:38281", "", 2, 1); result != 1 || s.connectionInfo().HasPassword {
		t.Fatal("clear mode could not repair the unreadable saved password")
	}
	s.mu.Lock()
	repaired := !s.connection.credentialError && s.connection.desired
	s.mu.Unlock()
	if !repaired {
		t.Fatal("repair did not enable the requested connection")
	}
}

func TestStaleSessionCannotClearNewSessionReadiness(t *testing.T) {
	s := connectionFixture(t)
	oldEpoch := s.connection.epoch
	s.connection.epoch++
	s.ready = true
	s.connection.state = "connected"
	s.history = []networkItem{{Item: 10, Player: 2, Location: 21}}
	s.death.pending = &deathData{Time: 1, Source: "Ami"}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := (&websocket.Upgrader{}).Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer conn.Close()
		conn.SetReadDeadline(time.Now().Add(time.Second))
		conn.WriteJSON([]packet{{"cmd": "RoomInfo", "seed_name": s.cfg.Room}})
		conn.ReadMessage()
	}))
	defer server.Close()
	conn, _, err := websocket.DefaultDialer.Dial("ws"+strings.TrimPrefix(server.URL, "http"), nil)
	if err != nil {
		t.Fatal(err)
	}
	if err = s.sessionEpoch(conn, "", oldEpoch); !errors.Is(err, errConnectionReplaced) {
		t.Fatalf("stale session was not rejected: %v", err)
	}
	s.mu.Lock()
	retained := s.ready && len(s.history) == 1 && s.death.pending != nil && s.connection.state == "connected"
	s.mu.Unlock()
	if !retained {
		t.Fatal("old session cleanup changed the current session")
	}
}

func TestManualDisconnectCancelsDialAndConnectInterruptsBackoff(t *testing.T) {
	s := connectionFixture(t)
	var diagnostic connectionLog
	s.logger = log.New(&diagnostic, "", 0)
	attempts := make(chan string, 12)
	s.connection.dial = func(ctx context.Context, endpoint string) (*websocket.Conn, *http.Response, error) {
		attempts <- endpoint
		if endpoint == s.cfg.Server {
			<-ctx.Done()
			return nil, nil, ctx.Err()
		}
		return nil, nil, errors.New("private URL/password must not reach logs")
	}
	startConnectionManager(t, s)
	select {
	case <-attempts:
	case <-time.After(time.Second):
		t.Fatal("initial automatic dial did not start")
	}
	s.disconnect()
	waitConnection(t, s, "disconnected")
	select {
	case endpoint := <-attempts:
		t.Fatalf("manual disconnect redialed %s", endpoint)
	case <-time.After(50 * time.Millisecond):
	}
	if got := s.connect("localhost:2", "", 0, 1); got != 1 {
		t.Fatal(got)
	}
	select {
	case endpoint := <-attempts:
		if endpoint != "ws://localhost:2" {
			t.Fatal(endpoint)
		}
	case <-time.After(time.Second):
		t.Fatal("manual connect did not wake the network manager")
	}
	waitConnection(t, s, "retrying")
	if got := s.connect("localhost:3", "", 0, 1); got != 1 {
		t.Fatal(got)
	}
	select {
	case endpoint := <-attempts:
		if endpoint != "ws://localhost:3" {
			t.Fatal(endpoint)
		}
	case <-time.After(400 * time.Millisecond):
		t.Fatal("connection edit waited for the old retry delay")
	}
	s.disconnect()
	// Wait for the manager to finish handling its last error before reading its log.
	s.connection.commandMu.Lock()
	s.connection.commandMu.Unlock()
	if strings.Contains(diagnostic.String(), "private URL/password") {
		t.Fatal("the raw network error leaked into logs")
	}
}

func connectionServer(t *testing.T, s *Client, kind string, arrivals *atomic.Int32, checks chan int) *httptest.Server {
	t.Helper()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := (&websocket.Upgrader{}).Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer conn.Close()
		attempt := int(arrivals.Add(1))
		room := s.cfg.Room
		if kind == "room" {
			room = "different-seed"
		}
		conn.SetReadDeadline(time.Now().Add(4 * time.Second))
		if conn.WriteJSON([]packet{{"cmd": "RoomInfo", "seed_name": room}}) != nil {
			return
		}
		var connect []packet
		if conn.ReadJSON(&connect) != nil {
			return
		}
		if kind == "refused" {
			conn.WriteJSON([]packet{{"cmd": "ConnectionRefused", "errors": []string{"InvalidPassword"}}})
			return
		}
		slot := s.cfg.Player
		if kind == "slot" {
			slot++
		}
		connected := packet{"cmd": "Connected", "slot": slot, "players": []packet{{"slot": s.cfg.Player, "name": s.cfg.Slot}},
			"checked_locations": []int{}, "slot_data": packet{"Token": s.cfg.Token, "Protocol": s.cfg.Protocol, "Checks": []int{20}, "reward_mode": s.cfg.RewardMode, "local_items": s.cfg.LocalItems}}
		if kind == "checked" {
			connected["checked_locations"] = []int{20, 999999}
		}
		if conn.WriteJSON([]packet{connected}) != nil {
			return
		}
		for {
			var packets []packet
			if conn.ReadJSON(&packets) != nil {
				return
			}
			for _, p := range packets {
				switch p["cmd"] {
				case "Get":
					keys, ok := p["keys"].([]any)
					if !ok || len(keys) != 1 {
						return
					}
					history := []networkItem{{Item: 10, Player: 2, Location: 21}}
					if attempt > 1 {
						history = append(history, networkItem{Item: 11, Player: 2, Location: 22})
					}
					if conn.WriteJSON([]packet{{"cmd": "ReceivedItems", "index": 0, "items": history},
						{"cmd": "Retrieved", "keys": packet{keys[0].(string): nil}}}) != nil {
						return
					}
				case "LocationChecks":
					if checks != nil {
						select {
						case checks <- 1:
						default:
						}
					}
					if conn.WriteJSON([]packet{{"cmd": "RoomUpdate", "checked_locations": []int{20}}}) != nil {
						return
					}
				}
			}
		}
	}))
	t.Cleanup(server.Close)
	return server
}

func TestConnectionManagerPreservesHistoryChecksAndDropsDeaths(t *testing.T) {
	s := connectionFixture(t)
	automatic := false
	s.cfg.AutoConnect = &automatic
	s.connection = newConnectionControl(s.cfg)
	var arrivals atomic.Int32
	checks := make(chan int, 4)
	server := connectionServer(t, s, "valid", &arrivals, checks)
	endpoint := "ws" + strings.TrimPrefix(server.URL, "http")
	startConnectionManager(t, s)
	if got := s.connect(endpoint, "", 0, 1); got != 1 {
		t.Fatal(got)
	}
	waitConnection(t, s, "connected")
	s.mu.Lock()
	oldEpoch := s.connection.epoch
	s.death.pending = &deathData{Time: 1, Source: "Ami"}
	s.death.outgoing = &deathData{Time: 2, Source: "Zelda"}
	if len(s.history) != 1 || s.history[0].Item != 10 {
		t.Fatal("first history missing")
	}
	s.mu.Unlock()
	s.disconnect()
	s.opened([]uint32{30}, false)
	s.mu.Lock()
	if s.ready || s.death.pending != nil || s.death.outgoing != nil || len(s.history) != 1 || !s.seen[20] {
		t.Fatal("disconnect lost state or retained a death")
	}
	if s.connectionCurrentLocked(oldEpoch) {
		t.Fatal("old session epoch survived disconnect")
	}
	s.mu.Unlock()
	if got := s.connect(endpoint, "", 0, 1); got != 1 {
		t.Fatal(got)
	}
	waitConnection(t, s, "connected")
	s.mu.Lock()
	if len(s.history) != 2 || s.history[0].Item != 10 || s.history[1].Item != 11 || s.cfg.CursorHash != 17 {
		t.Fatal("reconnection changed filtered indices or save binding")
	}
	if s.death.pending != nil || s.death.outgoing != nil {
		t.Fatal("reconnection replayed DeathLink")
	}
	s.mu.Unlock()
	select {
	case <-checks:
	case <-time.After(time.Second):
		t.Fatal("offline check was not sent after reconnect")
	}
	if arrivals.Load() != 2 {
		t.Fatalf("unexpected session count %d", arrivals.Load())
	}
}

func TestConnectionManagerRejectsWrongRoomSlotAndRefusal(t *testing.T) {
	for _, kind := range []string{"room", "slot", "refused"} {
		t.Run(kind, func(t *testing.T) {
			s := connectionFixture(t)
			automatic := false
			s.cfg.AutoConnect = &automatic
			s.connection = newConnectionControl(s.cfg)
			var arrivals atomic.Int32
			server := connectionServer(t, s, kind, &arrivals, nil)
			startConnectionManager(t, s)
			if got := s.connect("ws"+strings.TrimPrefix(server.URL, "http"), "", 0, 1); got != 1 {
				t.Fatal(got)
			}
			info := waitConnection(t, s, "retrying")
			want := map[string]string{"room": "wrong_room", "slot": "wrong_slot", "refused": "connection_refused"}[kind]
			if info.ErrorCode != want {
				t.Fatalf("unexpected safe error %+v", info)
			}
			s.mu.Lock()
			ready := s.ready
			s.mu.Unlock()
			if ready {
				t.Fatal("unmatched room reached item delivery")
			}
			s.disconnect()
		})
	}
}

func TestConcurrentConnectionCommandsAndStatus(t *testing.T) {
	s := connectionFixture(t)
	var workers sync.WaitGroup
	for n := 0; n < 8; n++ {
		workers.Add(1)
		go func() {
			defer workers.Done()
			for n := 0; n < 8; n++ {
				s.connectionInfo()
				if s.connect("localhost:38281", "", 0, 1) != 1 {
					t.Error("concurrent settings failed")
				}
				s.disconnect()
			}
		}()
	}
	workers.Wait()
	raw, _ := os.ReadFile(filepath.Join(s.root, "native-session.json"))
	var fields map[string]json.RawMessage
	if json.Unmarshal(raw, &fields) != nil || string(fields["Baseline"]) != "13" {
		t.Fatal("concurrent persistence damaged profile")
	}
}

func TestWindowsConnectionPasswordProtectionRoundTrip(t *testing.T) {
	if runtime.GOOS != "windows" {
		t.Skip("DPAPI is Windows-only")
	}
	plain := "connection-test-pässword"
	protected, err := protectPassword(plain)
	if err != nil || protected == "" || strings.Contains(protected, plain) {
		t.Fatalf("protect failed: %v", err)
	}
	decoded, err := password(protected)
	if err != nil || decoded != plain {
		t.Fatalf("DPAPI roundtrip failed: %v", err)
	}
}
