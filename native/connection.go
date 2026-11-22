package main

/*
#include <stdint.h>
*/
import "C"

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode"
	"unicode/utf8"
	"unsafe"

	"github.com/gorilla/websocket"
)

var errConnectionReplaced = errors.New("connection request replaced")

// All fields except commandMu and the immutable function hooks use Client.mu.
// The generated seed configuration and active Client never change at runtime.
type connectionControl struct {
	commandMu                   sync.Mutex
	server, password, protected string
	autoConnect, desired        bool
	credentialError             bool
	epoch                       uint64
	state, errorCode            string
	wake                        chan struct{}
	cancel                      context.CancelFunc
	socket                      *websocket.Conn
	dial                        func(context.Context, string) (*websocket.Conn, *http.Response, error)
	protect                     func(string) (string, error)
}

func newConnectionControl(cfg Config) *connectionControl {
	auto := cfg.AutoConnect == nil || *cfg.AutoConnect
	server := cfg.Server
	if normalized, ok := normalizeServer(server); ok {
		server = normalized
	}
	return &connectionControl{
		server: server, protected: cfg.ProtectedPassword, autoConnect: auto,
		desired: auto, epoch: 1, state: "disconnected", wake: make(chan struct{}, 1),
		protect: protectPassword,
		dial: func(ctx context.Context, endpoint string) (*websocket.Conn, *http.Response, error) {
			dialer := *websocket.DefaultDialer
			dialer.HandshakeTimeout = 12 * time.Second
			dialer.EnableCompression = true
			return dialer.DialContext(ctx, endpoint, nil)
		},
	}
}

type connectionInfo struct {
	Server      string `json:"server"`
	Slot        string `json:"slot"`
	Room        string `json:"room"`
	State       string `json:"state"`
	ErrorCode   string `json:"error_code"`
	HasPassword bool   `json:"has_password"`
	AutoConnect bool   `json:"auto_connect"`
	Language    string `json:"language"`
}

func (s *Client) connectionInfo() connectionInfo {
	s.mu.Lock()
	defer s.mu.Unlock()
	c := s.connection
	return connectionInfo{c.server, s.cfg.Slot, s.cfg.Room, c.state, c.errorCode,
		c.password != "" || c.protected != "", c.autoConnect, s.cfg.Language}
}

//export AP_ConnectionInfo
func AP_ConnectionInfo(dest *C.char, capacity C.int) C.int {
	if active == nil || dest == nil || capacity < 256 || capacity > 16384 {
		return 0
	}
	raw, err := json.Marshal(active.connectionInfo())
	if err != nil || len(raw) >= int(capacity) {
		return 0
	}
	buffer := unsafe.Slice((*byte)(unsafe.Pointer(dest)), int(capacity))
	copy(buffer, raw)
	buffer[len(raw)] = 0
	return C.int(len(raw))
}

//export AP_Connect
func AP_Connect(server, pass *C.char, passwordMode, automatic C.int) C.int {
	if active == nil {
		return 0
	}
	if server == nil || (passwordMode == 1 && pass == nil) {
		return -2
	}
	secret := ""
	if pass != nil && passwordMode == 1 {
		secret = C.GoString(pass)
	}
	return C.int(active.connect(C.GoString(server), secret, int(passwordMode), int(automatic)))
}

//export AP_Disconnect
func AP_Disconnect() C.int {
	if active == nil {
		return 0
	}
	active.disconnect()
	return 1
}

