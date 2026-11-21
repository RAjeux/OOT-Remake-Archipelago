package main

import (
	"bytes"
	"encoding/json"
	"io"
	"log"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
)

const controlTestSecret = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
const controlTestHost = "127.0.0.1:38281"

func controlRequest(handler http.Handler, method, path, body string, edit func(*http.Request)) *httptest.ResponseRecorder {
	request := httptest.NewRequest(method, path, strings.NewReader(body))
	request.Host = controlTestHost
	request.Header.Set("Authorization", "Bearer "+controlTestSecret)
	request.Header.Set("Content-Type", "application/json")
	if edit != nil {
		edit(request)
	}
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	return response
}

func TestControlRejectsBrowserAndUnauthenticatedRequests(t *testing.T) {
	s := connectionFixture(t)
	handler := controlHandler(s, controlTestSecret, controlTestHost)
	epoch := s.connection.epoch
	for _, test := range []struct {
		name string
		edit func(*http.Request)
		code int
	}{
		{"no bearer", func(r *http.Request) { r.Header.Del("Authorization") }, 401},
		{"wrong bearer", func(r *http.Request) { r.Header.Set("Authorization", "Bearer stale-secret") }, 401},
		{"wrong scheme", func(r *http.Request) { r.Header.Set("Authorization", "Basic "+controlTestSecret) }, 401},
		{"duplicate bearer", func(r *http.Request) { r.Header.Add("Authorization", "Bearer "+controlTestSecret) }, 401},
		{"browser", func(r *http.Request) { r.Header.Set("Origin", "https://example.test") }, 403},
		{"empty origin", func(r *http.Request) { r.Header["Origin"] = []string{""} }, 403},
		{"null origin", func(r *http.Request) { r.Header.Set("Origin", "null") }, 403},
		{"origin casing", func(r *http.Request) { r.Header["origin"] = []string{""} }, 403},
	} {
		t.Run(test.name, func(t *testing.T) {
			response := controlRequest(handler, "POST", "/v1/disconnect", "{}", test.edit)
			if response.Code != test.code {
				t.Fatalf("status %d, want %d", response.Code, test.code)
			}
			if response.Header().Get("Access-Control-Allow-Origin") != "" ||
				response.Header().Get("Cache-Control") != "no-store" ||
				strings.Contains(response.Body.String(), controlTestSecret) {
				t.Fatal("invalid response privacy headers or leaked bearer")
			}
		})
	}
	if s.connection.epoch != epoch {
		t.Fatal("rejected request changed the native connection")
	}
}

func TestControlValidatesMethodEndpointAndWholeBodyBeforeMutation(t *testing.T) {
	s := connectionFixture(t)
	handler := controlHandler(s, controlTestSecret, controlTestHost)
	epoch := s.connection.epoch
	for _, test := range []struct {
		name, method, path, body string
		edit                     func(*http.Request)
		code                     int
	}{
		{name: "status POST", method: "POST", path: "/v1/status", body: "{}", code: 405},
		{name: "connect GET", method: "GET", path: "/v1/connect", code: 405},
		{name: "disconnect GET", method: "GET", path: "/v1/disconnect", code: 405},
		{name: "preflight", method: "OPTIONS", path: "/v1/connect", code: 405},
		{name: "unknown route", method: "POST", path: "/v1/other", body: "{}", code: 404},
		{name: "query", method: "GET", path: "/v1/status?secret=private", code: 400},
		{name: "proxy", method: "GET", path: "http://127.0.0.1:38281/v1/status", code: 400},
		{name: "host", method: "POST", path: "/v1/disconnect", body: "{}", edit: func(r *http.Request) { r.Host = "example.test" }, code: 400},
		{name: "GET body", method: "GET", path: "/v1/status", body: "{}", code: 400},
		{name: "wrong content type", method: "POST", path: "/v1/disconnect", body: "{}", edit: func(r *http.Request) { r.Header.Set("Content-Type", "text/plain") }, code: 415},
		{name: "null", method: "POST", path: "/v1/disconnect", body: "null", code: 400},
		{name: "empty", method: "POST", path: "/v1/disconnect", code: 400},
		{name: "unknown field", method: "POST", path: "/v1/disconnect", body: `{"password":"never-echo-this"}`, code: 400},
		{name: "trailing JSON", method: "POST", path: "/v1/disconnect", body: "{} {}", code: 400},
		{name: "missing fields", method: "POST", path: "/v1/connect", body: "{}", code: 400},
		{name: "missing password", method: "POST", path: "/v1/connect", body: `{"server":"localhost:3","password_mode":1,"auto_connect":true}`, code: 400},
		{name: "null boolean", method: "POST", path: "/v1/connect", body: `{"server":"localhost:3","password_mode":0,"auto_connect":null}`, code: 400},
		{name: "wrong boolean", method: "POST", path: "/v1/connect", body: `{"server":"localhost:3","password_mode":0,"auto_connect":"true"}`, code: 400},
		{name: "oversized", method: "POST", path: "/v1/disconnect", body: "{}" + strings.Repeat(" ", controlBodyLimit), code: 413},
		{name: "oversized chunked", method: "POST", path: "/v1/disconnect", body: "{}" + strings.Repeat(" ", controlBodyLimit), edit: func(r *http.Request) { r.ContentLength = -1; r.TransferEncoding = []string{"chunked"} }, code: 413},
	} {
		t.Run(test.name, func(t *testing.T) {
			response := controlRequest(handler, test.method, test.path, test.body, test.edit)
			if response.Code != test.code {
				t.Fatalf("status %d, want %d: %s", response.Code, test.code, response.Body.String())
			}
			if strings.Contains(response.Body.String(), "never-echo-this") || strings.Contains(response.Body.String(), "private") {
				t.Fatal("invalid request was reflected into the response")
			}
		})
	}
	if s.connection.epoch != epoch {
		t.Fatal("invalid HTTP request changed the native connection")
	}
}

