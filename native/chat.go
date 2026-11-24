package main

import (
	"encoding/json"
	"sort"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"
)

const chatTextLimit = 512
const chatHistoryLimit = 128
const chatReplyLimit = 20

// The state belongs to one immutable room Client. It is guarded by Client.mu,
// is never persisted, and has no outgoing queue that could survive reconnects.
type chatState struct {
	epoch uint64
	send  func(...packet) error
	next  uint64
	rows  []chatMessage
	games map[int]string
	data  map[string]chatGame
}

type chatGame struct {
	Items     map[int]string
	Locations map[int]string
}

type chatMessage struct {
	ID   uint64 `json:"id"`
	Text string `json:"text"`
}

type chatResponse struct {
	Result   int            `json:"result"`
	Info     connectionInfo `json:"info"`
	Messages []chatMessage  `json:"messages"`
	Error    string         `json:"chat_error,omitempty"`
}

func (s *Client) bindChat(epoch uint64, send func(...packet) error) func() {
	s.mu.Lock()
	if s.chat == nil {
		s.chat = &chatState{}
	}
	if s.connectionCurrentLocked(epoch) {
		s.chat.epoch, s.chat.send = epoch, send
	}
	s.mu.Unlock()
	return func() {
		s.mu.Lock()
		if s.chat != nil && s.chat.epoch == epoch {
			s.chat.send = nil
		}
		s.mu.Unlock()
	}
}

func validChatText(text string) bool {
	if text == "" || strings.TrimSpace(text) == "" || len(text) > chatTextLimit || !utf8.ValidString(text) {
		return false
	}
	for _, character := range text {
		if unicode.IsControl(character) {
			return false
		}
	}
	return true
}

func (s *Client) say(text string) string {
	if !validChatText(text) {
		return "invalid_chat_message"
	}
	s.mu.Lock()
	if s.connection == nil || s.chat == nil || s.chat.send == nil || !s.ready ||
		s.connection.state != "connected" || !s.connectionCurrentLocked(s.chat.epoch) {
		s.mu.Unlock()
		return "chat_disconnected"
	}
	send := s.chat.send
	s.mu.Unlock()
	// The session's existing writer lock serializes this with checks, DeathLink
	// and synchronization. A replaced socket closes; no text is retried later.
	if err := send(packet{"cmd": "Say", "text": text}); err != nil {
		return "chat_disconnected"
	}
	return ""
}

func boundedChatText(text string) string {
	var output strings.Builder
	for _, character := range text {
		if unicode.IsControl(character) && character != '\n' {
			continue
		}
		if output.Len()+utf8.RuneLen(character) > chatTextLimit {
			break
		}
		output.WriteRune(character)
	}
	return strings.TrimSpace(output.String())
}

