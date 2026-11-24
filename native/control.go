package main

import (
	"bytes"
	"crypto/rand"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"log"
	"mime"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"time"
)

const controlBodyLimit = 16 << 10

// This file only exposes commands on the existing native Client. The companion
// never owns an Archipelago socket, item history, save cursor or room lock.
type controlDescriptor struct {
	Version         int    `json:"version"`
	Port            int    `json:"port"`
	Secret          string `json:"secret,omitempty"`
	ProtectedSecret string `json:"protected_secret,omitempty"`
	PID             int    `json:"pid"`
	Token           string `json:"token"`
}

type connectionService struct {
	server *http.Server
}

// startConnectionService must run only after AP_Start has acquired the profile
// lock. Publishing the descriptor is the last startup step, after a successful
// loopback bind. A new bearer secret also invalidates any stale descriptor.
func startConnectionService(s *Client) (*connectionService, error) {
	listener, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		return nil, errors.New("local connection control unavailable")
	}
	started := false
	defer func() {
		if !started {
			listener.Close()
		}
	}()
	var random [32]byte
	if _, err = rand.Read(random[:]); err != nil {
		return nil, errors.New("local connection control unavailable")
	}
	secret := hex.EncodeToString(random[:])
	descriptor := controlDescriptor{Version: 1, Port: listener.Addr().(*net.TCPAddr).Port,
		PID: os.Getpid(), Token: s.cfg.Token}
	if runtime.GOOS == "windows" {
		descriptor.ProtectedSecret, err = protectPassword(secret)
		if err != nil || descriptor.ProtectedSecret == "" {
			return nil, errors.New("local connection control unavailable")
		}
	} else {
		// POSIX file permissions protect the bearer for native Linux development.
		descriptor.Secret = secret
	}
	server := &http.Server{
		Handler:           controlHandler(s, secret, listener.Addr().String()),
		ReadHeaderTimeout: 2 * time.Second,
		ReadTimeout:       5 * time.Second,
		WriteTimeout:      5 * time.Second,
		IdleTimeout:       15 * time.Second,
		MaxHeaderBytes:    8 << 10,
		ErrorLog:          log.New(io.Discard, "", 0),
	}
	if err = publishControlDescriptor(s.root, descriptor); err != nil {
		return nil, errors.New("local connection control unavailable")
	}
	started = true
	go func() {
		if err := server.Serve(listener); err != nil && !errors.Is(err, http.ErrServerClosed) {
			s.logger.Print("Local connection control stopped.")
		}
	}()
	return &connectionService{server: server}, nil
}

func publishControlDescriptor(root string, descriptor controlDescriptor) error {
	raw, err := json.Marshal(descriptor)
	if err != nil {
		return err
	}
	file, err := os.CreateTemp(root, ".connection-control-*.tmp")
	if err != nil {
		return err
	}
	defer os.Remove(file.Name())
	if err = file.Chmod(0600); err == nil {
		_, err = file.Write(append(raw, '\n'))
	}
	if err == nil {
		err = file.Sync()
	}
	closeErr := file.Close()
	if err != nil {
		return err
	}
	if closeErr != nil {
		return closeErr
	}
	return os.Rename(file.Name(), filepath.Join(root, "connection-control.json"))
}

type controlResponse struct {
	Result int            `json:"result"`
	Info   connectionInfo `json:"info"`
}

func controlJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(body)
}

func controlError(w http.ResponseWriter, status int, code string) {
	controlJSON(w, status, struct {
		Error string `json:"error"`
	}{code})
}