func TestControlUsesNativeCommandsAndPreservesSafeStatus(t *testing.T) {
	s := connectionFixture(t)
	s.connection.protect = func(string) (string, error) { return "protected-room-password", nil }
	s.history = []networkItem{{Item: 10, Player: 2, Location: 21}}
	s.seen[20] = true
	handler := controlHandler(s, controlTestSecret, controlTestHost)
	plain := "room-password-should-never-be-returned"
	body := `{"server":"localhost:38281","password":"` + plain + `","password_mode":1,"auto_connect":false}`
	response := controlRequest(handler, "POST", "/v1/connect", body, nil)
	var result controlResponse
	if response.Code != 200 || json.Unmarshal(response.Body.Bytes(), &result) != nil || result.Result != 1 ||
		result.Info.Server != "ws://localhost:38281" || !result.Info.HasPassword || result.Info.AutoConnect || result.Info.State != "connecting" {
		t.Fatalf("unexpected connection response: %d %s", response.Code, response.Body.String())
	}
	for _, test := range []struct{ method, path, body string }{
		{"GET", "/v1/status", ""}, {"POST", "/v1/disconnect", "{}"},
	} {
		response = controlRequest(handler, test.method, test.path, test.body, nil)
		if response.Code != 200 || json.Unmarshal(response.Body.Bytes(), &result) != nil || result.Result != 1 {
			t.Fatalf("native command failed: %s", response.Body.String())
		}
		if strings.Contains(response.Body.String(), plain) || strings.Contains(response.Body.String(), "protected-room-password") ||
			strings.Contains(response.Body.String(), controlTestSecret) || strings.Contains(response.Body.String(), s.cfg.Token) {
			t.Fatal("safe connection info leaked credential or profile token")
		}
	}
	if result.Info.State != "disconnected" || !result.Info.HasPassword || len(s.history) != 1 || !s.seen[20] {
		t.Fatal("disconnect changed replay history, checks or saved password")
	}
	raw, err := os.ReadFile(filepath.Join(s.root, "native-session.json"))
	if err != nil || bytes.Contains(raw, []byte(plain)) || !bytes.Contains(raw, []byte("protected-room-password")) {
		t.Fatal("room password was not saved through the native credential protection")
	}
	response = controlRequest(handler, "POST", "/v1/connect", `{"server":"ws://user:private@localhost","password_mode":0,"auto_connect":true}`, nil)
	if response.Code != 200 || json.Unmarshal(response.Body.Bytes(), &result) != nil || result.Result != -1 || result.Info.ErrorCode != "invalid_server" || strings.Contains(response.Body.String(), "private") {
		t.Fatal("native validation or safe error result was bypassed")
	}
}

func startControlFixture(t *testing.T, s *Client) (controlDescriptor, string, *http.Client) {
	t.Helper()
	service, err := startConnectionService(s)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { service.server.Close() })
	file := filepath.Join(s.root, "connection-control.json")
	raw, err := os.ReadFile(file)
	var descriptor controlDescriptor
	if err != nil || json.Unmarshal(raw, &descriptor) != nil || descriptor.Version != 1 ||
		descriptor.Port < 1 || descriptor.Port > 65535 || descriptor.PID != os.Getpid() || descriptor.Token != s.cfg.Token {
		t.Fatal("invalid control descriptor")
	}
	secret := descriptor.Secret
	if runtime.GOOS == "windows" {
		secret, err = password(descriptor.ProtectedSecret)
		if err != nil || descriptor.Secret != "" || descriptor.ProtectedSecret == "" || bytes.Contains(raw, []byte(secret)) {
			t.Fatal("Windows descriptor did not protect its bearer with DPAPI")
		}
	} else if info, err := os.Stat(file); err != nil || info.Mode().Perm() != 0600 {
		t.Fatal("control descriptor is not restricted to its owner")
	}
	if len(secret) != 64 {
		t.Fatal("control bearer lacks 256 random bits")
	}
	client := &http.Client{Transport: &http.Transport{Proxy: nil}}
	t.Cleanup(client.CloseIdleConnections)
	return descriptor, secret, client
}