func normalizeServer(input string) (string, bool) {
	if strings.IndexFunc(input, unicode.IsControl) >= 0 {
		return "", false
	}
	endpoint := strings.TrimSpace(input)
	if endpoint == "" || len(endpoint) > 2048 || !utf8.ValidString(endpoint) ||
		strings.IndexFunc(endpoint, func(r rune) bool { return unicode.IsControl(r) || unicode.IsSpace(r) }) >= 0 {
		return "", false
	}
	if !strings.Contains(endpoint, "://") {
		endpoint = "ws://" + endpoint
	}
	u, err := url.Parse(endpoint)
	if err != nil || (u.Scheme != "ws" && u.Scheme != "wss") || u.Hostname() == "" ||
		u.User != nil || u.RawQuery != "" || u.ForceQuery || u.Fragment != "" || u.Opaque != "" ||
		(u.Path != "" && u.Path != "/") || strings.HasSuffix(u.Host, ":") ||
		(strings.Count(u.Host, ":") > 1 && !strings.HasPrefix(u.Host, "[")) {
		return "", false
	}
	if port := u.Port(); port != "" {
		n, err := strconv.Atoi(port)
		if err != nil || n < 1 || n > 65535 {
			return "", false
		}
	}
	// Hosted rooms require TLS. Upgrade old saved ws:// addresses too; never
	// retry them in plaintext after a TLS or certificate failure.
	host := strings.TrimSuffix(strings.ToLower(u.Hostname()), ".")
	if host == "archipelago.gg" || strings.HasSuffix(host, ".archipelago.gg") {
		u.Scheme = "wss"
	}
	return u.String(), true
}

func (s *Client) connectionError(code string, result int) int {
	s.mu.Lock()
	s.connection.errorCode = code
	s.mu.Unlock()
	return result
}

func (s *Client) connect(server, secret string, mode, automatic int) int {
	endpoint, ok := normalizeServer(server)
	if !ok {
		return s.connectionError("invalid_server", -1)
	}
	if mode < 0 || mode > 2 || automatic < 0 || automatic > 1 || len(secret) > 4096 ||
		!utf8.ValidString(secret) || strings.ContainsRune(secret, 0) {
		return s.connectionError("invalid_password", -2)
	}
	c := s.connection
	c.commandMu.Lock()
	defer c.commandMu.Unlock()
	s.mu.Lock()
	plain, protected, badCredential := c.password, c.protected, c.credentialError
	s.mu.Unlock()
	if mode == 0 && badCredential {
		return s.connectionError("credential_error", -3)
	}
	if mode == 1 {
		plain = secret
		var err error
		protected, err = c.protect(secret)
		if err != nil {
			return s.connectionError("credential_error", -3)
		}
	} else if mode == 2 {
		plain, protected = "", ""
	}
	if err := s.saveConnection(endpoint, protected, automatic != 0); err != nil {
		return s.connectionError("settings_error", -4)
	}
	s.mu.Lock()
	c.server, c.password, c.protected, c.autoConnect = endpoint, plain, protected, automatic != 0
	c.credentialError = false
	c.desired, c.state, c.errorCode = true, "connecting", ""
	c.epoch++
	s.ready = false
	s.death.pending, s.death.outgoing = nil, nil
	cancel, socket := c.cancel, c.socket
	s.mu.Unlock()
	interruptConnection(cancel, socket)
	s.wakeConnection()
	return 1
}

func (s *Client) saveConnection(server, protected string, automatic bool) error {
	dest := filepath.Join(s.root, "native-session.json")
	raw, err := os.ReadFile(dest)
	if err != nil || len(raw) > 16<<20 {
		return errors.New("cannot read connection settings")
	}
	var fields map[string]json.RawMessage
	var bound Config
	if json.Unmarshal(raw, &fields) != nil || fields == nil || json.Unmarshal(raw, &bound) != nil ||
		bound.Token != s.cfg.Token || bound.Room != s.cfg.Room || bound.Slot != s.cfg.Slot ||
		bound.Player != s.cfg.Player || bound.Protocol != s.cfg.Protocol || bound.CursorHash != s.cfg.CursorHash {
		return errors.New("connection settings no longer match this mod")
	}
	fields["Server"], _ = json.Marshal(server)
	fields["ProtectedPassword"], _ = json.Marshal(protected)
	fields["AutoConnect"], _ = json.Marshal(automatic)
	updated, err := json.MarshalIndent(fields, "", "  ")
	if err != nil {
		return err
	}
	file, err := os.CreateTemp(s.root, ".native-session-*.tmp")
	if err != nil {
		return err
	}
	defer os.Remove(file.Name())
	if _, err = file.Write(append(updated, '\n')); err != nil {
		file.Close()
		return err
	}
	if err = file.Close(); err != nil {
		return err
	}
	return os.Rename(file.Name(), dest)
}

func interruptConnection(cancel context.CancelFunc, socket *websocket.Conn) {
	if cancel != nil {
		cancel()
	}
	if socket != nil {
		socket.Close()
	}
}

