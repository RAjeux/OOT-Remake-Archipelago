package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/gorilla/websocket"
)

// Observe the actual WebSocket frames after TLS, rather than merely checking
// that the handshake advertised an extension.
type compressionWire struct {
	net.Conn
	mu             sync.Mutex
	received, sent bytes.Buffer
}

func (w *compressionWire) Read(p []byte) (int, error) {
	n, err := w.Conn.Read(p)
	w.mu.Lock()
	w.received.Write(p[:n])
	w.mu.Unlock()
	return n, err
}

func (w *compressionWire) Write(p []byte) (int, error) {
	n, err := w.Conn.Write(p)
	w.mu.Lock()
	w.sent.Write(p[:n])
	w.mu.Unlock()
	return n, err
}

type compressionResponse struct {
	http.ResponseWriter
	wire *compressionWire
}

func (w compressionResponse) Hijack() (net.Conn, *bufio.ReadWriter, error) {
	conn, buffer, err := w.ResponseWriter.(http.Hijacker).Hijack()
	if err != nil {
		return nil, nil, err
	}
	w.wire.Conn = conn
	return w.wire, buffer, nil
}

func TestConnectionCompressionNegotiationAndMessages(t *testing.T) {
	for _, secure := range []bool{false, true} {
		for _, compressed := range []bool{false, true} {
			t.Run(fmt.Sprintf("tls=%t/compression=%t", secure, compressed), func(t *testing.T) {
				wire := &compressionWire{}
				offered := make(chan string, 1)
				done := make(chan error, 1)
				messages := [][]byte{
					[]byte(`[{"cmd":"RoomInfo","seed_name":"` + strings.Repeat("room", 500) + `"}]`),
					[]byte(`[{"cmd":"ReceivedItems","items":[],"note":"` + strings.Repeat("different-data", 400) + `"}]`),
				}
				server := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
					offered <- r.Header.Get("Sec-WebSocket-Extensions")
					done <- func() error {
						upgrader := websocket.Upgrader{EnableCompression: compressed}
						conn, err := upgrader.Upgrade(compressionResponse{w, wire}, r, nil)
						if err != nil {
							return err
						}
						defer conn.Close()
						conn.SetReadDeadline(time.Now().Add(5 * time.Second))
						conn.SetWriteDeadline(time.Now().Add(5 * time.Second))
						for _, expected := range messages {
							kind, message, err := conn.ReadMessage()
							if err != nil {
								return err
							}
							if kind != websocket.TextMessage || !bytes.Equal(message, expected) {
								return fmt.Errorf("server received a corrupted message")
							}
							if err := conn.WriteMessage(websocket.TextMessage, expected); err != nil {
								return err
							}
						}
						return nil
					}()
				}))
				if secure {
					server.StartTLS()
				} else {
					server.Start()
				}
				defer server.Close()

				// Exercise the real connection-control constructor, with compression
				// disabled in the library default so the native setting is required.
				// No test is parallel: the temporary default only adds our test CA.
				original := websocket.DefaultDialer
				dialer := *original
				dialer.EnableCompression = false
				dialer.Proxy = nil
				if secure {
					roots := x509.NewCertPool()
					roots.AddCert(server.Certificate())
					dialer.TLSClientConfig = &tls.Config{RootCAs: roots}
				}
				conn, response, err := func() (*websocket.Conn, *http.Response, error) {
					websocket.DefaultDialer = &dialer
					defer func() { websocket.DefaultDialer = original }()
					control := newConnectionControl(Config{})
					ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
					defer cancel()
					return control.dial(ctx, "ws"+strings.TrimPrefix(server.URL, "http"))
				}()
				if err != nil {
					t.Fatal(err)
				}
				defer conn.Close()
				conn.SetReadDeadline(time.Now().Add(5 * time.Second))
				conn.SetWriteDeadline(time.Now().Add(5 * time.Second))
				if offer := <-offered; !strings.Contains(offer, "permessage-deflate") ||
					!strings.Contains(offer, "server_no_context_takeover") || !strings.Contains(offer, "client_no_context_takeover") {
					t.Fatalf("native dialer omitted the supported compression offer: %q", offer)
				}
				extension := response.Header.Get("Sec-WebSocket-Extensions")
				if strings.Contains(extension, "permessage-deflate") != compressed {
					t.Fatalf("unexpected compression negotiation: %q", extension)
				}
				for _, expected := range messages {
					if err := conn.WriteMessage(websocket.TextMessage, expected); err != nil {
						t.Fatal(err)
					}
					kind, message, err := conn.ReadMessage()
					if err != nil || kind != websocket.TextMessage || !bytes.Equal(message, expected) {
						t.Fatalf("client message round trip failed: type=%d, error=%v", kind, err)
					}
				}
				select {
				case err := <-done:
					if err != nil {
						t.Fatal(err)
					}
				case <-time.After(5 * time.Second):
					t.Fatal("compression server did not finish")
				}
				wire.mu.Lock()
				defer wire.mu.Unlock()
				_, serverFrames, ok := bytes.Cut(wire.sent.Bytes(), []byte("\r\n\r\n"))
				if !ok {
					t.Fatal("missing captured HTTP upgrade")
				}
				for direction, frames := range map[string][]byte{"client": wire.received.Bytes(), "server": serverFrames} {
					if len(frames) < 2 || frames[0]&15 != websocket.TextMessage || (frames[0]&0x40 != 0) != compressed {
						t.Fatalf("%s did not send the expected compressed=%t data frame", direction, compressed)
					}
				}
			})
		}
	}
}