func controlHandler(s *Client, secret, host string) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		// Reject even an empty Origin header. Native companions have no Origin;
		// browser requests, preflights and all CORS attempts are unsupported.
		for key := range r.Header {
			if strings.EqualFold(key, "Origin") {
				controlError(w, http.StatusForbidden, "browser_forbidden")
				return
			}
		}
		auth := r.Header.Values("Authorization")
		if len(auth) != 1 || subtle.ConstantTimeCompare([]byte(auth[0]), []byte("Bearer "+secret)) != 1 {
			controlError(w, http.StatusUnauthorized, "unauthorized")
			return
		}
		// The service is not a proxy, and only the literal descriptor endpoint
		// is valid. Forwarded headers never affect this check or routing.
		if r.Host != host || r.URL.IsAbs() || r.URL.RawQuery != "" || r.URL.ForceQuery {
			controlError(w, http.StatusBadRequest, "invalid_request")
			return
		}
		method := ""
		switch r.URL.Path {
		case "/v1/status":
			method = http.MethodGet
		case "/v1/chat":
			method = r.Method
			if method != http.MethodGet && method != http.MethodPost {
				w.Header().Set("Allow", "GET, POST")
				controlError(w, http.StatusMethodNotAllowed, "method_not_allowed")
				return
			}
		case "/v1/connect", "/v1/disconnect":
			method = http.MethodPost
		default:
			controlError(w, http.StatusNotFound, "not_found")
			return
		}
		if r.Method != method {
			w.Header().Set("Allow", method)
			controlError(w, http.StatusMethodNotAllowed, "method_not_allowed")
			return
		}
		if method == http.MethodGet {
			if r.ContentLength != 0 || len(r.TransferEncoding) != 0 {
				controlError(w, http.StatusBadRequest, "invalid_request")
				return
			}
			if r.URL.Path == "/v1/chat" {
				controlJSON(w, http.StatusOK, s.chatReply(1, ""))
			} else {
				controlJSON(w, http.StatusOK, controlResponse{1, s.connectionInfo()})
			}
			return
		}
		if media, _, err := mime.ParseMediaType(r.Header.Get("Content-Type")); err != nil || media != "application/json" {
			controlError(w, http.StatusUnsupportedMediaType, "invalid_content_type")
			return
		}
		raw, err := io.ReadAll(http.MaxBytesReader(w, r.Body, controlBodyLimit))
		if err != nil {
			var oversized *http.MaxBytesError
			if errors.As(err, &oversized) {
				controlError(w, http.StatusRequestEntityTooLarge, "request_too_large")
			} else {
				controlError(w, http.StatusBadRequest, "invalid_request")
			}
			return
		}
		if r.URL.Path == "/v1/disconnect" {
			var request struct{}
			if !decodeControlJSON(raw, &request) {
				controlError(w, http.StatusBadRequest, "invalid_request")
				return
			}
			s.disconnect()
			controlJSON(w, http.StatusOK, controlResponse{1, s.connectionInfo()})
			return
		}
		if r.URL.Path == "/v1/chat" {
			var request struct {
				Text *string `json:"text"`
			}
			if !decodeControlJSON(raw, &request) || request.Text == nil {
				controlError(w, http.StatusBadRequest, "invalid_request")
				return
			}
			errorCode, result := s.say(*request.Text), 1
			if errorCode != "" {
				result = -1
			}
			controlJSON(w, http.StatusOK, s.chatReply(result, errorCode))
			return
		}
		var request struct {
			Server       *string `json:"server"`
			Password     *string `json:"password"`
			PasswordMode *int    `json:"password_mode"`
			AutoConnect  *bool   `json:"auto_connect"`
		}
		if !decodeControlJSON(raw, &request) || request.Server == nil || request.PasswordMode == nil ||
			request.AutoConnect == nil || (*request.PasswordMode == 1 && request.Password == nil) {
			controlError(w, http.StatusBadRequest, "invalid_request")
			return
		}
		plain := ""
		if request.Password != nil {
			plain = *request.Password
		}
		automatic := 0
		if *request.AutoConnect {
			automatic = 1
		}
		result := s.connect(*request.Server, plain, *request.PasswordMode, automatic)
		controlJSON(w, http.StatusOK, controlResponse{result, s.connectionInfo()})
	})
}

func decodeControlJSON(raw []byte, dest any) bool {
	// Require one JSON object, including for the empty disconnect command.
	raw = bytes.TrimSpace(raw)
	if len(raw) < 2 || raw[0] != '{' {
		return false
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if decoder.Decode(dest) != nil {
		return false
	}
	var extra any
	return errors.Is(decoder.Decode(&extra), io.EOF)
}