func (s *Client) wakeConnection() {
	select {
	case s.connection.wake <- struct{}{}:
	default:
	}
}

func (s *Client) disconnect() {
	c := s.connection
	c.commandMu.Lock()
	defer c.commandMu.Unlock()
	s.mu.Lock()
	c.desired, c.state, c.errorCode = false, "disconnected", ""
	c.epoch++
	s.ready = false
	s.death.pending, s.death.outgoing = nil, nil
	cancel, socket := c.cancel, c.socket
	s.mu.Unlock()
	interruptConnection(cancel, socket)
	s.wakeConnection()
}

func (s *Client) connectionCurrentLocked(epoch uint64) bool {
	return epoch == 0 || (s.connection.desired && s.connection.epoch == epoch)
}

func (s *Client) connectionCurrent(epoch uint64) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.connectionCurrentLocked(epoch)
}

func (s *Client) run() {
	go s.saveChecks()
	s.runConnections(context.Background())
}

func (s *Client) initializePassword(plain string, err error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.connection.password = plain
	if err != nil {
		s.connection.credentialError = true
		s.connection.desired = false
		s.connection.errorCode = "credential_error"
	}
}

func (s *Client) runConnections(ctx context.Context) {
	c := s.connection
	defer s.disconnect()
	delay := time.Second
	for ctx.Err() == nil {
		s.mu.Lock()
		epoch, desired, endpoint, secret := c.epoch, c.desired, c.server, c.password
		if desired {
			c.state = "connecting"
		}
		s.mu.Unlock()
		if !desired {
			select {
			case <-ctx.Done():
				return
			case <-c.wake:
				continue
			}
		}
		attempt, cancel := context.WithCancel(ctx)
		s.mu.Lock()
		if !s.connectionCurrentLocked(epoch) {
			s.mu.Unlock()
			cancel()
			continue
		}
		c.cancel = cancel
		s.mu.Unlock()
		start := time.Now()
		conn, response, err := c.dial(attempt, endpoint)
		if response != nil && err != nil {
			response.Body.Close()
		}
		s.mu.Lock()
		current := s.connectionCurrentLocked(epoch)
		if current && err == nil {
			c.socket, c.state = conn, "authenticating"
		}
		s.mu.Unlock()
		if !current {
			interruptConnection(cancel, conn)
			continue
		}
		if err == nil {
			// Cancelling a dial context does not close a connected WebSocket.
			stop := context.AfterFunc(attempt, func() { conn.Close() })
			err = s.sessionEpoch(conn, secret, epoch)
			stop()
		}
		cancel()
		if ctx.Err() != nil {
			return
		}
		s.mu.Lock()
		current = s.connectionCurrentLocked(epoch)
		if current {
			c.cancel, c.socket = nil, nil
			c.state, c.errorCode = "retrying", connectionErrorCode(err)
			s.ready = false
			s.death.pending, s.death.outgoing = nil, nil
		}
		s.mu.Unlock()
		if !current {
			delay = time.Second
			continue
		}
		// Never log arbitrary dial/server errors, which can contain credentials.
		s.logger.Print("Connection interrupted · ", connectionErrorCode(err))
		if time.Since(start) > 30*time.Second {
			delay = time.Second
		}
		timer := time.NewTimer(delay)
		waiting := true
		for waiting {
			select {
			case <-ctx.Done():
				timer.Stop()
				return
			case <-c.wake:
				// A buffered wake belonging to this attempt is already applied.
				if s.connectionCurrent(epoch) {
					continue
				}
				timer.Stop()
				delay, waiting = time.Second, false
			case <-timer.C:
				if delay < 16*time.Second {
					delay *= 2
				}
				waiting = false
			}
		}
	}
}

func connectionErrorCode(err error) string {
	if err == nil {
		return "connection_lost"
	}
	text := err.Error()
	switch {
	case text == "wrong room for this mod":
		return "wrong_room"
	case text == "this mod does not match the room slot":
		return "wrong_slot"
	case text == "unknown item for this mod version":
		return "unknown_item"
	case strings.HasPrefix(text, "connection refused:"):
		return "connection_refused"
	default:
		return "connection_failed"
	}
}