func TestControlPublishesProtectedDescriptorAndRejectsPreviousBearer(t *testing.T) {
	s := connectionFixture(t)
	var diagnostic connectionLog
	s.logger = log.New(&diagnostic, "", 0)
	descriptor, firstSecret, client := startControlFixture(t, s)
	_, secondSecret, _ := startControlFixture(t, s)
	if firstSecret == secondSecret {
		t.Fatal("control restart reused its bearer")
	}
	// The first listener represents a still-running old process. The newly
	// published secret cannot authenticate against that stale endpoint.
	url := "http://127.0.0.1:" + strconv.Itoa(descriptor.Port) + "/v1/status"
	for _, test := range []struct {
		secret string
		status int
	}{{firstSecret, 200}, {secondSecret, 401}} {
		request, _ := http.NewRequest("GET", url, nil)
		request.Header.Set("Authorization", "Bearer "+test.secret)
		response, err := client.Do(request)
		if err != nil {
			t.Fatal(err)
		}
		raw, err := io.ReadAll(response.Body)
		response.Body.Close()
		if err != nil || response.StatusCode != test.status || bytes.Contains(raw, []byte(firstSecret)) || bytes.Contains(raw, []byte(secondSecret)) {
			t.Fatal("live control authentication or secret redaction failed")
		}
	}
	if diagnostic.String() != "" {
		t.Fatal("control requests produced status or credential logs")
	}
	temps, _ := filepath.Glob(filepath.Join(s.root, ".connection-control-*.tmp"))
	if len(temps) != 0 {
		t.Fatal("descriptor publication left credential temporary files")
	}
}

func TestConcurrentControlRequestsShareOneNativeOwner(t *testing.T) {
	s := connectionFixture(t)
	owner := s.connection
	s.history = []networkItem{{Item: 10, Player: 2, Location: 21}}
	var protecting, maximum atomic.Int32
	s.connection.protect = func(string) (string, error) {
		active := protecting.Add(1)
		for old := maximum.Load(); active > old && !maximum.CompareAndSwap(old, active); old = maximum.Load() {
		}
		protecting.Add(-1)
		return "protected-concurrent-password", nil
	}
	handler := controlHandler(s, controlTestSecret, controlTestHost)
	var workers sync.WaitGroup
	for n := 0; n < 8; n++ {
		workers.Add(1)
		go func() {
			defer workers.Done()
			for n := 0; n < 8; n++ {
				for _, command := range []struct{ method, path, body string }{
					{"GET", "/v1/status", ""},
					{"POST", "/v1/connect", `{"server":"localhost:38281","password":"secret-concurrent-password","password_mode":1,"auto_connect":true}`},
					{"POST", "/v1/disconnect", "{}"},
				} {
					response := controlRequest(handler, command.method, command.path, command.body, nil)
					var result controlResponse
					if response.Code != 200 || json.Unmarshal(response.Body.Bytes(), &result) != nil || result.Result != 1 {
						t.Error("concurrent control command failed")
					}
				}
			}
		}()
	}
	workers.Wait()
	if maximum.Load() != 1 || s.connection != owner || len(s.history) != 1 {
		t.Fatal("control bypassed native command serialization or replaced its owner/history")
	}
	raw, err := os.ReadFile(filepath.Join(s.root, "native-session.json"))
	var persisted Config
	if err != nil || json.Unmarshal(raw, &persisted) != nil || persisted.Token != s.cfg.Token ||
		persisted.CursorHash != s.cfg.CursorHash || bytes.Contains(raw, []byte("secret-concurrent-password")) {
		t.Fatal("concurrent control commands damaged the profile or persisted plaintext")
	}
}

func TestControlPublicationFailureDoesNotReplaceDescriptor(t *testing.T) {
	s := connectionFixture(t)
	destination := filepath.Join(s.root, "connection-control.json")
	if err := os.Mkdir(destination, 0700); err != nil {
		t.Fatal(err)
	}
	marker := filepath.Join(destination, "preserve")
	if err := os.WriteFile(marker, []byte("previous descriptor is unavailable"), 0600); err != nil {
		t.Fatal(err)
	}
	service, err := startConnectionService(s)
	if err == nil || service != nil || strings.Contains(err.Error(), s.root) {
		t.Fatal("failed descriptor publication did not safely abort service startup")
	}
	if raw, err := os.ReadFile(marker); err != nil || string(raw) != "previous descriptor is unavailable" {
		t.Fatal("failed publication replaced an existing destination")
	}
	temps, _ := filepath.Glob(filepath.Join(s.root, ".connection-control-*.tmp"))
	if len(temps) != 0 {
		t.Fatal("failed publication left credential temporary files")
	}
}
