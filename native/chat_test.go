package main

import (
	"encoding/json"
	"fmt"
	"strings"
	"sync"
	"testing"
)

func chatFixture(t *testing.T) *Client {
	s := connectionFixture(t)
	s.mu.Lock()
	s.connection.epoch = 7
	s.connection.desired = true
	s.connection.state = "connected"
	s.ready = true
	s.mu.Unlock()
	return s
}

func TestChatUsesExistingSenderAndNeverQueuesDisconnectedText(t *testing.T) {
	s := chatFixture(t)
	var sent []packet
	unbind := s.bindChat(7, func(p ...packet) error { sent = append(sent, p...); return nil })
	if code := s.say("!hint Bow"); code != "" || len(sent) != 1 || sent[0]["cmd"] != "Say" || sent[0]["text"] != "!hint Bow" {
		t.Fatal("chat did not use the room's current native writer")
	}
	s.disconnect()
	if code := s.say("do not send after disconnect"); code != "chat_disconnected" || len(sent) != 1 {
		t.Fatal("disconnected chat was sent or queued")
	}
	unbind()
	s.mu.Lock()
	s.connection.epoch++
	s.connection.desired, s.ready = true, true
	s.connection.state = "connected"
	epoch := s.connection.epoch
	s.mu.Unlock()
	s.bindChat(epoch, func(p ...packet) error { sent = append(sent, p...); return nil })
	if len(sent) != 1 {
		t.Fatal("reconnect replayed a disconnected chat message")
	}
}

func TestChatRejectsInvalidInputBeforeSending(t *testing.T) {
	s := chatFixture(t)
	sends := 0
	s.bindChat(7, func(...packet) error { sends++; return nil })
	for _, text := range []string{"", "   ", "line\nline", "tab\t", "\x00", strings.Repeat("a", 513), string([]byte{0xff})} {
		if code := s.say(text); code != "invalid_chat_message" {
			t.Fatalf("invalid chat accepted: %q", code)
		}
	}
	if sends != 0 {
		t.Fatal("an invalid chat message reached the server")
	}
}

func TestChatHistoryResolvesNamespacesAndRedactsCredentials(t *testing.T) {
	s := chatFixture(t)
	s.mu.Lock()
	s.connection.password = "private-room-password"
	s.cfg.Items[42] = "Zelda-only Bow"
	s.cfg.Checks[88] = Location{Name: "Zelda-only chest"}
	s.mu.Unlock()
	games := s.chatRoster(7, json.RawMessage(`{"1":{"name":"Friend","game":"Other game"},"2":{"name":"Link","game":"Zelda game"}}`))
	if len(games) != 2 {
		t.Fatal("chat did not request the actual room games")
	}
	s.chatPackage(7, json.RawMessage(`{"games":{"Other game":{"item_name_to_id":{"Other-game Boots":42},"location_name_to_id":{"Other-game Castle":88}}}}`))
	s.recordChat(7, json.RawMessage(`[{"type":"player_id","text":"1"},{"text":" found "},{"type":"item_id","text":"42","player":1},{"text":" at "},{"type":"location_id","text":"88","player":1}]`))
	s.recordChatText(7, "Do not expose private-room-password")
	rows := s.chatMessages()
	if len(rows) != 2 || rows[0].Text != "Friend found Other-game Boots at Other-game Castle" || strings.Contains(rows[1].Text, "private-room-password") {
		t.Fatalf("incorrect or unsafe chat rendering: %+v", rows)
	}
	s.recordChatText(6, "stale connection message")
	if len(s.chatMessages()) != 2 {
		t.Fatal("a replaced connection changed chat history")
	}
}

func TestChatBufferAndControlResponseAreBounded(t *testing.T) {
	s := chatFixture(t)
	for i := 0; i < 300; i++ {
		s.recordChatText(7, fmt.Sprintf("%03d", i)+strings.Repeat("<\\\"", 200))
	}
	if len(s.chat.rows) != chatHistoryLimit {
		t.Fatal("chat history exceeded its fixed memory bound")
	}
	handler := controlHandler(s, controlTestSecret, controlTestHost)
	response := controlRequest(handler, "GET", "/v1/chat", "", nil)
	if response.Code != 200 || response.Body.Len() > controlBodyLimit {
		t.Fatalf("chat response escaped its RPC bound: %d", response.Body.Len())
	}
	var reply chatResponse
	if json.Unmarshal(response.Body.Bytes(), &reply) != nil || len(reply.Messages) > chatReplyLimit || len(reply.Messages) == 0 {
		t.Fatal("chat response lost its recent message batch")
	}
}

func TestChatControlUsesExistingAuthorizationAndValidatesWholeRequest(t *testing.T) {
	s := chatFixture(t)
	var sent []packet
	s.bindChat(7, func(p ...packet) error { sent = append(sent, p...); return nil })
	handler := controlHandler(s, controlTestSecret, controlTestHost)
	for _, body := range []string{`{}`, `{"text":null}`, `{"text":"hello","password":"private"}`, `{"text":"hello"} {}`} {
		response := controlRequest(handler, "POST", "/v1/chat", body, nil)
		if response.Code != 400 || len(sent) != 0 || strings.Contains(response.Body.String(), "private") {
			t.Fatal("malformed chat command was accepted or reflected")
		}
	}
	response := controlRequest(handler, "POST", "/v1/chat", `{"text":"!hint"}`, nil)
	if response.Code != 200 || len(sent) != 1 || sent[0]["text"] != "!hint" {
		t.Fatal("authenticated chat command was not sent")
	}
	response = controlRequest(handler, "POST", "/v1/chat", `{"text":"hello\nworld"}`, nil)
	var reply chatResponse
	if response.Code != 200 || json.Unmarshal(response.Body.Bytes(), &reply) != nil || reply.Error != "invalid_chat_message" || len(sent) != 1 {
		t.Fatal("invalid text did not return a safe explicit error")
	}
}

func TestChatConcurrentReadersAndReplacedCleanup(t *testing.T) {
	s := chatFixture(t)
	oldCleanup := s.bindChat(7, func(...packet) error { return nil })
	s.mu.Lock()
	s.connection.epoch = 8
	s.mu.Unlock()
	s.bindChat(8, func(...packet) error { return nil })
	oldCleanup()
	if code := s.say("current connection"); code != "" {
		t.Fatal("old connection cleanup disabled the new chat writer")
	}
	var workers sync.WaitGroup
	for i := 0; i < 8; i++ {
		workers.Add(1)
		go func() {
			defer workers.Done()
			for j := 0; j < 100; j++ {
				s.recordChatText(8, "Server message")
				s.chatMessages()
				s.say("User message")
			}
		}()
	}
	workers.Wait()
}
