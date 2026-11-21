package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
)

// Zero means no host override. The game calls AP_SetLanguage before AP_Start;
// direct ABI users may instead set Config.Language. The host itself caches its
// desired language for the process lifetime, so reconnects retain this choice.
var hostLanguage atomic.Uint32

func normalizeLanguage(code string) string {
	switch strings.ToLower(strings.ReplaceAll(strings.TrimSpace(code), "_", "-")) {
	case "fr", "fr-fr", "fr-ca", "eufr", "usfr":
		return "fr"
	default:
		return "en"
	}
}

func setHostLanguage(code string) {
	value := uint32(1)
	if normalizeLanguage(code) == "fr" {
		value = 2
	}
	hostLanguage.Store(value)
}

func runtimeLanguage(config string) string {
	switch hostLanguage.Load() {
	case 1:
		return "en"
	case 2:
		return "fr"
	default:
		return normalizeLanguage(config)
	}
}

var messages = map[string][2]string{
	"active":         {"Archipelago mod active · %s", "Mod Archipelago actif · %s"},
	"connected":      {"Archipelago connected · %s", "Archipelago connecté · %s"},
	"item_received":  {"%s received from %s", "%s reçu de %s"},
	"item_sent":      {"%s sent to %s", "%s envoyé à %s"},
	"death_local":    {"%s died in Zelda.", "%s est mort dans Zelda."},
	"death_received": {"DeathLink · Shared death from %s", "DeathLink · Mort partagée de %s"},
}

func message(language, key string, args ...any) string {
	text, ok := messages[key]
	if !ok {
		return key
	}
	index := 0
	if normalizeLanguage(language) == "fr" {
		index = 1
	}
	return fmt.Sprintf(text[index], args...)
}

func (s *Client) text(key string, args ...any) string {
	return message(s.cfg.Language, key, args...)
}

func (s *Client) itemName(id int) string {
	if names := s.cfg.ItemNames[id]; names != nil {
		if name := names[s.cfg.Language]; name != "" {
			return name
		}
		if name := names["en"]; name != "" {
			return name
		}
	}
	return s.cfg.Items[id]
}

func (s *Client) zeldaItemName(name string) string {
	// The caller must establish the recipient's game before looking up a name.
	for id, canonical := range s.cfg.Items {
		if canonical == name {
			return s.itemName(id)
		}
	}
	return name
}

func (s *Client) notice(key string, args ...any) {
	s.queueNotice(message("en", key, args...), s.text(key, args...))
}

func (s *Client) noticeReceived(id int, player string) {
	s.queueNotice(message("en", "item_received", s.cfg.Items[id], player), s.text("item_received", s.itemName(id), player))
}

func zeldaGame(game string) bool {
	return game == "Ocarina of Time Remake" || game == "Ocarina of Time Remake (Triforce)"
}

func (s *Client) noticeLocation(loc Location) {
	name := loc.Item
	// A foreign game can use the same English item name (for example Bow).
	// Translate only when the recipient's game or own-slot identity proves it
	// belongs to this catalogue; legacy unknown-game records keep AP's name.
	if loc.Owner == s.cfg.Slot || (loc.Game != "" && (loc.Game == s.cfg.Game ||
		(zeldaGame(loc.Game) && zeldaGame(s.cfg.Game)))) {
		name = s.zeldaItemName(name)
	}
	s.queueNotice(message("en", "item_sent", loc.Item, loc.Owner), s.text("item_sent", name, loc.Owner))
}

func (s *Client) queueNotice(diagnostic, display string) {
	s.logger.Print(diagnostic)
	s.mu.Lock()
	defer s.mu.Unlock()
	if len(s.notices) < 512 {
		s.notices = append(s.notices, display)
	}
}

func saveLanguage(root, language string) error {
	raw, err := json.Marshal(struct {
		Language string `json:"language"`
	}{normalizeLanguage(language)})
	if err != nil {
		return err
	}
	dest := filepath.Join(root, "language.json")
	if err := os.WriteFile(dest+".tmp", append(raw, '\n'), 0600); err != nil {
		return err
	}
	return os.Rename(dest+".tmp", dest)
}