func (s *Client) recordChatText(epoch uint64, text string) {
	if !utf8.ValidString(text) {
		return
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if !s.connectionCurrentLocked(epoch) {
		return
	}
	// Authentication packets are never recorded. Also redact the current plain
	// password if a server happens to echo it in a printable server message.
	if s.connection != nil && s.connection.password != "" {
		text = strings.ReplaceAll(text, s.connection.password, "[redacted]")
	}
	text = boundedChatText(text)
	if text == "" {
		return
	}
	if s.chat == nil {
		s.chat = &chatState{}
	}
	s.chat.next++
	s.chat.rows = append(s.chat.rows, chatMessage{s.chat.next, text})
	if len(s.chat.rows) > chatHistoryLimit {
		s.chat.rows = append([]chatMessage(nil), s.chat.rows[len(s.chat.rows)-chatHistoryLimit:]...)
	}
}

func (s *Client) recordChat(epoch uint64, raw json.RawMessage) {
	if len(raw) > 64<<10 {
		return
	}
	var parts []struct {
		Text   string `json:"text"`
		Type   string `json:"type"`
		Player int    `json:"player"`
	}
	if json.Unmarshal(raw, &parts) != nil || len(parts) > 512 {
		return
	}
	var text strings.Builder
	s.mu.Lock()
	for _, part := range parts {
		value := part.Text
		if id, err := strconv.Atoi(part.Text); err == nil {
			switch part.Type {
			case "player_id":
				if name := s.names[id]; name != "" {
					value = name
				}
			case "item_id":
				if s.chat != nil && s.chat.data[s.chat.games[part.Player]].Items[id] != "" {
					value = s.chat.data[s.chat.games[part.Player]].Items[id]
				} else if (part.Player == 0 || part.Player == s.cfg.Player) && s.cfg.Items[id] != "" {
					name := s.cfg.Items[id]
					value = name
				}
			case "location_id":
				if s.chat != nil && s.chat.data[s.chat.games[part.Player]].Locations[id] != "" {
					value = s.chat.data[s.chat.games[part.Player]].Locations[id]
				} else if location, ok := s.cfg.Checks[id]; ok && (part.Player == 0 || part.Player == s.cfg.Player) {
					value = location.Name
				}
			}
		}
		text.WriteString(value)
		if text.Len() > 4*chatTextLimit {
			break
		}
	}
	s.mu.Unlock()
	s.recordChatText(epoch, text.String())
}

func (s *Client) chatRoster(epoch uint64, raw json.RawMessage) []string {
	var slots map[string]struct {
		Name string `json:"name"`
		Game string `json:"game"`
	}
	if len(raw) > 1<<20 || json.Unmarshal(raw, &slots) != nil || len(slots) > 10000 {
		return nil
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if !s.connectionCurrentLocked(epoch) {
		return nil
	}
	if s.chat == nil {
		s.chat = &chatState{}
	}
	s.chat.games = make(map[int]string)
	if s.chat.data == nil {
		s.chat.data = make(map[string]chatGame)
	}
	if s.names == nil {
		s.names = make(map[int]string)
	}
	games := make(map[string]bool)
	for key, slot := range slots {
		id, err := strconv.Atoi(key)
		if err != nil || id < 1 || slot.Game == "" || len(slot.Game) > 256 {
			continue
		}
		s.chat.games[id] = slot.Game
		if s.names[id] == "" {
			s.names[id] = boundedChatText(slot.Name)
		}
		games[slot.Game] = true
	}
	result := make([]string, 0, len(games))
	for game := range games {
		result = append(result, game)
	}
	sort.Strings(result)
	if len(result) > 128 {
		result = result[:128]
	}
	return result
}

func (s *Client) chatPackage(epoch uint64, raw json.RawMessage) {
	if len(raw) > 16<<20 {
		return
	}
	var data struct {
		Games map[string]struct {
			Items     map[string]int `json:"item_name_to_id"`
			Locations map[string]int `json:"location_name_to_id"`
		} `json:"games"`
	}
	if json.Unmarshal(raw, &data) != nil || len(data.Games) > 128 {
		return
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if !s.connectionCurrentLocked(epoch) || s.chat == nil {
		return
	}
	allowed := make(map[string]bool)
	for _, game := range s.chat.games {
		allowed[game] = true
	}
	for game, names := range data.Games {
		if !allowed[game] || len(names.Items) > 200000 || len(names.Locations) > 300000 {
			continue
		}
		entry := chatGame{Items: make(map[int]string), Locations: make(map[int]string)}
		for name, id := range names.Items {
			if len(name) <= 512 {
				entry.Items[id] = boundedChatText(name)
			}
		}
		for name, id := range names.Locations {
			if len(name) <= 512 {
				entry.Locations[id] = boundedChatText(name)
			}
		}
		s.chat.data[game] = entry
	}
}

func (s *Client) chatMessages() []chatMessage {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.chat == nil || len(s.chat.rows) == 0 {
		return []chatMessage{}
	}
	start := len(s.chat.rows) - chatReplyLimit
	if start < 0 {
		start = 0
	}
	return append([]chatMessage(nil), s.chat.rows[start:]...)
}

func (s *Client) chatReply(result int, errorCode string) chatResponse {
	reply := chatResponse{Result: result, Info: s.connectionInfo(), Messages: s.chatMessages(), Error: errorCode}
	// Quotes, HTML escapes and server-selected room names can expand JSON.
	// Keep the authenticated response inside the companion's existing bound.
	for len(reply.Messages) > 0 {
		raw, err := json.Marshal(reply)
		if err == nil && len(raw)+1 <= controlBodyLimit {
			break
		}
		reply.Messages = reply.Messages[1:]
	}
	return reply
}
